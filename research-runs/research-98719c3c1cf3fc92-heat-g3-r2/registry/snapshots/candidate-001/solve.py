#!/usr/bin/env python3
"""Recover the initial field for batches of 1-D heat inverse problems."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar


def load_case(case_dir: Path):
    metadata = json.loads((case_dir / "metadata.json").read_text())
    obs = np.loadtxt(case_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    if obs.size == 0:
        obs = np.empty((0, 3), dtype=float)
    return metadata, obs


def negative_log_evidence(log_c, A, y, sigma, k, p):
    c = np.exp(log_c)
    var = (c * k ** (-p)) ** 2
    m = A.shape[0]
    cov = (A * var[None, :]) @ A.T
    cov[np.diag_indices(m)] += sigma * sigma
    try:
        L = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        return 1.0e100
    alpha = np.linalg.solve(L, y)
    return 0.5 * float(alpha @ alpha) + float(np.sum(np.log(np.diag(L))))


def estimate(case_dir: Path):
    metadata, obs = load_case(case_dir)
    kappa = float(metadata["kappa"])
    sigma = float(metadata["sigma"])
    target = np.load(case_dir / "target_grid.npy", allow_pickle=False)
    target = np.asarray(target, dtype=np.float64).reshape(-1)

    x = np.asarray(obs[:, 0], dtype=np.float64)
    t = np.asarray(obs[:, 1], dtype=np.float64)
    y = np.asarray(obs[:, 2], dtype=np.float64)

    limit = int(metadata.get("mode_limit", 32))
    limit = max(1, min(32, limit))
    k = np.arange(1, limit + 1, dtype=np.float64)

    # Observation operator for the retained coordinates and times.
    exponent = kappa * np.pi**2 * np.outer(t, k * k)
    exponent = np.minimum(exponent, 700.0)
    A = np.sin(np.pi * np.outer(x, k)) * np.exp(-exponent)

    # Coefficient prior: a_k ~ N(0, (c/k^2)^2).  The p=2 envelope is the
    # smoothness scale of the public data family.  Estimate its amplitude
    # per case by type-II maximum likelihood, with a safe fallback.
    p = 2.0
    c = 1.4
    if len(y) >= limit:
        try:
            result = minimize_scalar(
                negative_log_evidence,
                bounds=(np.log(0.12), np.log(24.0)),
                args=(A, y, sigma, k, p),
                method="bounded",
                options={"xatol": 1.0e-4},
            )
            if np.isfinite(result.fun):
                c = float(np.exp(result.x))
        except Exception:
            c = 1.4

    var = (c * k ** (-p)) ** 2
    # Posterior mean under the Gaussian coefficient prior, expressed as a
    # least-squares problem with prior whitening for numerical stability.
    M = A.T @ A
    M[np.diag_indices(limit)] += sigma * sigma / var
    rhs = A.T @ y
    try:
        a = np.linalg.solve(M, rhs)
    except np.linalg.LinAlgError:
        a = np.linalg.lstsq(M, rhs, rcond=None)[0]

    u0 = np.sin(np.pi * np.outer(target, k)) @ a
    u0 = np.asarray(u0, dtype="<f8").reshape(-1)
    if u0.size != target.size or not np.isfinite(u0).all():
        raise RuntimeError("invalid reconstruction")
    return u0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    np.random.seed(args.seed)
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    manifest = json.loads((input_dir / "manifest.json").read_text())

    for case in manifest["cases"]:
        case_id = str(case["id"])
        case_dir = input_dir / case["path"]
        u0 = estimate(case_dir)
        destination = output_dir / "cases" / case_id / "u0.npy"
        destination.parent.mkdir(parents=True, exist_ok=True)
        np.save(destination, u0, allow_pickle=False)


if __name__ == "__main__":
    main()
