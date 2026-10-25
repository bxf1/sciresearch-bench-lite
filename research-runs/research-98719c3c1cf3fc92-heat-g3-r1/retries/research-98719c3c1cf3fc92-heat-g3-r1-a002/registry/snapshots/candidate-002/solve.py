#!/usr/bin/env python3
"""Recover the initial field of a 1-D heat equation from noisy observations.

The initial field is represented by its first 32 sine coefficients.  A
hierarchical Gaussian prior a_k ~ N(0, (C/k^2)^2) is used.  The scale C is
estimated from all cases in the supplied batch by marginal likelihood.  The
first three modes are usually very well determined; the known unit L2 norm of
the initial field then supplies the expected energy left for the remaining
modes, which sets their prior scale.  This adapts the regularisation to each
field instead of imposing one fixed high-mode variance on every case.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

NMODES = 32
KS = np.arange(1, NMODES + 1, dtype=np.float64)
K2 = KS * KS
W = 1.0 / K2
W2 = W * W
S_GRID = np.sin(np.pi * (np.arange(1, 257, dtype=np.float64) / 257.0)[:, None] * KS[None, :])
K_FIXED = 3
TOTAL_NORM2 = 2.0


def load_case(case_dir: Path):
    with (case_dir / "metadata.json").open("r") as f:
        metadata = json.load(f)
    obs = np.loadtxt(case_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    if obs.ndim != 2 or obs.shape[1] < 3 or len(obs) == 0:
        raise ValueError("malformed observations")
    x = np.asarray(obs[:, 0], dtype=np.float64)
    t = np.asarray(obs[:, 1], dtype=np.float64)
    y = np.asarray(obs[:, 2], dtype=np.float64)
    kappa = float(metadata["kappa"])
    sigma = float(metadata["sigma"])
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = max(float(np.std(y)) * 1.0e-3, 1.0e-12)
    return x, t, y, kappa, sigma


def observation_operator(x, t, kappa):
    exponent = -kappa * (math.pi ** 2) * t[:, None] * K2[None, :]
    return np.sin(math.pi * x[:, None] * KS[None, :]) * np.exp(exponent)


def ridge_with_variance(A, y, sigma, variance):
    B = A / sigma
    prec = B.T @ B
    prec.flat[:: NMODES + 1] += 1.0 / variance
    rhs = B.T @ (y / sigma)
    try:
        return np.linalg.solve(prec, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(prec, rhs, rcond=None)[0]


def global_coefficients(A, y, sigma, C):
    return ridge_with_variance(A, y, sigma, (C * W) ** 2)


def log_marginal(A, y, sigma, C):
    try:
        U, s, _ = np.linalg.svd(A, full_matrices=False)
    except np.linalg.LinAlgError:
        return -np.inf
    tau = C * W
    var = (s * tau) ** 2
    noise_var = sigma * sigma
    yp = U.T @ y
    yr = y - U @ yp
    denom = noise_var + var
    if np.any(denom <= 0) or not np.isfinite(denom).all():
        return -np.inf
    logdet = np.sum(np.log(denom)) + (len(y) - len(s)) * math.log(noise_var)
    quad = np.sum(yp * yp / denom) + np.sum(yr * yr) / noise_var
    value = -0.5 * (logdet + quad + len(y) * math.log(2.0 * math.pi))
    return float(value) if np.isfinite(value) else -np.inf


def estimate_scale(cases):
    lo, hi = math.log(0.8), math.log(2.4)
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c = b - phi * (b - a)
    d = a + phi * (b - a)

    def nll(log_c):
        C = math.exp(log_c)
        return -sum(log_marginal(A, y, sig, C) for (A, y, sig) in cases)

    fc, fd = nll(c), nll(d)
    for _ in range(45):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = nll(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = nll(d)
    C = math.exp(0.5 * (a + b))
    if not math.isfinite(C):
        return 1.5
    return float(min(2.0, max(1.05, C)))


def conditional_coefficients(A, y, sigma, C):
    """Use first modes, then distribute the known remaining L2 energy."""
    a0 = global_coefficients(A, y, sigma, C)
    used = float(np.sum(a0[:K_FIXED] ** 2))
    remaining = max(TOTAL_NORM2 - used, 0.02 * TOTAL_NORM2)
    tail_weights = W2[K_FIXED:] / np.sum(W2[K_FIXED:])
    variance = np.empty(NMODES, dtype=np.float64)
    variance[:K_FIXED] = (C * W[:K_FIXED]) ** 2
    variance[K_FIXED:] = remaining * tail_weights
    # A small mixture with the global prior prevents the residual-energy
    # estimate from becoming overconfident on a single noisy low mode.
    variance = 0.8 * variance + 0.2 * (C * W) ** 2
    return ridge_with_variance(A, y, sigma, variance)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    input_root = Path(args.input)
    output_root = Path(args.output)
    with (input_root / "manifest.json").open("r") as f:
        manifest = json.load(f)

    entries = manifest["cases"]
    loaded = []
    cases_for_scale = []
    for entry in entries:
        case_dir = input_root / entry["path"]
        x, t, y, kappa, sigma = load_case(case_dir)
        A = observation_operator(x, t, kappa)
        loaded.append((entry["id"], A, y, sigma))
        cases_for_scale.append((A, y, sigma))

    C = estimate_scale(cases_for_scale)

    for case_id, A, y, sigma in loaded:
        coef = conditional_coefficients(A, y, sigma, C)
        if not np.isfinite(coef).all():
            coef = np.zeros(NMODES, dtype=np.float64)
        u0 = S_GRID @ coef
        u0 = np.asarray(u0, dtype="<f8").reshape(256)
        if not np.isfinite(u0).all():
            u0 = np.zeros(256, dtype="<f8")
        case_out = output_root / "cases" / case_id
        case_out.mkdir(parents=True, exist_ok=True)
        np.save(case_out / "u0.npy", u0, allow_pickle=False)


if __name__ == "__main__":
    main()
