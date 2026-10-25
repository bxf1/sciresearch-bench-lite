#!/usr/bin/env python3
"""Batched sparse SPD Poisson solver using one sparse LU per operator.

The public inputs are CSR matrices. For a symmetric matrix the CSR arrays are
also a valid CSC representation, so no sparse-format rewrite is needed. The
SuperLU extension is loaded directly to avoid importing the rest of SciPy at
startup; SciPy remains a fallback if the extension cannot be found.
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import sys
import sysconfig
from pathlib import Path

import numpy as np


def _load_superlu():
    """Load scipy's compiled SuperLU bindings without importing scipy.sparse."""
    roots = []
    for key in ("purelib", "platlib"):
        try:
            roots.append(sysconfig.get_paths()[key])
        except Exception:
            pass
    roots.extend(p for p in sys.path if p)
    seen = set()
    paths = []
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        paths.extend(glob.glob(os.path.join(
            root, "scipy", "sparse", "linalg", "_dsolve", "_superlu*.so")))
    if not paths:
        paths = glob.glob(
            "/usr/local/lib/python*/site-packages/scipy/sparse/linalg/_dsolve/_superlu*.so")
    for path in paths:
        try:
            spec = importlib.util.spec_from_file_location("_superlu", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:
            continue
    return None


_SUPERLU = _load_superlu()
_OPTIONS = {
    "DiagPivotThresh": 0.0,
    "ColPerm": "MMD_AT_PLUS_A",
    "SymmetricMode": True,
    "PanelSize": 2,
    "Relax": 4,
}


def _load_arrays(path):
    """Read the numeric sparse arrays without relying on scipy.sparse."""
    with np.load(path, allow_pickle=False) as archive:
        names = set(archive.files)
        data = np.asarray(archive["data"])
        indices = np.asarray(archive["indices"])
        indptr = np.asarray(archive["indptr"])
        fmt = archive["format"].item() if "format" in names else b"csr"
        if isinstance(fmt, bytes):
            fmt = fmt.decode("ascii", "strict").lower()
        else:
            fmt = str(fmt).lower()
        if "shape" in names:
            shape = tuple(int(x) for x in np.asarray(archive["shape"]).ravel())
        else:
            shape = (len(indptr) - 1, len(indptr) - 1)

    if data.dtype != np.float64:
        data = data.astype(np.float64, copy=False)
    if indices.dtype != np.int32:
        indices = indices.astype(np.int32, copy=False)
    if indptr.dtype != np.int32:
        indptr = indptr.astype(np.int32, copy=False)
    data = np.ascontiguousarray(data)
    indices = np.ascontiguousarray(indices)
    indptr = np.ascontiguousarray(indptr)
    return fmt, shape, data, indices, indptr


def _matvec(data, indices, indptr, answer):
    products = data[:, None] * answer[indices, :]
    return np.add.reduceat(products, indptr[:-1], axis=0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    manifest = json.loads((args.input / "manifest.json").read_text())
    cache = {}
    cache_fill = 0
    max_cache_fill = 20_000_000

    for case in manifest["cases"]:
        source = args.input / case["path"]
        fmt, shape, data, indices, indptr = _load_arrays(source / "A.npz")
        rhs = np.asarray(np.load(source / "rhs.npy", allow_pickle=False),
                         dtype=np.float64)

        key = None
        lu = None
        if fmt in ("csr", "csc"):
            key = (shape[0], shape[1], data.size,
                   hash(data.tobytes()), hash(indices.tobytes()),
                   hash(indptr.tobytes()))
            lu = cache.get(key)
        if lu is None:
            if _SUPERLU is not None and fmt in ("csr", "csc"):
                lu = _SUPERLU.gstrf(
                    int(shape[0]), data.size, data, indices, indptr,
                    csc_construct_func=lambda *a, **k: None,
                    ilu=False, options=dict(_OPTIONS))
            else:
                from scipy.sparse import csc_matrix, load_npz
                from scipy.sparse.linalg import splu
                if fmt in ("csr", "csc"):
                    matrix = csc_matrix((data, indices, indptr), shape=shape)
                else:
                    matrix = load_npz(source / "A.npz").tocsc()
                lu = splu(matrix, permc_spec="MMD_AT_PLUS_A",
                          diag_pivot_thresh=0.0,
                          options={"SymmetricMode": True})
            if key is not None:
                fill = getattr(lu, "nnz", 0)
                if cache_fill + fill <= max_cache_fill:
                    cache[key] = lu
                    cache_fill += fill

        answer = np.asarray(lu.solve(rhs), dtype="<f8")
        residual = _matvec(data, indices, indptr, answer) - rhs
        rel = np.linalg.norm(residual, axis=0) / np.maximum(
            np.linalg.norm(rhs, axis=0), 1e-12)
        if not np.isfinite(rel).all() or rel.max() > 1e-8:
            raise FloatingPointError(f"relative residual check failed: {rel}")

        destination = args.output / "cases" / case["id"]
        destination.mkdir(parents=True, exist_ok=True)
        np.save(destination / "solution.npy", answer, allow_pickle=False)


if __name__ == "__main__":
    main()
