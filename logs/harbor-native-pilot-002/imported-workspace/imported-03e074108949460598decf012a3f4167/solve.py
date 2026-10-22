import argparse
import json
import os

import numpy as np
from scipy.stats import chi2


def solve_case(case_dir, out_dir):
    meta_path = os.path.join(case_dir, "metadata.json")
    obs_path = os.path.join(case_dir, "observations.csv")
    with open(meta_path) as f:
        meta = json.load(f)
    kappa = float(meta["kappa"])
    sigma = float(meta["sigma"])
    mode_limit = int(meta.get("mode_limit", 32))

    data = np.loadtxt(obs_path, delimiter=",", skiprows=1)
    x = data[:, 0]
    t = data[:, 1]
    y = data[:, 2]

    m = x.shape[0]
    K = mode_limit
    k = np.arange(1, K + 1, dtype=float)

    # Forward matrix A_ik = sin(pi*k*x_i) * exp(-kappa*pi^2*k^2*t_i)
    A = np.sin(np.pi * np.outer(x, k)) * np.exp(
        -kappa * np.pi ** 2 * np.outer(t, k ** 2)
    )

    # D = diag(k^2); solve via SVD of A * D^-1
    Dinv = 1.0 / (k ** 2)
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
    best_res = np.inf
    for alpha in alpha_grid:
        a = estimate(alpha)
        res = np.sum((A @ a - y) ** 2)
        if res <= delta2:
            best_alpha = alpha
            best_res = res
        else:
            # grid is increasing alpha; once we exceed bound, larger alpha
            # only increases residual, so stop
            break

    if best_alpha is not None:
        a = estimate(best_alpha)
    else:
        # fallback: OLS on first five modes, zero the rest
        a = np.zeros(K)
        A5 = A[:, :5]
        a5, *_ = np.linalg.lstsq(A5, y, rcond=None)
        a[:5] = a5

    # Evaluate on target grid x_j = j/257, j=1..256
    xg = np.arange(1, 257) / 257.0
    S = np.sin(np.pi * np.outer(xg, k))
    u0 = S @ a

    out_path = os.path.join(out_dir, "u0.npy")
    np.save(out_path, u0.astype(np.float64))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    manifest_path = os.path.join(args.input, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    for case in manifest["cases"]:
        case_id = case["id"]
        case_dir = os.path.join(args.input, case["path"])
        out_dir = os.path.join(args.output, "cases", case_id)
        os.makedirs(out_dir, exist_ok=True)
        solve_case(case_dir, out_dir)


if __name__ == "__main__":
    main()
