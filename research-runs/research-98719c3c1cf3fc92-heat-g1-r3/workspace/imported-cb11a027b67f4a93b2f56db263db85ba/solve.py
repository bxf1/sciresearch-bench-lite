import argparse
import json
from pathlib import Path

import numpy as np


def load_case(case_dir):
    meta = json.loads((case_dir / "metadata.json").read_text())
    obs = np.loadtxt(case_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    x = np.asarray(obs[:, 0], dtype=np.float64)
    t = np.asarray(obs[:, 1], dtype=np.float64)
    y = np.asarray(obs[:, 2], dtype=np.float64)
    return meta, x, t, y


def estimate(case_dir):
    meta, x, t, y = load_case(case_dir)
    kappa = float(meta["kappa"])
    n_modes = 32
    k = np.arange(1, n_modes + 1, dtype=np.float64)

    # Forward map from initial sine coefficients to all observations.
    A = np.sin(np.pi * np.outer(x, k)) * np.exp(
        -kappa * np.pi**2 * np.outer(t, k * k)
    )
    D = k * k
    # Whiten the very different sensitivities of the sine modes.
    B = A / D
    U, s, Vt = np.linalg.svd(B, full_matrices=False)
    q = U.T @ y
    m = float(len(y))
    s2 = s * s

    # Generalized cross-validation over the normalized ridge parameter.
    # The penalty ||D a||^2 is the public second-derivative choice.
    alphas = np.logspace(-10.0, 0.0, 81)
    best_alpha = alphas[0]
    best_gcv = np.inf
    for alpha in alphas:
        lam = alpha * s2[0]
        shrink = s2 / (s2 + lam)
        residual = y - U @ (shrink * q)
        rss = float(residual @ residual)
        trace_h = float(np.sum(shrink))
        denom = m - trace_h
        if denom <= 0.0:
            gcv = np.inf
        else:
            gcv = rss / (denom * denom)
        if gcv < best_gcv:
            best_gcv = gcv
            best_alpha = alpha

    lam = best_alpha * s2[0]
    b = Vt.T @ ((s / (s2 + lam)) * q)
    a = b / D

    grid = np.load(case_dir / "target_grid.npy").astype(np.float64, copy=False)
    u = np.sin(np.pi * np.outer(grid, k)) @ a
    return np.asarray(u, dtype="<f8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    manifest = json.loads((input_dir / "manifest.json").read_text())

    for case in manifest["cases"]:
        case_id = case["id"]
        case_dir = input_dir / case["path"]
        u = estimate(case_dir)
        out_dir = output_dir / "cases" / case_id
        out_dir.mkdir(parents=True, exist_ok=True)
        np.save(out_dir / "u0.npy", u)


if __name__ == "__main__":
    main()
