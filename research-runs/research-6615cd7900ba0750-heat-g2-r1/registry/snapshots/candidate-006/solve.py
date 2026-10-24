#!/usr/bin/env python3
"""Recover initial fields for 1D heat inverse problems.

Model: u_t = kappa * u_xx on (0,1), u(0,t)=u(1,t)=0.
Initial field is a finite sine series with at most `mode_limit` modes:
    u0(x) = sum_{k=1..K} c_k sin(k*pi*x)
Solution:
    u(x,t) = sum_k c_k exp(-kappa*pi^2*k^2*t) sin(k*pi*x)

Observations are noisy samples of u at two positive times on a grid that is
NOT the target grid, so we evaluate the sine basis at the observation
x-coordinates directly.

Ill-posedness: the decay factor exp(-kappa*pi^2*k^2*t) is tiny for large k at
the later time, so high modes are essentially unobservable.  We solve a
Tikhonov-regularised least squares problem in the coefficient vector, with a
penalty that grows with k (and with the inverse of the information content),
which keeps the recovered u0 stable while still fitting the data.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np


def load_case(case_dir: Path):
    meta = json.loads((case_dir / "metadata.json").read_text())
    obs = np.genfromtxt(case_dir / "observations.csv", delimiter=",", names=True)
    x = np.asarray(obs["x"], dtype=np.float64)
    t = np.asarray(obs["t"], dtype=np.float64)
    y = np.asarray(obs["y"], dtype=np.float64)
    grid_path = case_dir / "target_grid.npy"
    if grid_path.is_file():
        grid = np.load(grid_path).astype(np.float64)
    else:
        n = int(meta.get("target_size", 256))
        grid = np.arange(1, n + 1) / (n + 1)
    return meta, x, t, y, grid


def solve_case(meta, x, t, y, grid, reg_scale=1.0):
    kappa = float(meta["kappa"])
    sigma = float(meta.get("sigma", 1e-3)) or 1e-3
    K = int(meta.get("mode_limit", 32))
    ks = np.arange(1, K + 1, dtype=np.float64)

    # Design matrix: rows are observations, columns are modes.
    # A[i, k-1] = exp(-kappa*pi^2*k^2*t_i) * sin(k*pi*x_i)
    decay = np.exp(-kappa * np.pi**2 * ks[None, :] ** 2 * t[:, None])
    basis = np.sin(np.pi * x[:, None] * ks[None, :])
    A = decay * basis

    # Weight rows by 1/sigma (uniform sigma -> constant scaling, but keep it
    # explicit so the regularisation strength is in data units).
    w = 1.0 / sigma
    Aw = A * w
    yw = y * w

    # Regularisation: penalise high modes more strongly.  The natural scale is
    # the noise amplification of each mode, ~ 1/decay.  We use a smooth
    # spectral penalty lambda_k = reg_scale * (k/K)^p / (typical decay).
    # A simpler and robust choice: ridge on the coefficient vector with a
    # k-dependent weight derived from the *later* time decay (worst case).
    t_late = float(np.max(t))
    d_late = np.exp(-kappa * np.pi**2 * ks**2 * t_late)
    # information weight: modes whose late-time signal is below noise are
    # effectively unconstrained; penalise them hard.
    info = d_late / sigma  # signal-to-noise per unit coefficient
    # penalty grows as information vanishes
    lam = reg_scale * (1.0 / np.maximum(info, 1e-12)) ** 2
    # normalise so the smallest penalty is ~1 (pure ridge floor)
    lam = lam / np.min(lam)
    # add mild smoothness in k
    lam = lam * (1.0 + 0.05 * (ks / K) ** 2)

    # Solve (A^T A + diag(lam)) c = A^T y  in weighted form
    AtA = Aw.T @ Aw
    Aty = Aw.T @ yw
    reg = np.diag(lam)
    c = np.linalg.solve(AtA + reg, Aty)

    # Evaluate u0 on the target grid.
    u0 = np.sin(np.pi * grid[:, None] * ks[None, :]) @ c
    return u0, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--reg", type=float, default=1.0)
    args = ap.parse_args()

    in_root = Path(args.input)
    out_root = Path(args.output)
    manifest = json.loads((in_root / "manifest.json").read_text())

    for entry in manifest["cases"]:
        cid = entry["id"]
        case_dir = in_root / entry["path"]
        meta, x, t, y, grid = load_case(case_dir)
        u0, _ = solve_case(meta, x, t, y, grid, reg_scale=args.reg)
        out_dir = out_root / "cases" / cid
        out_dir.mkdir(parents=True, exist_ok=True)
        u0 = np.ascontiguousarray(u0, dtype="<f8")
        np.save(out_dir / "u0.npy", u0)


if __name__ == "__main__":
    main()
