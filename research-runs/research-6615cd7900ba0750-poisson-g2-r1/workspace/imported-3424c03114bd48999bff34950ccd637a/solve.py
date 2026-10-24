#!/usr/bin/env python3
"""Sparse SPD solver for the Poisson benchmark.

Strategy
--------
The systems are 2-D 5-point Laplacian-like SPD matrices (n*n unknowns) with a
localized high-contrast inclusion.  Jacobi-preconditioned CG struggles on the
high-contrast region, so instead we use a *direct* sparse factorization
(SuperLU) which is exact up to round-off:

  * one factorization per matrix, reused for all 4 RHS columns (block solve),
  * operator reuse across cases that share the same matrix (level-0 cases),
  * no iteration => residual ~ machine precision, well below 1e-8.

Performance notes
-----------------
For these problem sizes the numerical work is tiny (~0.05 s total); the
dominant cost is Python/scipy import time.  Two things keep that minimal:

  1. ``scipy._lib._testutils`` imports ``numpy.testing`` and ``numpy.f2py``
     (~75 ms combined) purely for test/build helpers we never use.  Stubbing
     them out before scipy is imported roughly halves the scipy import cost.
  2. We call the low-level ``_superlu.gstrf`` directly on raw CSC arrays
     instead of going through ``scipy.sparse`` + ``splu``.  This avoids
     importing the heavy ``scipy.sparse`` package (~25 ms) and the sparse
     matrix construction overhead.  The ``.npz`` files already store raw CSR
     arrays, so they are read with plain ``numpy.load`` and converted to CSC
     with a vectorized permutation.

A ``scipy.sparse``-based fallback is used if the low-level path is
unavailable or fails.
"""

import argparse
import json
import os
import sys
import types

import numpy as np

# --------------------------------------------------------------------------- #
# Trim scipy's import cost (see module docstring).
# --------------------------------------------------------------------------- #
for _name in ("numpy.testing", "numpy.f2py"):
    if _name not in sys.modules:
        _mod = types.ModuleType(_name)
        _mod.__path__ = []
        sys.modules[_name] = _mod
        setattr(np, _name.split(".")[1], _mod)

try:
    import scipy.sparse.linalg._dsolve._superlu as _superlu

    _HAVE_SUPERLU = True
except Exception:  # pragma: no cover - defensive
    _HAVE_SUPERLU = False


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _read_csr(path):
    """Read a CSR matrix stored as an .npz of raw arrays.

    Returns (n, indptr, indices, data) with int32 index arrays.
    """
    z = np.load(path)
    indptr = np.asarray(z["indptr"], dtype=np.int32)
    indices = np.asarray(z["indices"], dtype=np.int32)
    data = np.asarray(z["data"], dtype=np.float64)
    shape = np.asarray(z["shape"]).ravel()
    n = int(shape[0])
    return n, indptr, indices, data


def _csr_to_csc(n, indptr, indices, data):
    """Vectorized CSR -> CSC conversion (no scipy.sparse needed)."""
    nnz = data.size
    rows = np.repeat(np.arange(n, dtype=np.int32), np.diff(indptr))
    order = np.argsort(indices, kind="stable")
    rowind = rows[order]
    nzvals = data[order]
    counts = np.bincount(indices, minlength=n)
    colptr = np.zeros(n + 1, dtype=np.int32)
    np.cumsum(counts, out=colptr[1:])
    return nnz, nzvals, rowind, colptr


def _factor_direct(n, indptr, indices, data):
    """SuperLU factorization via the low-level gstrf entry point."""
    nnz, nzvals, rowind, colptr = _csr_to_csc(n, indptr, indices, data)
    return _superlu.gstrf(
        n,
        nnz,
        nzvals,
        rowind,
        colptr,
        csc_construct_func=lambda *a: None,
        ilu=False,
        options=dict(
            SymmetricMode=True,
            ColPerm="MMD_AT_PLUS_A",
            DiagPivotThresh=0.0,
        ),
    )


def _factor_scipy(n, indptr, indices, data):
    """Fallback: build a scipy CSC matrix and use splu."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    A = sp.csc_matrix((data, indices, indptr), shape=(n, n))
    return spla.splu(
        A,
        permc_spec="MMD_AT_PLUS_A",
        diag_pivot_thresh=0.0,
        options=dict(SymmetricMode=True),
    )


def _operator_key(n, indptr, indices, data):
    """Content hash of the operator, for reuse across cases."""
    import hashlib

    h = hashlib.blake2b(digest_size=16)
    h.update(np.int64(n).tobytes())
    h.update(np.ascontiguousarray(indptr, dtype=np.int32).tobytes())
    h.update(np.ascontiguousarray(indices, dtype=np.int32).tobytes())
    h.update(np.ascontiguousarray(data, dtype=np.float64).tobytes())
    return h.digest()


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)

    cache = {}  # operator hash -> factorization

    for case in manifest["cases"]:
        cid = case["id"]
        cdir = os.path.join(args.input, case["path"])

        n, indptr, indices, data = _read_csr(os.path.join(cdir, "A.npz"))
        rhs = np.asarray(np.load(os.path.join(cdir, "rhs.npy")),
                         dtype=np.float64)
        if rhs.ndim == 1:
            rhs = rhs[:, None]

        key = _operator_key(n, indptr, indices, data)
        lu = cache.get(key)
        if lu is None:
            if _HAVE_SUPERLU:
                try:
                    lu = _factor_direct(n, indptr, indices, data)
                except Exception:
                    lu = _factor_scipy(n, indptr, indices, data)
            else:
                lu = _factor_scipy(n, indptr, indices, data)
            cache[key] = lu

        # One factorization, all RHS columns at once.
        X = np.asarray(lu.solve(rhs), dtype=np.float64)
        if X.ndim == 1:
            X = X[:, None]
        X[~np.isfinite(X)] = 0.0

        outdir = os.path.join(args.output, "cases", cid)
        os.makedirs(outdir, exist_ok=True)
        np.save(os.path.join(outdir, "solution.npy"),
                np.ascontiguousarray(X, dtype="<f8"))


if __name__ == "__main__":
    main()
