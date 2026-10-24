"""Standalone T1 baselines. All parameter choices use public observations only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import chi2


def solve_case(input_dir, method):
    meta = json.loads((input_dir / "metadata.json").read_text())
    obs = np.loadtxt(input_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    x, t, y = obs.T
    k = np.arange(1, 33, dtype=float)
    matrix = np.sin(np.pi * x[:, None] * k) * np.exp(-meta["kappa"] * np.pi**2 * t[:, None] * k**2)
    fallback = np.zeros(32)
    fallback[:5] = np.linalg.lstsq(matrix[:, :5], y, rcond=None)[0]
    info = {"method": method, "fallback": False}
    if method == "ls":
        coefficients = np.linalg.lstsq(matrix, y, rcond=1e-12)[0]
    elif method == "rank5":
        coefficients = fallback
    elif method in ("tikhonov", "discrepancy"):
        U, s, Vt = np.linalg.svd(matrix / k**2, full_matrices=False)
        projection = np.einsum("ij,i->j", U, y)

        def estimate(alpha):
            lam = alpha * s[0]**2
            return np.einsum("ij,i->j", Vt, s / (s**2 + lam) * projection) / k**2

        if method == "tikhonov":
            coefficients = estimate(1e-5)
            info["alpha"] = 1e-5
        else:
            bound = float(meta["sigma"]**2 * chi2.ppf(.99, len(y)))
            accepted, residuals = [], []
            for alpha in np.logspace(-10, 0, 81):
                value = estimate(alpha)
                residual = np.linalg.norm(np.einsum("ij,j->i", matrix, value) - y)**2
                residuals.append(float(residual))
                if residual <= bound:
                    accepted.append((float(alpha), value))
            info.update({"noise_energy_bound": bound, "fallback": not bool(accepted), "alpha": accepted[-1][0] if accepted else None,
                         "minimum_residual": min(residuals), "alpha_range": [1e-10, 1.0], "alpha_count": 81})
            coefficients = accepted[-1][1] if accepted else fallback
    elif method == "tsvd":
        U, s, Vt = np.linalg.svd(matrix, full_matrices=False)
        projection = np.einsum("ij,i->j", U, y)
        bound = float(meta["sigma"]**2 * chi2.ppf(.99, len(y)))
        coefficients, selected_rank, residuals = fallback, None, []
        for rank in range(1, len(s) + 1):
            if s[rank - 1] <= s[0] * 1e-12:
                break
            value = np.einsum("ij,i->j", Vt[:rank], projection[:rank] / s[:rank])
            residual = np.linalg.norm(np.einsum("ij,j->i", matrix, value) - y)**2
            residuals.append(float(residual))
            if residual <= bound:
                coefficients, selected_rank = value, rank
                break
        info.update({"noise_energy_bound": bound, "fallback": selected_rank is None, "rank": selected_rank,
                     "minimum_tested_residual": min(residuals) if residuals else None,
                     "tested_rank_range": [1, len(residuals)], "relative_singular_cutoff": 1e-12})
    else:
        raise ValueError("unknown method")
    grid = np.load(input_dir / "target_grid.npy", allow_pickle=False)
    return np.einsum("ij,j->i", np.sin(np.pi * grid[:, None] * k), coefficients).astype("<f8"), info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--method", choices=["ls", "rank5", "tikhonov", "discrepancy", "tsvd"], default="tikhonov")
    args = parser.parse_args()
    manifest = json.loads((args.input / "manifest.json").read_text())
    for case in manifest["cases"]:
        value, info = solve_case(args.input / case["path"], args.method)
        output = args.output / "cases" / case["id"]
        output.mkdir(parents=True, exist_ok=True)
        np.save(output / "u0.npy", value, allow_pickle=False)
        print(json.dumps({"case": case["id"], **info}, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
