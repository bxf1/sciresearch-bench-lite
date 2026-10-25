#!/usr/bin/env python3
"""Recover sine-mode initial fields for 1-D heat inverse problems.

The estimator is the posterior mean for a smooth Gaussian coefficient prior.
Prior variances decay as k^-4 (a squared-second-derivative penalty).  The
decay exponent is refined per case by marginal likelihood and posterior
predictions are averaged over a small set of exponents, which guards against
over/under-smoothing without fitting observation noise.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.linalg import cho_factor, cho_solve, LinAlgError


TWO_PI2 = np.pi * np.pi


def solve_case(case_dir, out_file):
    meta = json.loads((case_dir / "metadata.json").read_text())
    try:
        obs = np.genfromtxt(case_dir / "observations.csv", delimiter=",",
                            names=True, dtype=np.float64)
    except Exception:
        obs = np.genfromtxt(case_dir / "observations.csv", delimiter=",",
                            skip_header=1, dtype=np.float64)
        obs = {"x": obs[:, 0], "t": obs[:, 1], "y": obs[:, 2]}
    x = np.atleast_1d(np.asarray(obs["x"], dtype=np.float64))
    t = np.atleast_1d(np.asarray(obs["t"], dtype=np.float64))
    y = np.atleast_1d(np.asarray(obs["y"], dtype=np.float64))

    kappa = float(meta["kappa"])
    sigma = max(abs(float(meta["sigma"])), 1.0e-14)
    K = int(meta.get("mode_limit", 32))
    K = max(1, min(K, 64))
    k = np.arange(1, K + 1, dtype=np.float64)

    # Observation operator: u(x,t) = sum_k a_k exp(-kappa pi^2 k^2 t) sin(pi k x)
    A = np.sin(np.pi * x[:, None] * k[None, :])
    A *= np.exp(-kappa * TWO_PI2 * (k * k)[None, :] * t[:, None])

    AtA = A.T @ A
    Aty = A.T @ y
    yy = float(y @ y)
    n = len(y)
    log_sigma2 = 2.0 * np.log(sigma)

    def posterior(p):
        # Expected squared L2 norm of the field is one.
        v = k ** (-2.0 * p)
        v = v / (0.5 * np.sum(v))
        B = AtA / (sigma * sigma) + np.diag(1.0 / v)
        try:
            cf = cho_factor(B, lower=True, check_finite=False)
        except (LinAlgError, ValueError):
            B = B + np.eye(K) * (1.0e-12 * max(1.0, np.max(np.diag(B))))
            cf = cho_factor(B, lower=True, check_finite=False)
        rhs = Aty / (sigma * sigma)
        co = cho_solve(cf, rhs, check_finite=False)
        # Log marginal likelihood, up to a case-independent constant.
        logdetB = 2.0 * np.sum(np.log(np.diag(cf[0])))
        quad = yy / (sigma * sigma)
        quad -= float(Aty @ cho_solve(cf, Aty, check_finite=False)) / (sigma ** 4)
        ev = -0.5 * (n * log_sigma2 + np.sum(np.log(v)) + logdetB + quad)
        return co, ev

    # Marginal likelihood over a family of smoothness priors.  The weak prior
    # on p keeps the choice near the k^-4 penalty when the data cannot decide.
    ps = np.linspace(1.5, 2.8, 27)
    models = []
    for p in ps:
        co, ev = posterior(float(p))
        if np.isfinite(co).all() and np.isfinite(ev):
            logw = ev - 0.5 * ((p - 2.0) / 0.6) ** 2
            models.append((logw, co))
    if not models:
        co = posterior(2.0)[0]
    else:
        lw = np.array([m[0] for m in models])
        w = np.exp(lw - np.max(lw))
        w /= np.sum(w)
        co = np.zeros(K, dtype=np.float64)
        for wi, (_, ci) in zip(w, models):
            co += wi * ci

    target = np.load(case_dir / "target_grid.npy", allow_pickle=False)
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    u = np.sin(np.pi * target[:, None] * k[None, :]) @ co
    u = np.asarray(u, dtype="<f8").reshape(256)
    u[~np.isfinite(u)] = 0.0
    out_file.parent.mkdir(parents=True, exist_ok=True)
    np.save(out_file, u, allow_pickle=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    np.random.seed(args.seed)  # deterministic; estimator itself needs no RNG

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    manifest = json.loads((input_dir / "manifest.json").read_text())
    for case in manifest["cases"]:
        cid = str(case["id"])
        case_dir = input_dir / str(case["path"])
        solve_case(case_dir, output_dir / "cases" / cid / "u0.npy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
