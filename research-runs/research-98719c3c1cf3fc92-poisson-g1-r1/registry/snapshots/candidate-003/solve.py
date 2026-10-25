#!/usr/bin/env python3
"""Batched sparse SPD Poisson solver using one sparse LU per operator.

The public inputs are CSR matrices. For a symmetric matrix the CSR arrays are
also a valid CSC representation, so no sparse-format rewrite is needed. The
compiled SuperLU bindings are loaded directly to avoid importing the rest of
SciPy at startup; SciPy remains a fallback for unusual sparse containers.
"""
import importlib.util
import json
import os
import sys

import numpy as np


def _load_superlu():
    """Load scipy's compiled SuperLU bindings without importing scipy.sparse."""
    directories = []
    try:
        site_packages = os.path.dirname(os.path.dirname(np.__file__))
        directories.append(os.path.join(
            site_packages, "scipy", "sparse", "linalg", "_dsolve"))
    except Exception:
        pass
    for root in sys.path:
        if root:
            directories.append(os.path.join(
                root, "scipy", "sparse", "linalg", "_dsolve"))
    seen = set()
    for directory in directories:
        if directory in seen:
            continue
        seen.add(directory)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if name.startswith("_superlu") and name.endswith((".so", ".pyd")):
                path = os.path.join(directory, name)
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
    """Read numeric sparse arrays without relying on scipy.sparse."""
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
    return (fmt, shape, np.ascontiguousarray(data),
            np.ascontiguousarray(indices), np.ascontiguousarray(indptr))


def _factorize(n, data, indices, indptr):
    if _SUPERLU is not None:
        return _SUPERLU.gstrf(
            n, data.size, data, indices, indptr,
            csc_construct_func=lambda *a, **k: None,
            ilu=False, options=dict(_OPTIONS))
    from scipy.sparse import csc_matrix
    from scipy.sparse.linalg import splu
    matrix = csc_matrix((data, indices, indptr), shape=(n, n))
    return splu(matrix, permc_spec="MMD_AT_PLUS_A",
                diag_pivot_thresh=0.0, options={"SymmetricMode": True})


def _solve(source, destination, cache):
    fmt, shape, data, indices, indptr = _load_arrays(
        os.path.join(source, "A.npz"))
    rhs = np.asarray(np.load(os.path.join(source, "rhs.npy"),
                             allow_pickle=False), dtype=np.float64)
    n = int(shape[0])

    if fmt in ("csr", "csc"):
        # A is symmetric, so CSR arrays are also its CSC representation.
        key = (n, data.size, hash(data.tobytes()), hash(indices.tobytes()),
               hash(indptr.tobytes()))
        lu = cache.get(key)
        if lu is None:
            lu = _factorize(n, data, indices, indptr)
            fill = getattr(lu, "nnz", 0)
            if fill <= 20_000_000 and sum(
                    getattr(old, "nnz", 0) for old in cache.values()) + fill <= 20_000_000:
                cache[key] = lu
        answer = np.asarray(lu.solve(rhs), dtype="<f8")
        products = data[:, None] * answer[indices, :]
        residual = np.add.reduceat(products, indptr[:-1], axis=0) - rhs
        rel = np.linalg.norm(residual, axis=0) / np.maximum(
            np.linalg.norm(rhs, axis=0), 1e-12)
        if not np.isfinite(rel).all() or rel.max() > 1e-8:
            raise FloatingPointError(f"relative residual check failed: {rel}")
    else:
        # Rare non-CSR/CSC container: let scipy perform the canonical conversion.
        from scipy.sparse import load_npz
        matrix = load_npz(os.path.join(source, "A.npz")).tocsc()
        from scipy.sparse.linalg import splu
        lu = splu(matrix, permc_spec="MMD_AT_PLUS_A",
                  diag_pivot_thresh=0.0, options={"SymmetricMode": True})
        answer = np.asarray(lu.solve(rhs), dtype="<f8")

    os.makedirs(destination, exist_ok=True)
    np.save(os.path.join(destination, "solution.npy"), answer,
            allow_pickle=False)


def main():
    args = sys.argv[1:]
    def option(name, default=None):
        try:
            return args[args.index(name) + 1]
        except (ValueError, IndexError):
            return default

    input_root = option("--input")
    output_root = option("--output")
    if not input_root or not output_root:
        print("usage: solve.py --input DIR --output DIR [--seed N]",
              file=sys.stderr)
        return 2
    with open(os.path.join(input_root, "manifest.json"), "r") as stream:
        manifest = json.load(stream)
    cache = {}
    for case in manifest["cases"]:
        _solve(os.path.join(input_root, case["path"]),
               os.path.join(output_root, "cases", case["id"]), cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
