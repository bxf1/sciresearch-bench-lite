#!/usr/bin/env python3
"""Batch solver for the symmetric positive-definite Poisson cases.

All four right-hand sides of a case share one operator.  A sparse LU
factorization is formed once and applied to the whole block of right-hand
sides.  Cases whose operator file is identical also share the factorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.sparse import diags, load_npz
from scipy.sparse.linalg import cg, splu


def file_digest(path: Path) -> bytes:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.digest()


def fallback_cg(matrix, rhs):
    """Memory-safe fallback; normally the sparse factorization is used."""
    diagonal = matrix.diagonal()
    precond = diags(1.0 / diagonal)
    result = np.empty_like(rhs)
    for column in range(rhs.shape[1]):
        answer, info = cg(matrix, rhs[:, column], M=precond, rtol=1e-11,
                          atol=0.0, maxiter=20000)
        if info != 0:
            raise RuntimeError("fallback CG did not converge")
        result[:, column] = answer
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    input_root = args.input
    output_root = args.output
    manifest = json.loads((input_root / "manifest.json").read_text())

    # Group byte-identical operator files so a repeated fixed operator is
    # factorized only once.  Groups are processed one at a time to bound peak
    # memory even if many large, distinct operators occur in one batch.
    groups: dict[bytes, list[dict]] = {}
    for case in manifest["cases"]:
        source = input_root / case["path"]
        key = file_digest(source / "A.npz")
        groups.setdefault(key, []).append(case)

    for entries in groups.values():
        first_source = input_root / entries[0]["path"]
        matrix = load_npz(first_source / "A.npz")
        blocks = []
        for case in entries:
            source = input_root / case["path"]
            rhs = np.load(source / "rhs.npy", allow_pickle=False)
            blocks.append(np.asarray(rhs, dtype=np.float64, order="C"))
        rhs_all = np.concatenate(blocks, axis=1)

        try:
            factor = splu(matrix.tocsc(), permc_spec="MMD_AT_PLUS_A",
                          diag_pivot_thresh=0.0,
                          options={"SymmetricMode": True})
            solution_all = factor.solve(rhs_all)
            if not np.isfinite(solution_all).all():
                raise FloatingPointError("nonfinite direct solution")
        except (MemoryError, RuntimeError, FloatingPointError):
            solution_all = fallback_cg(matrix, rhs_all)

        offset = 0
        for case, block in zip(entries, blocks):
            width = block.shape[1]
            solution = np.asarray(solution_all[:, offset:offset + width],
                                  dtype="<f8", order="C")
            destination = output_root / "cases" / case["id"]
            destination.mkdir(parents=True, exist_ok=True)
            np.save(destination / "solution.npy", solution, allow_pickle=False)
            offset += width


if __name__ == "__main__":
    main()
