#!/usr/bin/env python3
"""Fast batch solver for the SPD Poisson benchmark.

The operators are two-dimensional five(point) stencils.  A banded Cholesky
factorization (natural ordering) is both fast and memory efficient for the
grid sizes where it wins; larger systems use SuperLU's symmetric mode.  The
factorization is cached when several cases share an operator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

# Imported lazily only after a case has actually been read, keeping startup
# small for batches that can use the banded path.


def _read_sparse(path: Path):
    """Read a scipy CSR/CSC NPZ without importing scipy.sparse."""
    with np.load(path, allow_pickle=False) as z:
        files = set(z.files)
        fmt = z["format"].item()
        if isinstance(fmt, bytes):
            fmt = fmt.decode("ascii")
        data = np.asarray(z["data"])
        indices = np.asarray(z["indices"])
        indptr = np.asarray(z["indptr"])
        shape = tuple(int(x) for x in z["shape"])
    if fmt not in ("csr", "csc"):
        raise ValueError("unsupported sparse format")
    if data.dtype != np.float64 or indices.dtype.kind not in "iu" or indptr.dtype.kind not in "iu":
        raise ValueError("unsupported sparse dtypes")
    if fmt == "csr":
        return data, indices.astype(np.int64, copy=False), indptr.astype(np.int64, copy=False), shape, fmt
    # A CSC matrix with a symmetric pattern is just the transpose of an equal
    # CSR matrix; convert cheaply below when necessary.
    return data, indices.astype(np.int64, copy=False), indptr.astype(np.int64, copy=False), shape, fmt


def _csr_to_band(data, indices, indptr, n, bandwidth):
    N = n * n
    rows = np.repeat(np.arange(N, dtype=np.int64), np.diff(indptr))
    mask = (indices <= rows) & ((rows - indices) <= bandwidth)
    k = rows[mask] - indices[mask]
    j = indices[mask]
    ab = np.zeros((bandwidth + 1, N), dtype=np.float64, order="F")
    ab[k, j] = data[mask]
    # The diagonal must be explicit and positive for Cholesky.
    if not np.all(ab[0] > 0.0):
        raise ValueError("matrix has a nonpositive diagonal")
    return ab


def _digest(data, indices, indptr, shape):
    h = hashlib.blake2b(digest_size=16)
    h.update(np.asarray(shape, dtype=np.int64).tobytes())
    h.update(data.tobytes())
    h.update(indices.tobytes())
    h.update(indptr.tobytes())
    return h.digest()


class Solver:
    def __init__(self):
        self.cache = {}
        self.cache_bytes = 0
        self.max_cache_bytes = 768 * 1024 * 1024

    def _store(self, key, value, size):
        if size <= self.max_cache_bytes:
            # Simple LRU: dict insertion order is enough here.
            self.cache[key] = (value, size)
            self.cache_bytes += size
            while self.cache_bytes > self.max_cache_bytes and len(self.cache) > 1:
                _, (_, old_size) = next(iter(self.cache.items()))
                old_key = next(iter(self.cache))
                del self.cache[old_key]
                self.cache_bytes -= old_size

    def solve(self, path: Path, n: int, rhs: np.ndarray) -> np.ndarray:
        data, indices, indptr, shape, fmt = _read_sparse(path)
        if shape != (n * n, n * n):
            raise ValueError("matrix shape does not match metadata")
        key = _digest(data, indices, indptr, shape)
        hit = self.cache.get(key)
        if hit is not None:
            method, obj, bandwidth = hit[0]
            if method == "band":
                from scipy.linalg import cho_solve_banded
                return cho_solve_banded((obj, True), rhs, check_finite=False, overwrite_b=False)
            return obj.solve(rhs)

        N = n * n
        bandwidth = int(np.max(indices - np.repeat(np.arange(N), np.diff(indptr)), initial=0))
        # Also account for entries in the other triangle.
        lower_bw = 0
        rows = np.repeat(np.arange(N, dtype=np.int64), np.diff(indptr))
        lower = indices <= rows
        if np.any(lower):
            lower_bw = int(np.max(rows[lower] - indices[lower]))
        bandwidth = max(lower_bw, int(np.max(indices - rows, initial=0)))

        # Banded Cholesky is fastest for the small/medium grids.  For larger
        # grids SuperLU has substantially lower fill and memory.
        if fmt == "csr" and n <= 192 and bandwidth <= 4 * n:
            try:
                from scipy.linalg import cholesky_banded
                ab = _csr_to_band(data, indices, indptr, n, bandwidth)
                c = cholesky_banded(ab, lower=True, overwrite_ab=True, check_finite=False)
                self._store(key, ("band", c, bandwidth), c.nbytes)
                from scipy.linalg import cho_solve_banded
                return cho_solve_banded((c, True), rhs, check_finite=False, overwrite_b=False)
            except Exception:
                # Fall through to the general sparse path.
                pass

        from scipy.sparse import csc_matrix
        from scipy.sparse.linalg import splu
        if fmt == "csc":
            A = csc_matrix((data, indices, indptr), shape=shape)
        else:
            # SuperLU wants CSC; conversion is cheap compared with factoring.
            A = csc_matrix((data, indices, indptr), shape=shape)
        lu = splu(A, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                  options={"SymmetricMode": True})
        self._store(key, ("lu", lu, bandwidth), (lu.L.nnz + lu.U.nnz) * 12 + N * 16)
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
    cases = manifest["cases"]
    solver = Solver()

    for case in cases:
        cid = case["id"]
        source = input_root / case["path"]
        metadata = json.loads((source / "metadata.json").read_text())
        n = int(metadata["n"])
        rhs = np.load(source / "rhs.npy", allow_pickle=False)
        if rhs.dtype.str != "<f8" or rhs.shape != (n * n, 4):
            raise ValueError("unexpected rhs shape or dtype")
        answer = solver.solve(source / "A.npz", n, np.asarray(rhs, dtype="<f8"))
        # A final residual-safe touch: Cholesky/SuperLU are already accurate,
        # but validation rejects a non-finite artifact cheaply.
        if not np.isfinite(answer).all():
            raise FloatingPointError("nonfinite solution")
        destination = output_root / "cases" / cid
        destination.mkdir(parents=True, exist_ok=True)
        np.save(destination / "solution.npy", np.asarray(answer, dtype="<f8"), allow_pickle=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
