"""Standalone T3 baseline submission; public inputs only, no self timing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.sparse import diags, load_npz
from scipy.sparse.linalg import cg, splu


def solve(matrix, rhs, method):
    if method == "lu":
        return splu(matrix.tocsc(), permc_spec="COLAMD").solve(rhs)
    preconditioner = diags(1.0 / matrix.diagonal()) if method == "jacobi" else None
    columns = []
    for column in rhs.T:
        answer, info = cg(matrix, column, M=preconditioner, rtol=1e-10, atol=0.0, maxiter=10000)
        if info != 0:
            raise RuntimeError(f"CG did not converge (info={info})")
        columns.append(answer)
    return np.column_stack(columns)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--method", choices=("cg", "jacobi", "lu"), default="lu")
    args = parser.parse_args()
    manifest = json.loads((args.input / "manifest.json").read_text())
    for case in manifest["cases"]:
        directory = args.input / case["path"]
        matrix = load_npz(directory / "A.npz")
        rhs = np.load(directory / "rhs.npy", allow_pickle=False)
        solution = solve(matrix, rhs, args.method)
        if not np.isfinite(solution).all():
            raise FloatingPointError("Solver returned nonfinite values")
        destination = args.output / "cases" / case["id"]
        destination.mkdir(parents=True, exist_ok=True)
        np.save(destination / "solution.npy", np.asarray(solution, dtype="<f8"), allow_pickle=False)


if __name__ == "__main__":
    main()
