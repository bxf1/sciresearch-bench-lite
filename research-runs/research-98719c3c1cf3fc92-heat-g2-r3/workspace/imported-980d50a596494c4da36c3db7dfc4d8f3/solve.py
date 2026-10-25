#!/usr/bin/env python3
import argparse, json, os
from pathlib import Path
import numpy as np


def solve_case(case_dir: Path):
    meta = json.loads((case_dir / "metadata.json").read_text())
    obs = np.loadtxt(case_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    x = obs[:, 0].astype(np.float64)
    t = obs[:, 1].astype(np.float64)
    y = obs[:, 2].astype(np.float64)
    sigma = float(meta["sigma"])
    kappa = float(meta["kappa"])

    K = 32
    k = np.arange(1, K + 1, dtype=np.float64)
    # Design operator for observations: each row is a sine mode propagated to (x,t).
    A = np.sin(np.pi * x[:, None] * k[None, :])
    A *= np.exp(-kappa * np.pi**2 * t[:, None] * k[None, :] ** 2)

    # Smoothness prior inferred from the low-mode content of the problem family:
    # var(a_k) proportional to k^-4, with expected squared norm 2.
    prior_var = (2.0 / np.sum(k ** -4.0)) * k ** -4.0
    precision = A.T @ A / (sigma * sigma) + np.diag(1.0 / prior_var)
    rhs = A.T @ y / (sigma * sigma)
    a = np.linalg.solve(precision, rhs)

    grid = np.load(case_dir / "target_grid.npy").astype(np.float64)
    basis = np.sin(np.pi * np.outer(grid, k))
    return basis @ a


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    inp = Path(args.input)
    out = Path(args.output)
    manifest = json.loads((inp / "manifest.json").read_text())
    for entry in manifest["cases"]:
        cid = entry["id"]
        case_dir = inp / entry["path"]
        u0 = solve_case(case_dir)
        u0 = np.asarray(u0, dtype="<f8").reshape(256)
        if not np.isfinite(u0).all():
            u0 = np.zeros(256, dtype="<f8")
        dest = out / "cases" / cid
        dest.mkdir(parents=True, exist_ok=True)
        np.save(dest / "u0.npy", u0)


if __name__ == "__main__":
    main()
