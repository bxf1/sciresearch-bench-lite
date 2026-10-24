#!/usr/bin/env python
"""Identify 2D autonomous polynomial (deg<=3) ODE from noisy trajectories."""
import argparse
import json
import os

import numpy as np
from scipy.integrate import solve_ivp
from scipy.signal import savgol_filter

BASIS = [
    lambda z1, z2: np.ones_like(z1),
    lambda z1, z2: z1,
    lambda z1, z2: z2,
    lambda z1, z2: z1 * z1,
    lambda z1, z2: z1 * z2,
    lambda z1, z2: z2 * z2,
    lambda z1, z2: z1 ** 3,
    lambda z1, z2: z1 * z1 * z2,
    lambda z1, z2: z1 * z2 * z2,
    lambda z1, z2: z2 ** 3,
]


def design(z1, z2):
    return np.stack([f(z1, z2) for f in BASIS], axis=-1)


def rhs_factory(C):
    def f(t, z):
        z1, z2 = z[0], z[1]
        return design(np.array(z1), np.array(z2)) @ C
    return f


def smooth_derivs(traj, t, win=31, poly=3):
    """Smooth each channel and return smoothed states + derivatives."""
    n = traj.shape[0]
    w = min(win, n if n % 2 == 1 else n - 1)
    if w < poly + 2:
        w = poly + 2 if (poly + 2) % 2 == 1 else poly + 3
    xs = np.empty_like(traj)
    ds = np.empty_like(traj)
    for c in range(traj.shape[1]):
        xs[:, c] = savgol_filter(traj[:, c], w, poly, deriv=0, mode="interp")
        ds[:, c] = savgol_filter(traj[:, c], w, poly, deriv=1, delta=t[1] - t[0],
                                 mode="interp")
    return xs, ds


def fit_linear(X, Y, ridge=0.0):
    if ridge > 0:
        A = X.T @ X + ridge * np.eye(X.shape[1])
        return np.linalg.solve(A, X.T @ Y)
    return np.linalg.lstsq(X, Y, rcond=None)[0]


def stlsq(X, Y, thresh, max_terms=10, ridge=1e-10):
    """Sequentially thresholded least squares, per output column."""
    n_feat = X.shape[1]
    C = np.zeros((n_feat, Y.shape[1]))
    for j in range(Y.shape[1]):
        y = Y[:, j]
        active = np.ones(n_feat, dtype=bool)
        coef = fit_linear(X, y[:, None], ridge)[:, 0]
        for _ in range(30):
            small = np.abs(coef) < thresh
            new_active = ~small
            if new_active.sum() == 0:
                new_active[np.argmax(np.abs(coef))] = True
            if new_active.sum() > max_terms:
                idx = np.argsort(-np.abs(coef))[:max_terms]
                new_active = np.zeros(n_feat, dtype=bool)
                new_active[idx] = True
            if np.array_equal(new_active, active):
                break
            active = new_active
            coef = np.zeros(n_feat)
            coef[active] = fit_linear(X[:, active], y[:, None], ridge)[:, 0]
        C[:, j] = coef
    return C


def rollout_error(C, z0, t_eval, ref=None):
    f = rhs_factory(C)
    try:
        sol = solve_ivp(f, (t_eval[0], t_eval[-1]), z0, method="DOP853",
                        t_eval=t_eval, rtol=1e-9, atol=1e-11)
    except Exception:
        return np.inf, None
    if not sol.success or sol.y.shape[1] != len(t_eval):
        return np.inf, None
    pred = sol.y.T
    if ref is None:
        return 0.0, pred
    num = np.linalg.norm(pred - ref)
    den = np.linalg.norm(ref)
    return num / max(den, 1e-12), pred


def field_error(C, lo=-1.5, hi=1.5, n=21):
    g = np.linspace(lo, hi, n)
    Z1, Z2 = np.meshgrid(g, g, indexing="ij")
    z1 = Z1.ravel()
    z2 = Z2.ravel()
    V = design(z1, z2) @ C
    return V


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    np.random.seed(args.seed)
    manifest = json.load(open(os.path.join(args.input, "manifest.json")))

    for case in manifest["cases"]:
        cid = case["id"]
        cdir = os.path.join(args.input, case["path"])
        odir = os.path.join(args.output, "cases", cid)
        os.makedirs(odir, exist_ok=True)

        train = np.load(os.path.join(cdir, "train.npy"))  # (n_traj, n_t, 2)
        t = np.load(os.path.join(cdir, "t.npy"))
        z0s = np.load(os.path.join(cdir, "train_initial.npy"))
        meta = json.load(open(os.path.join(cdir, "metadata.json")))
        sig = np.array(meta["noise"]["train_sigma"])  # (n_traj, 2)

        n_traj, n_t, _ = train.shape

        # Build regression data from smoothed derivatives.
        Xs, Ys = [], []
        for i in range(n_traj):
            xs, ds = smooth_derivs(train[i], t, win=41, poly=3)
            Xs.append(design(xs[:, 0], xs[:, 1]))
            Ys.append(ds)
        X = np.concatenate(Xs, axis=0)
        Y = np.concatenate(Ys, axis=0)

        # Normalize columns for conditioning.
        scale = np.sqrt((X ** 2).mean(axis=0))
        scale[scale < 1e-12] = 1.0
        Xn = X / scale

        best = None
        for thresh in [1e-3, 3e-3, 1e-2, 3e-2, 1e-1]:
            C = stlsq(Xn, Y, thresh, max_terms=10)
            C = C / scale[:, None]
            C[np.abs(C) < 1e-6] = 0.0
            # evaluate on training trajectories
            errs = []
            for i in range(n_traj):
                e, _ = rollout_error(C, z0s[i], t, train[i])
                errs.append(e)
            score = float(np.mean(errs))
            if best is None or score < best[0]:
                best = (score, C, thresh)
        C = best[1]

        # Refine: nonlinear least squares on rollout error (light polish).
        C = polish(C, z0s, t, train, n_traj)

        C[np.abs(C) < 1e-6] = 0.0
        if np.count_nonzero(C) > 10:
            # keep 10 largest magnitude entries
            flat = np.abs(C).ravel()
            keep = np.argsort(-flat)[:10]
            mask = np.zeros_like(flat, dtype=bool)
            mask[keep] = True
            C = np.where(mask.reshape(C.shape), C, 0.0)

        with open(os.path.join(odir, "model.json"), "w") as fh:
            json.dump({"coefficients": C.tolist()}, fh)


def polish(C, z0s, t, train, n_traj, iters=30):
    from scipy.optimize import least_squares

    mask = np.abs(C) > 0
    if mask.sum() == 0:
        return C
    idx = np.where(mask.ravel())[0]
    x0 = C.ravel()[idx]

    def resid(p):
        Cc = np.zeros(C.size)
        Cc[idx] = p
        Cc = Cc.reshape(C.shape)
        out = []
        for i in range(n_traj):
            e, pred = rollout_error(Cc, z0s[i], t, train[i])
            if pred is None:
                return np.full(10 * n_traj, 1e3)
            out.append((pred - train[i]).ravel())
        return np.concatenate(out)

    try:
        res = least_squares(resid, x0, method="lm", xtol=1e-12, ftol=1e-12,
                            max_nfev=200)
        Cc = np.zeros(C.size)
        Cc[idx] = res.x
        Cc = Cc.reshape(C.shape)
        if np.all(np.isfinite(Cc)):
            return Cc
    except Exception:
        pass
    return C


if __name__ == "__main__":
    main()
