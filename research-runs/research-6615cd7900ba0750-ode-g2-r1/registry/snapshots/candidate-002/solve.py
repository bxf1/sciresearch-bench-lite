#!/usr/bin/env python3
"""Identify a 2D autonomous polynomial vector field (degree <= 3) from noisy trajectories."""
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import argparse
import json
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares


def basis(Z):
    z1, z2 = Z[:, 0], Z[:, 1]
    return np.column_stack([
        np.ones_like(z1), z1, z2, z1 * z1, z1 * z2, z2 * z2,
        z1 ** 3, z1 * z1 * z2, z1 * z2 * z2, z2 ** 3,
    ])


def smooth(t, Y, h):
    """Gaussian-weighted local linear fit -> smoothed states and derivatives."""
    n = len(t)
    out = np.zeros_like(Y)
    der = np.zeros_like(Y)
    for i in range(n):
        w = np.exp(-0.5 * ((t - t[i]) / h) ** 2)
        A = np.column_stack([np.ones(n), t - t[i]])
        Aw = A * w[:, None]
        M = Aw.T @ A
        rhs = Aw.T @ Y
        coef = np.linalg.solve(M, rhs)
        out[i] = coef[0]
        der[i] = coef[1]
    return out, der


def fit_field(t, tr, sig, h=0.05):
    """Pooled weighted least squares on smoothed derivatives."""
    Phis, Ds, Ws = [], [], []
    for k in range(tr.shape[0]):
        Xs, dXs = smooth(t, tr[k], h)
        Phis.append(basis(Xs))
        Ds.append(dXs)
        Ws.append(np.full(len(t), 1.0 / np.mean(sig[k]) ** 2))
    Phi = np.vstack(Phis)
    D = np.vstack(Ds)
    W = np.concatenate(Ws)
    C = np.linalg.lstsq(Phi * W[:, None], D * W[:, None], rcond=None)[0]
    return C


def rollout(C, z0, t):
    def f(tt, z):
        return (basis(z[None, :]) @ C)[0]
    sol = solve_ivp(f, (t[0], t[-1]), z0, t_eval=t, method="DOP853",
                    rtol=1e-9, atol=1e-11)
    if sol.y.shape[1] != len(t):
        return None
    return sol.y.T


def refine(C0, t, tr, ti, sig, max_nfev=2000):
    n = tr.shape[0]
    m = len(t)

    def res(p):
        C = p.reshape(10, 2)
        out = []
        for k in range(n):
            R = rollout(C, ti[k], t)
            if R is None:
                out.append(np.full(2 * m, 1e3))
            else:
                out.append(((R - tr[k]) / sig[k]).ravel())
        return np.concatenate(out)

    r = least_squares(res, C0.ravel(), method="trf", loss="soft_l1",
                      f_scale=1.0, max_nfev=max_nfev, xtol=1e-10, ftol=1e-10)
    return r.x.reshape(10, 2)


def solve_case(case_dir):
    tr = np.load(os.path.join(case_dir, "train.npy"))
    t = np.load(os.path.join(case_dir, "t.npy"))
    ti = np.load(os.path.join(case_dir, "train_initial.npy"))
    with open(os.path.join(case_dir, "metadata.json")) as f:
        md = json.load(f)
    sig = np.array(md["noise"]["train_sigma"])

    C0 = fit_field(t, tr, sig)
    C = refine(C0, t, tr, ti, sig)
    # Sparsify: keep only significant terms (K <= 10), then re-refine on the
    # retained support so the remaining coefficients are re-optimized.
    C[np.abs(C) < 1e-2] = 0.0
    C = refine_support(C, t, tr, ti, sig)
    C[np.abs(C) < 1e-6] = 0.0
    return C


def refine_support(C, t, tr, ti, sig, max_nfev=2000):
    """Re-optimize only the nonzero entries of C."""
    mask = C != 0.0
    idx = np.flatnonzero(mask.ravel())
    if idx.size == 0:
        return C
    n = tr.shape[0]
    m = len(t)

    def res(p):
        Cfull = np.zeros(20)
        Cfull[idx] = p
        Cm = Cfull.reshape(10, 2)
        out = []
        for k in range(n):
            R = rollout(Cm, ti[k], t)
            if R is None:
                out.append(np.full(2 * m, 1e3))
            else:
                out.append(((R - tr[k]) / sig[k]).ravel())
        return np.concatenate(out)

    r = least_squares(res, C.ravel()[idx], method="trf", loss="soft_l1",
                      f_scale=1.0, max_nfev=max_nfev, xtol=1e-10, ftol=1e-10)
    Cfull = np.zeros(20)
    Cfull[idx] = r.x
    return Cfull.reshape(10, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)
    cases = manifest["cases"] if isinstance(manifest, dict) else manifest

    for case in cases:
        cid = case["id"] if isinstance(case, dict) else case
        cdir = os.path.join(args.input, "cases", cid)
        C = solve_case(cdir)
        odir = os.path.join(args.output, "cases", cid)
        os.makedirs(odir, exist_ok=True)
        with open(os.path.join(odir, "model.json"), "w") as f:
            json.dump({"coefficients": C.tolist()}, f)


if __name__ == "__main__":
    main()
