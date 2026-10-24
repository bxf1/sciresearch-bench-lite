#!/usr/bin/env python3
"""Sparse direct solver for the poisson task.

Reads /input/manifest.json, solves each case with a sparse LU factorization
(COLAMD ordering) reused across all RHS columns, and writes
/output/cases/<id>/solution.npy.
"""
import argparse
import json
import os
import sys

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


def solve_case(case_dir, out_dir):
    A = sp.load_npz(os.path.join(case_dir, "A.npz")).tocsc()
    rhs = np.load(os.path.join(case_dir, "rhs.npy"))
    rhs = np.ascontiguousarray(rhs, dtype="<f8")
    if rhs.ndim == 1:
        rhs = rhs[:, None]

    lu = spla.splu(A, permc_spec="COLAMD", diag_pivot_thresh=0.0,
                   options=dict(SymmetricMode=True))
    x = lu.solve(rhs)

    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, "solution.npy"),
            np.ascontiguousarray(x, dtype="<f8"))
    return A, rhs, x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--output", default="/output")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)

    for case in manifest["cases"]:
        cid = case["id"]
        case_dir = os.path.join(args.input, case["path"])
        out_dir = os.path.join(args.output, "cases", cid)
        A, rhs, x = solve_case(case_dir, out_dir)
        res = A @ x - rhs
        rel = np.linalg.norm(res, axis=0) / np.linalg.norm(rhs, axis=0)
        print(f"{cid}: rel_res={rel.max():.3e}", file=sys.stderr)


if __name__ == "__main__":
    main()
