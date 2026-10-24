#!/usr/bin/env python3
"""Identify compact 2D autonomous polynomial systems (degree <= 3) from noisy trajectories."""
import argparse
import json
import os

import numpy as np
from scipy.integrate import solve_ivp
from scipy.signal import savgol_filter

MAX_TERMS = 10


def basis(Z):
    z1, z2 = Z[:, 0], Z[:, 1]
    return np.stack(
        [
            np.ones_like(z1),
            z1,
            z2,
            z1 * z1,
            z1 * z2,
            z2 * z2,
            z1 ** 3,
            z1 * z1 * z2,
            z1 * z2 * z2,
            z2 ** 3,
        ],
        axis=1,
    )


def stlsq(X, Y, thr, rounds=8):
    C = np.linalg.lstsq(X, Y, rcond=None)[0]
    for _ in range(rounds):
        for j in range(Y.shape[1]):
            m = np.abs(C[:, j]) >= thr
            if m.any():
                C[:, j] = 0.0
                C[m, j] = np.linalg.lstsq(X[:, m], Y[:, j], rcond=None)[0]
            else:
                C[:, j] = 0.0
    return C


def fit_sg(tr, t, win, thr):
    dt = t[1] - t[0]
    S = savgol_filter(tr, win, 3, axis=1, deriv=0)
    D = savgol_filter(tr, win, 3, axis=1, deriv=1, delta=dt)
    h = win // 2
    S = S[:, h:-h, :]
    D = D[:, h:-h, :]
    X = basis(S.reshape(-1, 2))
    Y = D.reshape(-1, 2)
    return stlsq(X, Y, thr)


def rollout_err(C, vi, va, t):
    def f(tt, z):
        return basis(z[None, :])[0] @ C

    errs = []
    for k in range(vi.shape[0]):
        sol = solve_ivp(
            f, (t[0], t[-1]), vi[k], method="DOP853", t_eval=t, rtol=1e-9, atol=1e-11
        )
        if not sol.success or sol.y.shape[1] != len(t):
            return None
        pred = sol.y.T
        errs.append(np.linalg.norm(pred - va[k]) / np.linalg.norm(va[k]))
    return float(np.mean(errs))


def traj_refine(C, tr, t, ti, rounds=6):
    """Least-squares refinement of coefficients against noisy trajectories."""
    def simulate(Cc):
        def f(tt, z):
            return basis(z[None, :])[0] @ Cc

        out = []
        for k in range(ti.shape[0]):
            sol = solve_ivp(
                f, (t[0], t[-1]), ti[k], method="DOP853", t_eval=t, rtol=1e-9, atol=1e-11
            )
            if not sol.success or sol.y.shape[1] != len(t):
                return None
            out.append(sol.y.T)
        return np.stack(out)

    mask = C != 0
    if mask.sum() == 0:
        return C
    Cc = C.copy()
    for _ in range(rounds):
        sim = simulate(Cc)
        if sim is None:
            return C
        # residual r = tr - sim ; linearize: sim ~ sim0 + J*(C-Cc)
        # Build design matrix from simulated states (basis evaluated at sim states)
        A = basis(sim.reshape(-1, 2))
        r = (tr - sim).reshape(-1, 2)
        # only update entries in mask
        cols = np.where(mask.any(axis=1))[0]
        Am = A[:, cols]
        dC = np.zeros_like(Cc)
        dC[cols] = np.linalg.lstsq(Am, r, rcond=None)[0]
        Cc = Cc + dC
        Cc[~mask] = 0.0
    return Cc


def solve_case(path, seed=0):
    tr = np.load(os.path.join(path, "train.npy"))
    va = np.load(os.path.join(path, "validation.npy"))
    t = np.load(os.path.join(path, "t.npy"))
    vi = np.load(os.path.join(path, "validation_initial.npy"))
    ti = np.load(os.path.join(path, "train_initial.npy"))

    best = None
    for win in (11, 21, 31, 41):
        for thr in (0.02, 0.05, 0.1):
            C = fit_sg(tr, t, win, thr)
            C[np.abs(C) < 1e-6] = 0.0
            K = int((C != 0).sum())
            if K == 0 or K > MAX_TERMS:
                continue
            e = rollout_err(C, vi, va, t)
            if e is None:
                continue
            score = e + 1e-4 * K
            if best is None or score < best[0]:
                best = (score, C, e, K)

    if best is None:
        C = fit_sg(tr, t, 31, 0.02)
        C[np.abs(C) < 1e-6] = 0.0
        return C

    _, C, e0, K0 = best

    # optional trajectory-based refinement, keep only if it improves validation
    try:
        Cr = traj_refine(C, tr, t, ti)
        Cr[np.abs(Cr) < 1e-6] = 0.0
        Kr = int((Cr != 0).sum())
        if 0 < Kr <= MAX_TERMS:
            er = rollout_err(Cr, vi, va, t)
            if er is not None and er + 1e-4 * Kr < e0 + 1e-4 * K0:
                C = Cr
    except Exception:
        pass

    return C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--output", default="/output")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    np.random.seed(args.seed)
    manifest = json.load(open(os.path.join(args.input, "manifest.json")))
    cases = manifest["cases"] if isinstance(manifest, dict) else manifest

    for c in cases:
        cid = c["id"]
        rel = c.get("path", cid)
        src = os.path.join(args.input, rel)
        C = solve_case(src, args.seed)
        outdir = os.path.join(args.output, "cases", cid)
        os.makedirs(outdir, exist_ok=True)
        with open(os.path.join(outdir, "model.json"), "w") as f:
            json.dump({"coefficients": C.tolist()}, f)
        print(cid, "K=", int((C != 0).sum()))


if __name__ == "__main__":
    main()
