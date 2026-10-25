#!/usr/bin/env python3
"""Recover the initial field of a 1-D heat equation from noisy observations.

The initial field is represented by its first 32 sine coefficients.  A
hierarchical Gaussian prior a_k ~ N(0, (C/k^2)^2) is used.  The scale C is
estimated from all cases in the supplied batch by marginal likelihood, which
makes the estimate insensitive to the particular random amplitudes in a batch.
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
S_GRID = np.sin(np.pi * (np.arange(1, 257, dtype=np.float64) / 257.0)[:, None] * KS[None, :])


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
    # A_ik = exp(-kappa*pi^2*k^2*t) * sin(pi*k*x)
    exponent = -kappa * (math.pi ** 2) * t[:, None] * K2[None, :]
    return np.sin(math.pi * x[:, None] * KS[None, :]) * np.exp(exponent)


def posterior_coefficients(A, y, sigma, C):
    """Posterior mean of a with independent N(0,(C/k^2)^2) coefficients."""
    tau = C / K2
    B = A / sigma
    prec = B.T @ B
    prec.flat[:: NMODES + 1] += 1.0 / (tau * tau)
    rhs = B.T @ (y / sigma)
    try:
        return np.linalg.solve(prec, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(prec, rhs, rcond=None)[0]


def log_marginal(A, y, sigma, C):
    """Log p(y | C) after analytically integrating out the coefficients."""
    try:
        U, s, _ = np.linalg.svd(A, full_matrices=False)
    except np.linalg.LinAlgError:
        return -np.inf
    tau = C / K2
    var = (s * tau) ** 2                 # a^2 tau_k^2, with s the singular values
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
    """Maximise the batch marginal likelihood over a positive scale C.

    A bounded golden-section search is used so that solve.py has no dependency
    on an optimiser implementation beyond NumPy.
    """
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
        coef = posterior_coefficients(A, y, sigma, C)
        # Safety: reject non-finite numerical accidents in favour of the prior
        # mean (which is zero for every coefficient).
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
