#!/usr/bin/env python3
"""Public T3 Jacobi-CG comparator, available identically to every guidance group.

Only public A and RHS are used. The CLI writes standard numeric submissions and
prints public residual diagnostics. Its in-process elapsed time is diagnostic;
formal complete-process timing, limits and B,C,C,B,B,C ordering belong to W.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

import numpy as np
from scipy.sparse import diags, issparse, load_npz
from scipy.sparse.linalg import cg

CG_SETTINGS = {"rtol": 1e-10, "atol": 0.0, "maxiter": 10000}


def solve(matrix, rhs):
    """Apply fixed Jacobi-preconditioned CG separately to the four public RHS."""
    rhs = np.asarray(rhs)
    if not issparse(matrix) or matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("A must be a square sparse matrix")
    if rhs.shape != (matrix.shape[0], 4):
        raise ValueError("rhs must have shape (A.shape[0], 4)")
    if np.iscomplexobj(matrix.data) or np.iscomplexobj(rhs) or not np.isfinite(matrix.data).all() or not np.isfinite(rhs).all():
        raise ValueError("A and rhs must contain finite real values")
    diagonal = matrix.diagonal()
    if not np.all(diagonal > 0):
        raise ValueError("Jacobi-CG requires a positive finite diagonal for these SPD inputs")
    preconditioner = diags(1.0 / diagonal)
    columns = []
    for column in rhs.T:
        answer, info = cg(matrix, column, M=preconditioner, **CG_SETTINGS)
        if info != 0:
            raise RuntimeError(f"Jacobi-CG did not converge (info={info})")
        if not np.isfinite(answer).all():
            raise FloatingPointError("Jacobi-CG returned nonfinite values")
        columns.append(answer)
    return np.asarray(np.column_stack(columns), dtype="<f8")


def solve_batch(input_root, output_root):
    """Return residual-only diagnostics; never estimate hidden solution error."""
    started = time.perf_counter()
    input_root, output_root = Path(input_root), Path(output_root)
    manifest = json.loads((input_root / "manifest.json").read_text())
    if manifest.get("task") != "poisson" or not isinstance(manifest.get("cases"), list) or not manifest["cases"]:
        raise ValueError("expected a nonempty public poisson manifest")
    seen = set()
    for case in manifest["cases"]:
        case_id = case.get("id")
        if not isinstance(case_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", case_id) is None:
            raise ValueError("unsafe case ID")
        if case_id in seen or case.get("path") != f"cases/{case_id}":
            raise ValueError("duplicate case or unsafe case path")
        seen.add(case_id)
    rows = []
    for case in manifest["cases"]:
        source = input_root / case["path"]
        matrix = load_npz(source / "A.npz")
        rhs = np.load(source / "rhs.npy", allow_pickle=False)
        answer = solve(matrix, rhs)
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            residual = matrix @ answer - rhs
            errors = [float(np.linalg.norm(residual[:, j]) / max(np.linalg.norm(rhs[:, j]), 1e-12))
                      for j in range(4)]
        if not np.isfinite(errors).all():
            raise FloatingPointError("residual diagnostic is nonfinite")
        destination = output_root / "cases" / case["id"]
        destination.mkdir(parents=True, exist_ok=True)
        np.save(destination / "solution.npy", answer, allow_pickle=False)
        rows.append({"id": case["id"], "E_res": errors, "residual_pass": max(errors) <= 1e-8})
    return {"method": "jacobi_cg", "settings": dict(CG_SETTINGS), "cases": rows,
            "timing_status": "diagnostic_in_process_only", "formal": False,
            "io_solve_check_save_seconds": time.perf_counter() - started,
            "timing_excludes": ["Python startup", "module imports", "container setup", "trusted scoring"],
            "timing_note": "Use trusted W complete-process timing for comparison; this measurement cannot set a formal speedup or reward."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0, help="The deterministic comparator uses no randomness; protocol seed is 0.")
    args = parser.parse_args()
    if args.seed != 0:
        parser.error("the frozen comparator contract requires --seed 0")
    print(json.dumps(solve_batch(args.input, args.output), sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
