#!/usr/bin/env python3
"""Heat inverse-problem solver.

Recovers the initial temperature field u0(x) on 0<x<1 from noisy point
observations of the solution of  u_t = kappa*u_xx  with zero Dirichlet
boundary conditions.  The true initial field lies in the first 32 sine
modes, so we estimate the 32 sine coefficients by weighted Tikhonov
regularisation as described in the task guidance.

Output: for every case <id>, /output/cases/<id>/u0.npy (float64, shape
(256,)) sampled at x_j = j/257, j=1..256.
"""

import argparse
import csv
import json
import os

import numpy as np

N_MODES = 32
TARGET_SIZE = 256


def solve_case(case_dir, method="fixed"):
    """Return the reconstructed u0 grid for one case."""
    with open(os.path.join(case_dir, "metadata.json"), "r") as f:
        meta = json.load(f)
    kappa = float(meta["kappa"])
    sigma = float(meta["sigma"])

    xs = []
    ts = []
    ys = []
    with open(os.path.join(case_dir, "observations.csv"), "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            xs.append(float(row["x"]))
            ts.append(float(row["t"]))
            ys.append(float(row["y"]))
    x = np.asarray(xs, dtype=np.float64)
    t = np.asarray(ts, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)

    m = x.size
    ks = np.arange(1, N_MODES + 1, dtype=np.float64)

    # A_ik = sin(pi*k*x_i) * exp(-kappa*pi^2*k^2*t_i)
    A = np.sin(np.pi * x[:, None] * ks[None, :]) * np.exp(
        -kappa * np.pi ** 2 * (ks ** 2)[None, :] * t[:, None]
    )

    # D = diag(k^2); solve weighted Tikhonov in c = D*a.
    D = ks ** 2
    M = A / D[None, :]  # A * D^-1
    U, s, Vt = np.linalg.svd(M, full_matrices=False)

    if method == "fixed":
        alpha = 1e-5
        lam = alpha * s[0] ** 2
        c = (Vt.T * (s / (s ** 2 + lam))[None, :]) @ (U.T @ y)
    elif method == "grid":
        # alpha grid selection using the public residual-square bound.
        from scipy import stats as _stats
        alphas = np.logspace(-10, 0, 81)
        delta2 = sigma ** 2 * _stats.chi2.ppf(0.99, m)
        smax2 = s[0] ** 2
        Uty = U.T @ y
        chosen = None
        min_res = np.inf
        for alpha in alphas:
            lam = alpha * smax2
            c = (Vt.T * (s / (s ** 2 + lam))[None, :]) @ Uty
            a = c / D
            r = A @ a - y
            res = float(r @ r)
            if res < min_res:
                min_res = res
            if res <= delta2:
                chosen = (alpha, c)
        if chosen is not None:
            c = chosen[1]
        else:
            # Fallback: OLS on the first five sine modes only.
            A5 = A[:, :5]
            a5, *_ = np.linalg.lstsq(A5, y, rcond=None)
            c = np.zeros(N_MODES)
            c[:5] = a5 * D[:5]
    else:
        raise ValueError("unknown method")

    a = c / D
    xgrid = np.arange(1, TARGET_SIZE + 1, dtype=np.float64) / (TARGET_SIZE + 1)
    u0 = np.sin(np.pi * xgrid[:, None] * ks[None, :]) @ a
    return u0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    with open(os.path.join(args.input, "manifest.json"), "r") as f:
        manifest = json.load(f)

    for case in manifest["cases"]:
        case_id = case["id"]
        case_dir = os.path.join(args.input, case["path"])
        u0 = solve_case(case_dir, method="fixed")
        out_dir = os.path.join(args.output, "cases", case_id)
        os.makedirs(out_dir, exist_ok=True)
        np.save(os.path.join(out_dir, "u0.npy"), u0.astype(np.float64))


if __name__ == "__main__":
    main()
