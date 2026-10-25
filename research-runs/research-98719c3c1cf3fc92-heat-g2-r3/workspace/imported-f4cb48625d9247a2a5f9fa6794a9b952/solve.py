#!/usr/bin/env python3
import argparse, json
from pathlib import Path
import numpy as np


def fit_coefficients(case_dir: Path):
    meta = json.loads((case_dir / "metadata.json").read_text())
    obs = np.loadtxt(case_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    x, t, y = obs[:, 0], obs[:, 1], obs[:, 2]
    sigma = float(meta["sigma"])
    kappa = float(meta["kappa"])

    k = np.arange(1, 33, dtype=np.float64)
    # Observation matrix in the 32-mode sine basis, with heat decay at each time.
    A = np.sin(np.pi * x[:, None] * k[None, :])
    A *= np.exp(-kappa * np.pi**2 * t[:, None] * k[None, :] ** 2)
    AtA = A.T @ A
    Aty = A.T @ y
    inv_var = 1.0 / (sigma * sigma)

    # Smooth-field prior: var(a_k) ~ k^-4 with expected squared norm 2.
    total_prior_energy = 2.0
    prior_scale = total_prior_energy / np.sum(k ** -4.0)
    prior_var = prior_scale * k ** -4.0

    precision = AtA * inv_var + np.diag(1.0 / prior_var)
    cov = np.linalg.inv(precision)
    a = cov @ (Aty * inv_var)

    # The low modes reveal how much of the fixed kinetic energy is already
    # resolved.  Use the remaining energy to set the scale of the unresolved
    # modes; this is deliberately conservative when the low modes dominate.
    K0 = 5
    resolved = float(np.sum(a[:K0] ** 2 + np.diag(cov)[:K0]))
    tail_weight = float(np.sum(k[K0:] ** -4.0))
    adaptive_scale = max((total_prior_energy - resolved) / tail_weight,
                         0.05 * prior_scale)
    adaptive_var = adaptive_scale * k ** -4.0
    precision = AtA * inv_var + np.diag(1.0 / adaptive_var)
    a = np.linalg.solve(precision, Aty * inv_var)
    return a


def solve_case(case_dir: Path):
    a = fit_coefficients(case_dir)
    k = np.arange(1, 33, dtype=np.float64)
    grid = np.load(case_dir / "target_grid.npy").astype(np.float64)
    u0 = np.sin(np.pi * np.outer(grid, k)) @ a
    return np.asarray(u0, dtype="<f8").reshape(256)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    inp, out = Path(args.input), Path(args.output)
    manifest = json.loads((inp / "manifest.json").read_text())
    for entry in manifest["cases"]:
        cid = entry["id"]
        u0 = solve_case(inp / entry["path"])
        if not np.isfinite(u0).all():
            u0 = np.zeros(256, dtype="<f8")
        dest = out / "cases" / cid
        dest.mkdir(parents=True, exist_ok=True)
        np.save(dest / "u0.npy", u0)


if __name__ == "__main__":
    main()
