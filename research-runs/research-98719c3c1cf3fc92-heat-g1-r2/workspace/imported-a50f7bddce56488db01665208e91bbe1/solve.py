#!/usr/bin/env python3
"""Recover first 32 sine coefficients for 1-D heat inverse problems.

Fixed second-derivative Tikhonov baseline from the public method note.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.linalg import svd


def solve_case(case_dir: Path, out_path: Path) -> None:
    metadata = json.loads((case_dir / "metadata.json").read_text())
    obs = np.loadtxt(case_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    x, t, y = obs[:, 0], obs[:, 1], obs[:, 2]
    kappa = float(metadata["kappa"])
    sigma = float(metadata["sigma"])
    sigma = max(sigma, 1e-12)

    k = np.arange(1, 33, dtype=np.float64)
    damping = np.exp(-kappa * np.pi**2 * t[:, None] * k[None, :] ** 2)
    A = np.sin(np.pi * x[:, None] * k[None, :]) * damping
    D = k**2

    # A D^{-1} = U diag(s) V^T
    U, s, Vt = svd(A / D, full_matrices=False)
    alpha = 1.0e-5
    lam = alpha * s[0] ** 2
    rhs = U.T @ y
    z = Vt.T @ (s / (s * s + lam) * rhs)
    coeff = z / D

    target = np.load(case_dir / "target_grid.npy").astype(np.float64, copy=False)
    # The evaluator's grid is exactly j/257; evaluating the continuous sine
    # series at the supplied target coordinates is equivalent.
    u0 = np.sin(np.pi * target[:, None] * k[None, :]) @ coeff
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, np.asarray(u0, dtype="<f8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    manifest = json.loads((input_dir / "manifest.json").read_text())
    for case in manifest["cases"]:
        case_id = str(case["id"])
        case_dir = input_dir / case["path"]
        solve_case(case_dir, output_dir / "cases" / case_id / "u0.npy")


if __name__ == "__main__":
    main()
