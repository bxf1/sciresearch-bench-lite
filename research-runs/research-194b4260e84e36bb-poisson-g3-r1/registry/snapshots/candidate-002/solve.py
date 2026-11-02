#!/usr/bin/env python3
"""Fast batch solver for the SPD Poisson benchmark.

The matrices are two-dimensional five-point (or otherwise narrow-banded)
stencils in natural row-major ordering.  Their Cholesky factor fits in a
small band, so a banded LAPACK factorization is both faster and much leaner
than a general black-box iterative solve.  LAPACK is reached through ctypes
to avoid paying scipy's import cost for the common case.  A SuperLU fallback
handles unexpectedly large or non-banded systems.
"""
from __future__ import annotations

import argparse
import ctypes
import glob
import hashlib
import json
import os
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Sparse input without importing scipy.sparse
# ---------------------------------------------------------------------------

def _read_sparse(path: Path):
    with np.load(path, allow_pickle=False) as z:
        fmt = z["format"].item()
        if isinstance(fmt, bytes):
            fmt = fmt.decode("ascii")
        data = np.asarray(z["data"], dtype=np.float64)
        indices = np.asarray(z["indices"], dtype=np.int64)
        indptr = np.asarray(z["indptr"], dtype=np.int64)
        shape = tuple(int(x) for x in z["shape"])
    if fmt not in ("csr", "csc"):
        raise ValueError("unsupported sparse format")
    # For a symmetric matrix, the CSC arrays are exactly the CSR arrays of
    # the transpose, hence of the matrix itself.
    return data, indices, indptr, shape, fmt


def _digest(data, indices, indptr, shape):
    h = hashlib.blake2b(digest_size=16)
    h.update(np.asarray(shape, dtype=np.int64).tobytes())
    h.update(memoryview(data))
    h.update(memoryview(indices))
    h.update(memoryview(indptr))
    return h.digest()


def _band_from_csr(data, indices, indptr, n, bandwidth):
    N = n * n
    rows = np.repeat(np.arange(N, dtype=np.int64), np.diff(indptr))
    lower = indices <= rows
    if not np.any(lower):
        raise ValueError("no lower triangle in sparse matrix")
    k = rows[lower] - indices[lower]
    j = indices[lower]
    ab = np.zeros((bandwidth + 1, N), dtype=np.float64, order="F")
    ab[k, j] = data[lower]
    if not np.all(ab[0] > 0.0):
        raise ValueError("nonpositive diagonal")
    return ab


# ---------------------------------------------------------------------------
# Minimal, lazy ctypes binding to LAPACK's banded Cholesky
# ---------------------------------------------------------------------------

def _load_banded_lapack():
    """Find OpenBLAS/LAPACKE symbols without importing scipy."""
    candidates = []
    try:
        site = Path(np.__file__).resolve().parent.parent
    except Exception:
        site = None
    if site is not None:
        candidates.extend(sorted(glob.glob(str(site / "scipy.libs" / "libscipy_openblas*.so"))))
        candidates.extend(sorted(glob.glob(str(site / "numpy.libs" / "libscipy_openblas*.so"))))
    for filename in candidates:
        try:
            lib = ctypes.CDLL(filename)
        except OSError:
            continue
        # Standard 32-bit LAPACK integer interface.
        try:
            trf = lib.scipy_LAPACKE_dpbtrf
            trs = lib.scipy_LAPACKE_dpbtrs
            trf.argtypes = [ctypes.c_int, ctypes.c_char, ctypes.c_int,
                            ctypes.c_int, ctypes.POINTER(ctypes.c_double),
                            ctypes.c_int]
            trf.restype = ctypes.c_int
            trs.argtypes = [ctypes.c_int, ctypes.c_char, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int,
                            ctypes.POINTER(ctypes.c_double), ctypes.c_int,
                            ctypes.POINTER(ctypes.c_double), ctypes.c_int]
            trs.restype = ctypes.c_int
            return trf, trs, ctypes.c_int
        except AttributeError:
            pass
        # Numpy's 64-bit-integer OpenBLAS build uses different names.
        try:
            trf = lib.scipy_LAPACKE_dpbtrf64_
            trs = lib.scipy_LAPACKE_dpbtrs64_
            trf.argtypes = [ctypes.c_int, ctypes.c_char, ctypes.c_int64,
                            ctypes.c_int64, ctypes.POINTER(ctypes.c_double),
                            ctypes.c_int64]
            trf.restype = ctypes.c_int
            trs.argtypes = [ctypes.c_int, ctypes.c_char, ctypes.c_int64,
                            ctypes.c_int64, ctypes.c_int64,
                            ctypes.POINTER(ctypes.c_double), ctypes.c_int64,
                            ctypes.POINTER(ctypes.c_double), ctypes.c_int64]
            trs.restype = ctypes.c_int
            return trf, trs, ctypes.c_int64
        except AttributeError:
            pass
    return None


_LAPACKE = None
_LAPACKE_TRIED = False


def _lapacke():
    global _LAPACKE, _LAPACKE_TRIED
    if not _LAPACKE_TRIED:
        _LAPACKE = _load_banded_lapack()
        _LAPACKE_TRIED = True
    return _LAPACKE


# ---------------------------------------------------------------------------
# Solver with operator cache
# ---------------------------------------------------------------------------

class Solver:
    def __init__(self):
        self.cache = {}
        self.cache_bytes = 0
        self.max_cache_bytes = 640 * 1024 * 1024

    def _get(self, key):
        return self.cache.get(key)

    def _put(self, key, value, size):
        if size > self.max_cache_bytes:
            return
        self.cache[key] = (value, size)
        self.cache_bytes += size
        while self.cache_bytes > self.max_cache_bytes and len(self.cache) > 1:
            old_key = next(iter(self.cache))
            _, old_size = self.cache.pop(old_key)
            self.cache_bytes -= old_size

    def solve(self, path: Path, n: int, rhs: np.ndarray) -> np.ndarray:
        data, indices, indptr, shape, fmt = _read_sparse(path)
        N = n * n
        if shape != (N, N):
            raise ValueError("matrix shape mismatch")
        key = _digest(data, indices, indptr, shape)
        cached = self._get(key)
        if cached is not None:
            kind, obj, bw = cached[0]
            if kind == "band":
                return self._band_solve(obj, bw, n, rhs)
            return obj.solve(rhs)

        rows = np.repeat(np.arange(N, dtype=np.int64), np.diff(indptr))
        lower = indices <= rows
        if not np.any(lower):
            return self._lu_solve(key, data, indices, indptr, shape, rhs)
        bandwidth = int(np.max(rows[lower] - indices[lower]))

        # The narrow-band path is very fast up to a few hundred grid points.
        if n <= 256 and bandwidth <= 4 * n:
            lap = _lapacke()
            if lap is not None:
                try:
                    ab = _band_from_csr(data, indices, indptr, n, bandwidth)
                    trf, trs, int_t = lap
                    info = trf(102, b"L", int_t(N), int_t(bandwidth),
                               ab.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                               int_t(bandwidth + 1))
                    if info == 0:
                        self._put(key, ("band", ab, bandwidth), ab.nbytes)
                        return self._band_solve(ab, bandwidth, n, rhs)
                except Exception:
                    pass

        # General sparse fallback.  This import happens only for large or
        # unexpected systems, so it does not penalize ordinary batches.
        from scipy.sparse import csc_matrix
        from scipy.sparse.linalg import splu
        A = csc_matrix((data, indices, indptr), shape=shape)
        lu = splu(A, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                  options={"SymmetricMode": True})
        self._put(key, ("lu", lu, bandwidth), (lu.L.nnz + lu.U.nnz) * 16 + N * 16)
        return lu.solve(rhs)

    def _band_solve(self, ab, bandwidth, n, rhs):
        trf, trs, int_t = _lapacke()
        N = n * n
        b = np.array(rhs, dtype=np.float64, order="F", copy=True)
        info = trs(102, b"L", int_t(N), int_t(bandwidth), int_t(4),
                   ab.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                   int_t(bandwidth + 1),
                   b.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                   int_t(N))
        if info != 0:
            raise np.linalg.LinAlgError("banded triangular solve failed")
        return b

    def _lu_solve(self, key, data, indices, indptr, shape, rhs):
        from scipy.sparse import csc_matrix
        from scipy.sparse.linalg import splu
        A = csc_matrix((data, indices, indptr), shape=shape)
        lu = splu(A, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                  options={"SymmetricMode": True})
        self._put(key, ("lu", lu, 0), (lu.L.nnz + lu.U.nnz) * 16 + shape[0] * 16)
        return lu.solve(rhs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    input_root = Path(args.input)
    output_root = Path(args.output)
    manifest = json.loads((input_root / "manifest.json").read_text())
    solver = Solver()

    for case in manifest["cases"]:
        cid = case["id"]
        source = input_root / case["path"]
        metadata = json.loads((source / "metadata.json").read_text())
        n = int(metadata["n"])
        rhs = np.load(source / "rhs.npy", allow_pickle=False)
        if rhs.dtype.str != "<f8" or rhs.shape != (n * n, 4):
            raise ValueError("unexpected rhs shape or dtype")
        answer = solver.solve(source / "A.npz", n, rhs)
        if not np.isfinite(answer).all():
            raise FloatingPointError("nonfinite solution")
        destination = output_root / "cases" / cid
        destination.mkdir(parents=True, exist_ok=True)
        np.save(destination / "solution.npy", np.ascontiguousarray(answer, dtype="<f8"),
                allow_pickle=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
