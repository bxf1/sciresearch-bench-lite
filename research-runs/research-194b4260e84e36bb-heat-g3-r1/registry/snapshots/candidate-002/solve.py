#!/usr/bin/env python3
"""Recover the initial temperature field for 1-D heat inverse problems.

Model (dimensionless):  u_t = kappa u_xx on (0,1), u(0,t)=u(1,t)=0.
Truth:                  u0(x) = sum_{k=1..K} b_k sin(pi k x),  K = 32.
Observation model:      y_i = u(x_i,t_i) + N(0, sigma^2),
                        u(x,t) = sum_k b_k exp(-kappa pi^2 k^2 t) sin(pi k x).

We estimate b by a Bayesian MAP with independent Student-t priors whose
per-mode scales encode the (empirically observed) rapidly decaying spectrum
of the initial fields.  Heavy tails keep genuine large modes while the scale
suppresses noise amplification of modes that are almost fully damped at the
observation times.  The final field is evaluated on the provided target grid
and written as little-endian float64.
"""

import argparse
import json
import os
import sys

import numpy as np

K_DEFAULT = 32

# Per-mode prior standard deviations (dev-ensemble informed, mildly inflated).
PRIOR_BASE = np.array([1.50, 0.45, 0.12, 0.10, 0.14, 0.08, 0.08, 0.06,
                       0.05, 0.04, 0.035, 0.03])
PRIOR_FLOOR = 0.03
# Global scale of the prior envelope (tuned on public dev cases / simulations).
PRIOR_SCALE = 0.5


def prior_sd(K):
    s = np.full(K, PRIOR_FLOOR)
    m = min(K, PRIOR_BASE.size)
    s[:m] = PRIOR_BASE[:m]
    return s * PRIOR_SCALE


def read_json(path):
    with open(path, "r") as fh:
        return json.load(fh)


def read_observations(path):
    """Return x, t, y arrays; tolerant to header variations."""
    x = t = y = None
    try:
        data = np.genfromtxt(path, delimiter=",", names=True, dtype=np.float64)
        if data.dtype.names is not None:
            names = {n.lower().strip(): n for n in data.dtype.names}
            if all(c in names for c in ("x", "t", "y")):
                x = np.atleast_1d(np.asarray(data[names["x"]], dtype=np.float64))
                t = np.atleast_1d(np.asarray(data[names["t"]], dtype=np.float64))
                y = np.atleast_1d(np.asarray(data[names["y"]], dtype=np.float64))
    except Exception:
        x = None
    if x is None:
        raw = np.genfromtxt(path, delimiter=",", skip_header=1, dtype=np.float64)
        raw = np.atleast_2d(raw)
        if raw.shape[1] < 3:
            raw = np.atleast_2d(np.genfromtxt(path, delimiter=",", dtype=np.float64))
        x, t, y = raw[:, 0], raw[:, 1], raw[:, 2]
    ok = np.isfinite(x) & np.isfinite(t) & np.isfinite(y)
    return x[ok], t[ok], y[ok]


def design_matrix(x, t, kappa, K):
    """A[i,k-1] = exp(-kappa pi^2 k^2 t_i) sin(pi k x_i)."""
    k = np.arange(1, K + 1, dtype=np.float64)
    decay = np.exp(-kappa * np.pi ** 2 * t[:, None] * (k ** 2)[None, :])
    return decay * np.sin(np.pi * x[:, None] * k[None, :])


def gauss_map(AtA, Aty, sig2, c):
    H = AtA / sig2 + np.diag(1.0 / c)
    return np.linalg.solve(H, Aty / sig2), H


def student_t_map(AtA, Aty, sig2, s, nu=1.0, niter=60):
    """MAP for independent Student-t(nu, scale s) priors via IRLS."""
    c = s ** 2
    H0 = AtA / sig2
    b, H = gauss_map(AtA, Aty, sig2, c)
    lam = 1.0 / c
    for _ in range(niter):
        Hl = H0 + np.diag(lam)
        try:
            b_new = np.linalg.solve(Hl, Aty / sig2)
        except np.linalg.LinAlgError:
            return b
        b_new = np.nan_to_num(b_new, nan=0.0, posinf=0.0, neginf=0.0)
        lam_new = (nu + 1.0) / (nu * c + b_new ** 2)
        if np.max(np.abs(lam_new - lam)) <= 1e-9 * max(np.max(lam_new), 1e-30):
            return b_new
        lam = lam_new
        b = b_new
    return b


def solve_case(case_dir, K=K_DEFAULT):
    meta_path = os.path.join(case_dir, "metadata.json")
    obs_path = os.path.join(case_dir, "observations.csv")
    grid_path = os.path.join(case_dir, "target_grid.npy")

    meta = read_json(meta_path) if os.path.exists(meta_path) else {}
    kappa = float(meta.get("kappa", 1.0))
    sigma = float(meta.get("sigma", 1e-2))
    if not np.isfinite(kappa) or kappa <= 0:
        kappa = 1.0
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = 1e-2

    grid = None
    if os.path.exists(grid_path):
        grid = np.asarray(np.load(grid_path, allow_pickle=False), dtype=np.float64).ravel()
    if grid is None or grid.size == 0:
        grid = np.arange(1, 257, dtype=np.float64) / 257.0

    x, t, y = read_observations(obs_path)
    Kl = int(meta.get("mode_limit", K) or K)
    Kl = max(1, min(Kl, K))
    if x.size < 2 or not np.isfinite(kappa):
        return np.zeros(grid.size, dtype="<f8")

    A = design_matrix(x, t, kappa, Kl)
    if not np.all(np.isfinite(A)):
        A = np.nan_to_num(A, nan=0.0, posinf=0.0, neginf=0.0)
    AtA = A.T @ A
    Aty = A.T @ y
    sig2 = sigma ** 2
    s = prior_sd(Kl)

    b = None
    try:
        b = student_t_map(AtA, Aty, sig2, s)
    except Exception:
        try:
            b, _ = gauss_map(AtA, Aty, sig2, s ** 2)
        except Exception:
            b = None
    if b is None or not np.all(np.isfinite(b)):
        try:
            b, _ = gauss_map(AtA, Aty, sig2, s ** 2)
        except Exception:
            b = np.zeros(Kl)
    b = np.nan_to_num(b, nan=0.0, posinf=0.0, neginf=0.0)

    # Reconstruct the initial field on the target grid.
    k = np.arange(1, b.size + 1, dtype=np.float64)
    u0 = np.sin(np.pi * np.outer(grid, k)) @ b
    u0 = np.nan_to_num(u0, nan=0.0, posinf=0.0, neginf=0.0)
    # Keep magnitudes physical (prior already prevents blow-up; hard safety net).
    lim = 1e6
    u0 = np.clip(u0, -lim, lim)
    return np.ascontiguousarray(u0, dtype="<f8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    in_dir = args.input
    out_dir = args.output

    manifest = read_json(os.path.join(in_dir, "manifest.json"))
    cases = manifest.get("cases", [])

    for case in cases:
        cid = str(case.get("id"))
        rel = case.get("path") or os.path.join("cases", cid)
        cdir = rel if os.path.isabs(rel) else os.path.join(in_dir, rel)
        if not os.path.isdir(cdir):
            cdir = os.path.join(in_dir, "cases", cid)
        try:
            u0 = solve_case(cdir)
        except Exception:
            gp = os.path.join(cdir, "target_grid.npy")
            try:
                u0 = np.zeros(np.load(gp).size, dtype="<f8")
            except Exception:
                u0 = np.zeros(256, dtype="<f8")
        odir = os.path.join(out_dir, "cases", cid)
        os.makedirs(odir, exist_ok=True)
        np.save(os.path.join(odir, "u0.npy"), u0.astype("<f8", copy=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
