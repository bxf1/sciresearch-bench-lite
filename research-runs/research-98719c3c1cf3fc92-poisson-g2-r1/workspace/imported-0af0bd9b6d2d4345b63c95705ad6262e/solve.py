#!/usr/bin/env python3
"""Batch solver for the symmetric positive-definite Poisson cases.

The right-hand sides of a case share one operator, so one sparse LU
factorization is reused for all four columns.  Cases that reuse the same
operator also reuse the factorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.sparse import load_npz
from scipy.sparse.linalg import splu


def file_digest(path: Path) -> bytes:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.digest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    input_root = args.input
    output_root = args.output
    manifest = json.loads((input_root / "manifest.json").read_text())
    cases = manifest["cases"]

    # Group cases whose operator file is byte-for-byte identical.  Easy cases
    # commonly share one fixed operator; retaining only the current group's
    # factorization keeps peak memory bounded.
    groups: dict[bytes, list[dict]] = {}
    for case in cases:
        source = input_root / case["path"]
        key = file_digest(source / "A.npz")
        groups.setdefault(key, []).append(case)

    for entries in groups.values():
        first_source = input_root / entries[0]["path"]
        matrix = load_npz(first_source / "A.npz").tocsc()
        # MMD on A^T+A reduces fill substantially for these 2-D operators.
        factor = splu(matrix, permc_spec="MMD_AT_PLUS_A",
                      diag_pivot_thresh=0.0,
                      options={"SymmetricMode": True})
        for case in entries:
            source = input_root / case["path"]
            rhs = np.load(source / "rhs.npy", allow_pickle=False)
            rhs = np.asarray(rhs, dtype=np.float64, order="C")
            solution = factor.solve(rhs)
            solution = np.asarray(solution, dtype="<f8", order="C")
            destination = output_root / "cases" / case["id"]
            destination.mkdir(parents=True, exist_ok=True)
            np.save(destination / "solution.npy", solution, allow_pickle=False)
        del factor, matrix


if __name__ == "__main__":
    main()
