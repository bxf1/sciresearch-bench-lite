#!/usr/bin/env python3
"""Recover the initial temperature field for batches of 1-D heat inverse problems.

Model: u_t = kappa u_xx on (0,1), u(0,t)=u(1,t)=0, u0 in span{sin(pi k x)}_{k=1..32}.
Observations y_i = sum_k b_k e^{-kappa pi^2 k^2 t_i} sin(pi k x_i) + N(0, sigma^2).

Estimator: Bayesian posterior mean for b (32 sine coefficients) with independent
Student-t priors (scale mixture of Gaussians, EM / evidence updates).  The prior
scale on the tail modes is deliberately generous enough that any mode the data can
see is retained, while modes with no information are shrunk to zero.  A total-energy
check (the generated fields are L2-normalised, sum b_k^2 ~= 2) provides a safety
net that re-expands the prior only if the posterior energy is implausibly small.

The posterior mean is computed through an SVD of A*diag(sqrt(prior variance)), so it
is numerically stable even though the forward map is severely ill-conditioned for
high modes.
"""
import argparse
import json
import os
import sys

import numpy as np

K = 32
NU = 4.0
S1 = 1.5          # prior sd for modes 1,2 (data always dominate these)
S_TAIL = 0.25     # prior scale for tail modes
P_TAIL = 1.5      # envelope: var_k = S_TAIL^2 * k^{-2 P_TAIL}
ENERGY_TARGET = 1.95   # sum b_k^2 is ~2; below this we re-expand the prior
HEDGE_SCALES = (0.5, 0.9)


def prior_variance(s_tail):
    gam = np.empty(K)
    gam[0] = gam[1] = S1 * S1
    ks = np.arange(3, K + 1, dtype=float)
    gam[2:] = max(s_tail, 1e-6) ** 2 * ks ** (-2.0 * P_TAIL)
    return gam


def design_matrix(x, t, kappa):
    ks = np.arange(1, K + 1, dtype=float)
    # decay can underflow to zero for invisible high modes: that is intended
    dec = np.exp(-kappa * np.pi ** 2 * ks ** 2 * t[:, None])
    return np.sin(np.pi * np.outer(x, ks)) * dec


def posterior_mean(A, y, sigma, gam):
    """Gaussian posterior mean with prior N(0, diag(gam)); returns mean, diag(cov)."""
    sg = np.sqrt(np.maximum(gam, 0.0))
    B = A * sg[None, :]
    U, s, Vt = np.linalg.svd(B, full_matrices=False)
    denom = s * s + sigma * sigma
    c = (s / denom) * (U.T @ y)
    b = sg * (Vt.T @ c)
    w = (sigma * sigma) / denom
    dvar = gam * (Vt.T ** 2 @ w)
    return b, dvar


def em_t(A, y, sigma, gam0, nu=NU, niter=30):
    """EM for b_k ~ t_nu(0, gam0_k) independent; returns posterior mean, diag cov, gam."""
    gam = gam0.copy()
    b, dvar = posterior_mean(A, y, sigma, gam)
    for _ in range(niter):
        gam_new = (b * b + dvar + nu * gam0) / (nu + 1.0)
        if np.max(np.abs(gam_new - gam)) <= 1e-9 * max(1.0, np.max(gam)):
            gam = gam_new
            break
        gam = gam_new
        b, dvar = posterior_mean(A, y, sigma, gam)
    return b, dvar, gam


def estimate(x, t, y, kappa, sigma):
    A = design_matrix(x, t, kappa)
    best = None
    scales = (S_TAIL,) + HEDGE_SCALES
    for i, s in enumerate(scales):
        b, dvar, gam = em_t(A, y, sigma, prior_variance(s))
        energy = float(np.sum(b * b + dvar))
        if best is None:
            best = b
        if energy >= ENERGY_TARGET:
            return b
        best = b  # keep the most recent (largest prior) estimate
    return best


def fallback_estimate(x, t, y, kappa, sigma):
    """Truncated-SVD least squares, used only if the main estimator raises."""
    A = design_matrix(x, t, kappa)
    U, s, Vt = np.linalg.svd(A, full_matrices=False)
    keep = s > max(s[0], 1e-300) * 1e-6
    c = np.zeros(len(s))
    c[keep] = (U[:, keep].T @ y) / s[keep]
    b = Vt.T @ c
    return np.nan_to_num(b, nan=0.0, posinf=0.0, neginf=0.0)


def read_case(case_dir):
    with open(os.path.join(case_dir, "metadata.json")) as f:
        meta = json.load(f)
    path = os.path.join(case_dir, "observations.csv")
    with open(path) as f:
        header = f.readline().strip().split(",")
    cols = [h.strip() for h in header]
    data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    ix = {name: i for i, name in enumerate(cols)}
    x = np.asarray(data[:, ix["x"]], dtype=float)
    t = np.asarray(data[:, ix["t"]], dtype=float)
    y = np.asarray(data[:, ix["y"]], dtype=float)
    kappa = float(meta["kappa"])
    sigma = float(meta["sigma"])
    return x, t, y, kappa, sigma


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)
    out_root = args.output
    os.makedirs(out_root, exist_ok=True)

    for case in manifest.get("cases", []):
        cid = str(case["id"])
        cpath = case.get("path", os.path.join("cases", cid))
        case_dir = cpath
        if not os.path.isdir(case_dir):
            case_dir = os.path.join(args.input, cpath)
        if not os.path.isdir(case_dir):
            case_dir = os.path.join(args.input, "cases", cid)

        try:
            x, t, y, kappa, sigma = read_case(case_dir)
            if sigma <= 0:
                sigma = 1e-12
            if len(x) == 0:
                raise ValueError("no observations")
            try:
                b = estimate(x, t, y, kappa, sigma)
            except Exception:
                b = fallback_estimate(x, t, y, kappa, sigma)
        except Exception:
            b = np.zeros(K)

        b = np.asarray(b, dtype=float).reshape(-1)
        if b.size < K:
            bb = np.zeros(K)
            bb[: b.size] = b
            b = bb
        b = b[:K]
        b = np.where(np.isfinite(b), b, 0.0)
        # keep coefficients within a sane physical range (safety only)
        b = np.clip(b, -10.0, 10.0)

        # target grid: x_j = j/257, j=1..256 (file preferred when available)
        grid = None
        try:
            grid = np.load(os.path.join(case_dir, "target_grid.npy")).astype(float).reshape(-1)
        except Exception:
            grid = None
        if grid is None or grid.size != 256 or not np.all(np.isfinite(grid)):
            grid = np.arange(1, 257) / 257.0
        ks = np.arange(1, K + 1, dtype=float)
        u0 = np.sin(np.pi * np.outer(grid, ks)) @ b
        u0 = np.nan_to_num(np.asarray(u0, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
        if u0.shape != (256,):
            u0 = np.resize(u0, 256)

        cdir = os.path.join(out_root, "cases", cid)
        os.makedirs(cdir, exist_ok=True)
        np.save(os.path.join(cdir, "u0.npy"), u0.astype("<f8"))


if __name__ == "__main__":
    main()
