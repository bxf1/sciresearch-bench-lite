#!/usr/bin/env python3
"""Sparse direct solver for the poisson task.

Each case is a sparse SPD system with 4 right-hand sides.  A single sparse LU
factorization (minimum-degree ordering, symmetric mode) is computed per operator and
reused for all four columns, which is far cheaper than an iterative solve.

Writes /output/cases/<id>/solution.npy as little-endian float64.
"""
import argparse
import json
import os

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


def solve_case(case_dir, out_dir):
    A = sp.load_npz(os.path.join(case_dir, "A.npz"))
    rhs = np.load(os.path.join(case_dir, "rhs.npy"))
    rhs = np.ascontiguousarray(rhs, dtype="<f8")
    if rhs.ndim == 1:
        rhs = rhs[:, None]

    # splu wants CSC; symmetric mode + no pivoting keeps the fill-in low for
    # these SPD operators and avoids numerical pivoting overhead.
    lu = spla.splu(A.tocsc(), permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                   options=dict(SymmetricMode=True))
    x = lu.solve(rhs)

    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, "solution.npy"),
            np.ascontiguousarray(x, dtype="<f8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--output", default="/output")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)

    for case in manifest["cases"]:
        solve_case(os.path.join(args.input, case["path"]),
                   os.path.join(args.output, "cases", case["id"]))


if __name__ == "__main__":
    main()
