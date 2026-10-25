#!/usr/bin/env python3
"""Bayesian recovery of the initial 32-mode sine field.

Prior from the data-generating structure: c_k = sqrt(2) * z_k k^-2 / ||z k^-2||,
z iid N(0,1).  This implies sum_k c_k^2 = 2.  We use a Gaussian prior
c ~ N(0, tau * diag(k^-4)) and choose tau per case by matching the posterior
expected squared coefficient norm to 2.  The posterior mean is the MMSE estimate.
"""
import argparse
import json
import os

import numpy as np

K = 32
POWER = 2.0
TARGET_NORM2 = 2.0


def posterior_stats(A, y, sigma, tau):
    """Return posterior mean and covariance trace for c ~ N(0,tau diag(k^-4))."""
    k = np.arange(1, K + 1, dtype=np.float64)
    r = np.sqrt(tau) * k ** (-POWER)
    Aw = A * (r / sigma)[None, :]
    yw = y / sigma
    C = Aw.T @ Aw + np.eye(K)
    try:
        X = np.linalg.solve(C, np.eye(K))
        z = X @ (Aw.T @ yw)
    except np.linalg.LinAlgError:
        X = np.linalg.pinv(C)
        z = X @ (Aw.T @ yw)
    m = r * z
    tr = float(np.sum(r * r * np.diag(X)))
    return m, tr


def estimate(A, y, sigma):
    lo, hi = -20.0, 10.0
    # E||c||^2 is increasing in tau.  Bisection on log(tau).
    m_lo, tr_lo = posterior_stats(A, y, sigma, np.exp(lo))
    m_hi, tr_hi = posterior_stats(A, y, sigma, np.exp(hi))
    n_lo = float(m_lo @ m_lo + tr_lo)
    n_hi = float(m_hi @ m_hi + tr_hi)
    if n_lo >= TARGET_NORM2:
        return m_lo
    if n_hi <= TARGET_NORM2:
        return m_hi
    for _ in range(90):
        mid = 0.5 * (lo + hi)
        m, tr = posterior_stats(A, y, sigma, np.exp(mid))
        if float(m @ m + tr) < TARGET_NORM2:
            lo = mid
        else:
            hi = mid
    m, _ = posterior_stats(A, y, sigma, np.exp(0.5 * (lo + hi)))
    return m


def fixed_tikhonov(A, y, alpha=1e-5):
    k = np.arange(1, K + 1, dtype=np.float64)
    Dinv = 1.0 / (k * k)
    B = A * Dinv[None, :]
    U, s, Vt = np.linalg.svd(B, full_matrices=False)
    lam = alpha * s[0] ** 2
    return Dinv * (Vt.T @ ((s / (s * s + lam)) * (U.T @ y)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)
    k = np.arange(1, K + 1, dtype=np.float64)
    j = np.arange(1, 257, dtype=np.float64)
    S = np.sin(np.pi * np.outer(j, k) / 257.0)

    for entry in manifest["cases"]:
        cdir = os.path.join(args.input, entry["path"])
        with open(os.path.join(cdir, "metadata.json")) as f:
            md = json.load(f)
        obs = np.loadtxt(os.path.join(cdir, "observations.csv"),
                         delimiter=",", skiprows=1, ndmin=2)
        x, t, y = obs[:, 0], obs[:, 1], obs[:, 2]
        A = np.sin(np.pi * np.outer(x, k)) * np.exp(
            -md["kappa"] * np.pi ** 2 * np.outer(t, k * k))
        sigma = float(md["sigma"])
        try:
            c = estimate(A, y, sigma)
        except Exception:
            c = fixed_tikhonov(A, y)
        c = np.asarray(c, dtype=np.float64)
        if not np.isfinite(c).all():
            c = fixed_tikhonov(A, y)
        u0 = S @ c
        u0 = np.ascontiguousarray(u0, dtype="<f8")
        outdir = os.path.join(args.output, "cases", entry["id"])
        os.makedirs(outdir, exist_ok=True)
        np.save(os.path.join(outdir, "u0.npy"), u0)


if __name__ == "__main__":
    main()
