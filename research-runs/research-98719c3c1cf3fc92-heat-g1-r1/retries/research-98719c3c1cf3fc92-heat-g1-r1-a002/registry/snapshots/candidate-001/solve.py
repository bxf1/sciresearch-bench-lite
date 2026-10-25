#!/usr/bin/env python3
"""Baseline: fixed second-derivative Tikhonov, alpha=1e-5."""
import argparse, json, os
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)
    j = np.arange(1, 257, dtype=np.float64)
    k = np.arange(1, 33, dtype=np.float64)
    S = np.sin(np.pi * np.outer(j, k) / 257.0)
    for entry in manifest["cases"]:
        cdir = os.path.join(args.input, entry["path"])
        with open(os.path.join(cdir, "metadata.json")) as f:
            md = json.load(f)
        obs = np.loadtxt(os.path.join(cdir, "observations.csv"), delimiter=",", skiprows=1, ndmin=2)
        x, t, y = obs[:, 0], obs[:, 1], obs[:, 2]
        A = np.sin(np.pi * np.outer(x, k)) * np.exp(-md["kappa"] * np.pi**2 * np.outer(t, k**2))
        Dinv = 1.0 / k**2
        B = A * Dinv[None, :]
        U, s, Vt = np.linalg.svd(B, full_matrices=False)
        lam = 1e-5 * s[0]**2
        a = Dinv * (Vt.T @ ((s / (s**2 + lam)) * (U.T @ y)))
        u0 = S @ a
        outdir = os.path.join(args.output, "cases", entry["id"])
        os.makedirs(outdir, exist_ok=True)
        np.save(os.path.join(outdir, "u0.npy"), np.ascontiguousarray(u0, dtype="<f8"))

if __name__ == "__main__":
    main()
