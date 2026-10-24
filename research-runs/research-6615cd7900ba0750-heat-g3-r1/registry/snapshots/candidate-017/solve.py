#!/usr/bin/env python3
"""Recover initial temperature field for 1D heat inverse problems.

Model: u(x,t) = sum_{k=1..32} c_k sin(k*pi*x) exp(-kappa*pi^2*k^2*t)

Given noisy observations at two times t1 < t2, estimate the initial-mode
coefficients c_k, then reconstruct u0 on the target grid x_j = j/257.

The estimation is a single regularised least-squares problem over both
observation times.  The design matrix uses the *decayed* sine basis, so the
later time naturally down-weights high modes (which are noise-dominated
there), while the earlier time constrains them.  A small ridge penalty on
the coefficients keeps the ill-conditioned high modes bounded.
"""
import argparse
import json
import os

import numpy as np

MODES = 32


def load_case(case_dir):
    with open(os.path.join(case_dir, "metadata.json")) as f:
        meta = json.load(f)
    obs_path = os.path.join(case_dir, "observations.csv")
    data = np.genfromtxt(obs_path, delimiter=",", names=True)
    x = np.atleast_1d(data["x"]).astype(np.float64)
    t = np.atleast_1d(data["t"]).astype(np.float64)
    y = np.atleast_1d(data["y"]).astype(np.float64)
    return meta, x, t, y


def estimate_modes(x, t, y, kappa, sigma, K, lam):
    """Joint regularised least squares for the initial-mode coefficients.

    Solves  min_c ||A c - y||^2 + lam * ||c||^2  where the rows of A are
    sin(k*pi*x_i) * exp(-kappa*pi^2*k^2*t_i).
    """
    decay = np.exp(-kappa * np.pi**2 * np.outer(t, K**2))
    A = np.sin(np.pi * np.outer(x, K)) * decay
    G = A.T @ A
    b = A.T @ y
    G[np.diag_indices_from(G)] += lam
    try:
        c = np.linalg.solve(G, b)
    except np.linalg.LinAlgError:
        c = np.linalg.lstsq(G, b, rcond=None)[0]
    return c


def solve_case(case_dir, lam=1e-4):
    meta, x, t, y = load_case(case_dir)
    kappa = float(meta["kappa"])
    sigma = float(meta.get("sigma", 0.0))
    K = np.arange(1, MODES + 1, dtype=np.float64)

    c = estimate_modes(x, t, y, kappa, sigma, K, lam)

    grid_path = os.path.join(case_dir, "target_grid.npy")
    if os.path.exists(grid_path):
        xg = np.load(grid_path).astype(np.float64).ravel()
    else:
        n = int(meta.get("target_size", 256))
        xg = np.arange(1, n + 1, dtype=np.float64) / (n + 1)

    u0 = np.sin(np.pi * np.outer(xg, K)) @ c
    u0 = np.nan_to_num(u0, nan=0.0, posinf=0.0, neginf=0.0)
    return u0.astype("<f8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    inp = args.input
    out = args.output
    os.makedirs(out, exist_ok=True)

    manifest_path = os.path.join(inp, "manifest.json")
    case_entries = []
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        case_entries = manifest.get("cases", [])

    if case_entries:
        for entry in case_entries:
            cid = entry["id"]
            rel = entry.get("path", os.path.join("cases", cid))
            case_dir = os.path.join(inp, rel)
            u0 = solve_case(case_dir)
            odir = os.path.join(out, "cases", cid)
            os.makedirs(odir, exist_ok=True)
            np.save(os.path.join(odir, "u0.npy"), u0)
    else:
        for cid in sorted(os.listdir(inp)):
            case_dir = os.path.join(inp, cid)
            if not os.path.isdir(case_dir):
                continue
            if not os.path.exists(os.path.join(case_dir, "metadata.json")):
                continue
            u0 = solve_case(case_dir)
            odir = os.path.join(out, "cases", cid)
            os.makedirs(odir, exist_ok=True)
            np.save(os.path.join(odir, "u0.npy"), u0)


if __name__ == "__main__":
    main()
