#!/usr/bin/env python3
"""Empirical-Bayes recovery of the first 32 sine modes for 1-D heat inversion.

Model: y = A c + noise(sigma), c_k ~ N(0, tau^2 / k^4).  The second-derivative
smoothness prior matches the public method note.  Its scale tau is selected for
each case by the Gaussian marginal likelihood (evidence), using only the public
observations and the known noise level.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.linalg import svd


TAU_GRID = np.geomspace(0.2, 8.0, 160)


def solve_case(case_dir: Path, out_path: Path) -> None:
    metadata = json.loads((case_dir / "metadata.json").read_text())
    obs = np.loadtxt(case_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    x, t, y = obs[:, 0], obs[:, 1], obs[:, 2]
    kappa = float(metadata["kappa"])
    sigma = max(float(metadata["sigma"]), 1e-12)

    k = np.arange(1, 33, dtype=np.float64)
    D = k**2
    damping = np.exp(-kappa * np.pi**2 * t[:, None] * k[None, :] ** 2)
    A = np.sin(np.pi * x[:, None] * k[None, :]) * damping

    U, s, Vt = svd(A / D, full_matrices=False)
    uy = U.T @ y

    # log evidence - 1/2 sum(log(tau^2 s_i^2 + sigma^2)
    #                        + (u_i^T y)^2/(tau^2 s_i^2 + sigma^2))
    variance = (TAU_GRID[:, None] ** 2) * (s[None, :] ** 2) + sigma**2
    log_evidence = -0.5 * (
        np.sum(np.log(variance), axis=1)
        + np.sum((uy[None, :] ** 2) / variance, axis=1)
    )
    tau = float(TAU_GRID[int(np.argmax(log_evidence))])

    alpha = sigma**2 / (tau * tau)
    z = Vt.T @ (s / (s * s + alpha) * uy)
    coeff = z / D

    target = np.load(case_dir / "target_grid.npy").astype(np.float64, copy=False)
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
