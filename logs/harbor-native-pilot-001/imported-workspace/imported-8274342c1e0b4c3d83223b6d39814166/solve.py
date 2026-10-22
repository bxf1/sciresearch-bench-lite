import argparse
import json
import os

import numpy as np
from scipy.stats import chi2

MODE_LIMIT = 32
TARGET_SIZE = 256


def build_forward_matrix(xs, ts, kappa, k_modes):
    """A_ik = sin(pi*k*x_i) * exp(-kappa*pi^2*k^2*t_i)."""
    m = len(xs)
    A = np.empty((m, k_modes))
    k = np.arange(1, k_modes + 1, dtype=np.float64)
    for j in range(k_modes):
        kj = k[j]
        A[:, j] = np.sin(np.pi * kj * xs) * np.exp(-kappa * np.pi**2 * kj**2 * ts)
    return A


def solve_case(case_dir):
    with open(os.path.join(case_dir, "metadata.json")) as f:
        meta = json.load(f)
    kappa = float(meta["kappa"])
    sigma = float(meta["sigma"])

    obs = np.loadtxt(os.path.join(case_dir, "observations.csv"),
                     delimiter=",", skiprows=1)
    xs = obs[:, 0]
    ts = obs[:, 1]
    y = obs[:, 2]
    m = len(y)

    A = build_forward_matrix(xs, ts, kappa, MODE_LIMIT)

    # D = diag(k^2)
    k = np.arange(1, MODE_LIMIT + 1, dtype=np.float64)
    D = k ** 2
    Dinv = 1.0 / D

    # A * D^-1 = U diag(s) V^T
    ADinv = A * Dinv[None, :]
    U, s, Vt = np.linalg.svd(ADinv, full_matrices=False)

    def estimate(alpha):
        lam = alpha * s[0] ** 2
        filt = s / (s ** 2 + lam)
        a = Dinv * (Vt.T @ (filt * (U.T @ y)))
        return a

    # Fixed public choice alpha = 1e-5
    a_fixed = estimate(1e-5)

    # Noise-based grid selection
    alpha_grid = np.logspace(-10, 0, 81)
    delta2 = sigma ** 2 * chi2.ppf(0.99, m)

    best_alpha = None
    min_resid = np.inf
    for alpha in alpha_grid:
        a = estimate(alpha)
        resid = np.linalg.norm(A @ a - y) ** 2
        if resid < min_resid:
            min_resid = resid
        if resid <= delta2:
            best_alpha = alpha  # keep largest accepted (grid ascending)

    if best_alpha is not None:
        a = estimate(best_alpha)
        fallback = False
    else:
        # five-mode OLS fallback
        A5 = A[:, :5]
        a5, *_ = np.linalg.lstsq(A5, y, rcond=None)
        a = np.zeros(MODE_LIMIT)
        a[:5] = a5
        fallback = True

    # Evaluate on target grid x_j = j/257
    xg = np.arange(1, TARGET_SIZE + 1, dtype=np.float64) / (TARGET_SIZE + 1)
    S = np.sin(np.pi * k[None, :] * xg[:, None])  # (256, 32)
    u0 = S @ a

    return u0, fallback, min_resid, delta2, best_alpha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)

    for case in manifest["cases"]:
        case_id = case["id"]
        case_dir = os.path.join(args.input, case["path"])
        u0, fallback, min_resid, delta2, best_alpha = solve_case(case_dir)

        out_dir = os.path.join(args.output, "cases", case_id)
        os.makedirs(out_dir, exist_ok=True)
        np.save(os.path.join(out_dir, "u0.npy"), u0.astype(np.float64))


if __name__ == "__main__":
    main()
