#!/usr/bin/env python3
"""Identify autonomous 2-D cubic polynomial vector fields from noisy trajectories."""
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import sys
import json
import argparse
import itertools
import numpy as np
from scipy.signal import savgol_filter
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares


# ----------------------------------------------------------------------------
# Polynomial dictionary (same ordering as the task statement)
# ----------------------------------------------------------------------------
def basis(Z):
    Z = np.atleast_2d(Z)
    z1 = Z[:, 0]
    z2 = Z[:, 1]
    return np.column_stack([
        np.ones_like(z1), z1, z2, z1 * z1, z1 * z2, z2 * z2,
        z1 ** 3, z1 * z1 * z2, z1 * z2 * z2, z2 ** 3,
    ])


def dbasis(z):
    z1, z2 = z[0], z[1]
    d1 = np.array([0.0, 1.0, 0.0, 2.0 * z1, z2, 0.0,
                   3.0 * z1 * z1, 2.0 * z1 * z2, z2 * z2, 0.0])
    d2 = np.array([0.0, 0.0, 1.0, 0.0, z1, 2.0 * z2,
                   0.0, z1 * z1, 2.0 * z1 * z2, 3.0 * z2 * z2])
    return d1, d2


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def load_case(cdir):
    t = np.load(os.path.join(cdir, "t.npy")).astype(float)
    with open(os.path.join(cdir, "metadata.json")) as f:
        meta = json.load(f)
    data = []
    for nm, im in (("train", "train_initial"), ("validation", "validation_initial")):
        zp = os.path.join(cdir, nm + ".npy")
        ip = os.path.join(cdir, im + ".npy")
        if not os.path.exists(zp):
            continue
        Z = np.load(zp).astype(float)
        I = np.load(ip).astype(float)
        sig = np.asarray(meta.get("noise", {}).get(nm + "_sigma", []), dtype=float)
        for k in range(Z.shape[0]):
            if sig.ndim == 2 and sig.shape[0] > 0:
                s = sig[k % sig.shape[0]].astype(float)
            elif sig.ndim == 1 and sig.size >= 2:
                s = sig.astype(float)
            else:
                # conservative fallback: 1% of the channel rms
                s = 0.01 * np.sqrt(np.mean(Z[k] ** 2, axis=0))
            s = np.maximum(s, 1e-12)
            data.append((Z[k], I[k], s))
    return t, data, meta


# ----------------------------------------------------------------------------
# Savitzky-Golay derivative regression
# ----------------------------------------------------------------------------
def weak_xy(t, data, win, poly=3):
    X, Y = [], []
    dt = float(t[1] - t[0])
    h = win // 2
    for Z, _z0, _s in data:
        Zs = savgol_filter(Z, win, poly, axis=0, mode="interp")
        D = savgol_filter(Z, win, poly, deriv=1, delta=dt, axis=0, mode="interp")
        X.append(basis(Zs[h:-h]))
        Y.append(D[h:-h])
    return np.vstack(X), np.vstack(Y)


def weak_stlsq(t, data, win=31, poly=3, thr=0.02, rounds=8):
    X, Y = weak_xy(t, data, win, poly)
    C = np.linalg.lstsq(X, Y, rcond=None)[0]
    for _ in range(rounds):
        for j in range(2):
            keep = np.abs(C[:, j]) >= thr
            if keep.sum() == 0:
                C[:, j] = 0.0
            else:
                C[keep, j] = np.linalg.lstsq(X[:, keep], Y[:, j], rcond=None)[0]
                C[~keep, j] = 0.0
    return C


# ----------------------------------------------------------------------------
# Exhaustive subset BIC on the derivative regression
# ----------------------------------------------------------------------------
def subset_stats(X, Y):
    n, p = X.shape
    G = X.T @ X
    b = X.T @ Y
    yty = np.sum(Y * Y, axis=0)
    masks = np.array(list(itertools.product([0, 1], repeat=p)), dtype=bool)
    ns = len(masks)
    rss = np.zeros((ns, 2))
    sols = np.zeros((ns, p, 2))
    for i, m in enumerate(masks):
        k = int(m.sum())
        if k == 0:
            rss[i] = yty
            continue
        try:
            beta = np.linalg.solve(G[np.ix_(m, m)], b[m])
        except np.linalg.LinAlgError:
            try:
                beta = np.linalg.lstsq(G[np.ix_(m, m)], b[m], rcond=None)[0]
            except np.linalg.LinAlgError:
                rss[i] = 1e30
                continue
        r = yty - 2.0 * np.sum(beta * b[m], axis=0) \
            + np.sum(beta * (G[np.ix_(m, m)] @ beta), axis=0)
        rss[i] = np.maximum(r, 1e-30)
        sols[i, m] = beta
    full = np.all(masks, axis=1)
    sig2 = np.maximum(rss[full][0] / max(n - p, 1), 1e-30)
    return masks, rss, sols, sig2, n


def bic_support(t, data, win=31, penalty_factor=1.0, maxk=10):
    X, Y = weak_xy(t, data, win)
    masks, rss, sols, sig2, n = subset_stats(X, Y)
    ks = masks.sum(axis=1)
    bic = rss / sig2[None, :] + ks[:, None] * (penalty_factor * np.log(n))
    best_by_k = {}
    for kk in range(min(maxk, X.shape[1]) + 1):
        idx = np.flatnonzero(ks == kk)
        if idx.size:
            best_by_k[kk] = (idx[np.argmin(bic[idx, 0])],
                             idx[np.argmin(bic[idx, 1])])
    best = None
    for k1, (i1, _) in best_by_k.items():
        for k2, (_, i2) in best_by_k.items():
            if k1 + k2 > maxk:
                continue
            val = bic[i1, 0] + bic[i2, 1]
            if best is None or val < best[0]:
                best = (val, i1, i2)
    _, i1, i2 = best
    S = np.column_stack([masks[i1], masks[i2]])
    C = np.column_stack([sols[i1, :, 0], sols[i2, :, 1]])
    return S, C


def significance_support(t, data, win=31, base_thr=0.02, z=3.0):
    X, Y = weak_xy(t, data, win)
    n, p = X.shape
    beta, _res, rank, _sv = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    sig2 = np.sum(resid ** 2, axis=0) / max(n - p, 1)
    cov = np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(cov)[:, None] * sig2[None, :], 1e-30))
    S = (np.abs(beta) >= base_thr) | (np.abs(beta) >= z * se)
    return S, beta


# ----------------------------------------------------------------------------
# Nonlinear output-error fit with sensitivity equations
# ----------------------------------------------------------------------------
class SimCache:
    __slots__ = ("t", "data", "rtol", "atol", "key", "out")

    def __init__(self, t, data, rtol, atol):
        self.t = t
        self.data = data
        self.rtol = rtol
        self.atol = atol
        self.key = None
        self.out = None

    def _sim(self, C, z0):
        t = self.t
        n = t.size

        def f(_tt, y):
            z = y[:2]
            S = y[2:].reshape(2, 20)
            th = basis(z)[0]
            d1, d2 = dbasis(z)
            fs = th @ C
            a = np.array([[C[:, 0] @ d1, C[:, 0] @ d2],
                          [C[:, 1] @ d1, C[:, 1] @ d2]])
            F = np.zeros((2, 20))
            F[0, 0:10] = th
            F[1, 10:20] = th
            return np.concatenate([fs, (a @ S + F).ravel()])

        y0 = np.concatenate([z0, np.zeros(40)])
        sol = solve_ivp(f, (t[0], t[-1]), y0, t_eval=t, method="DOP853",
                        rtol=self.rtol, atol=self.atol)
        if (not sol.success) or sol.y.shape[1] != n:
            raise RuntimeError("integration failed")
        Y = sol.y[:2].T
        S = sol.y[2:].T.reshape(n, 2, 20)
        if not np.all(np.isfinite(Y)) or not np.all(np.isfinite(S)):
            raise RuntimeError("nonfinite")
        return Y, S

    def eval(self, C):
        key = tuple(np.asarray(C, dtype=float).ravel())
        if self.key == key:
            return self.out
        out = []
        for Z, z0, sig in self.data:
            Y, S = self._sim(C, z0)
            out.append((Z, sig, Y, S))
        self.key = key
        self.out = out
        return out


def nls_fit(t, data, C0, mask, rtol=1e-7, atol=1e-10, max_nfev=80):
    mask = np.asarray(mask, dtype=bool).ravel()
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return np.zeros((10, 2)), 0.0, True
    cache = SimCache(t, data, rtol, atol)

    def unpack(p):
        c = np.zeros(20)
        c[idx] = p
        return c.reshape(10, 2)

    def fun(p):
        C = unpack(p)
        out = cache.eval(C)
        r = [((Y - Z) / sig).ravel() for Z, sig, Y, _S in out]
        return np.concatenate(r)

    def jac(p):
        C = unpack(p)
        out = cache.eval(C)
        cols = []
        for _Z, sig, _Y, S in out:
            inv = 1.0 / sig
            blocks = [(S[:, :, l] * inv[None, :]).ravel() for l in idx]
            cols.append(np.column_stack(blocks))
        return np.vstack(cols)

    p0 = np.asarray(C0, dtype=float).ravel()[idx]
    try:
        res = least_squares(fun, p0, jac=jac, method="trf", x_scale="jac",
                            ftol=1e-10, xtol=1e-10, gtol=1e-10,
                            max_nfev=max_nfev)
        C = unpack(res.x)
        if not np.all(np.isfinite(C)):
            return C0.copy(), np.inf, False
        chi2 = float(np.sum(fun(res.x) ** 2))
        return C, chi2, True
    except Exception:
        return C0.copy(), np.inf, False


# ----------------------------------------------------------------------------
# Rollout / validation
# ----------------------------------------------------------------------------
def rollout(C, z0, t, rtol=1e-9, atol=1e-11):
    def f(_tt, y):
        return basis(y)[0] @ C

    sol = solve_ivp(f, (t[0], t[-1]), z0, t_eval=t, method="DOP853",
                    rtol=rtol, atol=atol)
    if (not sol.success) or sol.y.shape[1] != t.size:
        raise RuntimeError("rollout failed")
    Y = sol.y.T
    if not np.all(np.isfinite(Y)):
        raise RuntimeError("nonfinite rollout")
    return Y


def validation_mean(C, t, data):
    """Mean relative Frobenius error on held-out (validation) trajectories."""
    errs = []
    for k, (Z, z0, _sig) in enumerate(data):
        # public validation trajectories are the last two in our data list;
        # for generality use every trajectory tagged as validation by caller.
        pass
    return errs


def candidate_errors(C, t, val_data):
    errs = []
    for Z, z0, _sig in val_data:
        try:
            Y = rollout(C, z0, t)
            e = np.linalg.norm(Y - Z) / max(np.linalg.norm(Z), 1e-30)
            if not np.isfinite(e):
                return None
            errs.append(float(e))
        except Exception:
            return None
    return errs


# ----------------------------------------------------------------------------
# Per-case solver
# ----------------------------------------------------------------------------
def solve_case(cdir):
    t, data, meta = load_case(cdir)
    if len(data) == 0:
        return np.zeros((10, 2))
    # validation entries are the ones after the train entries
    ntrain = 0
    zp = os.path.join(cdir, "train.npy")
    if os.path.exists(zp):
        ntrain = np.load(zp).shape[0]
    val_data = data[ntrain:]
    if len(val_data) == 0:
        val_data = data[-min(2, len(data)):]

    Cw = weak_stlsq(t, data, 31, 3, 0.02, 8)
    Cw_small = weak_stlsq(t, data, 31, 3, 0.005, 8)
    S_sig, beta_full = significance_support(t, data, 31, 0.02, 3.0)

    supports = []
    supports.append(np.abs(Cw) >= 1e-6)
    supports.append(np.abs(Cw_small) >= 1e-6)
    supports.append(S_sig)
    for pf in (0.75, 1.5):
        S_b, _C_b = bic_support(t, data, 31, pf, 10)
        supports.append(S_b)

    # rank reference for capping K
    Cref = beta_full

    uniq = []
    seen = set()
    for S in supports:
        S = np.asarray(S, dtype=bool).copy()
        flat = S.ravel()
        idx = np.flatnonzero(flat)
        if idx.size > 10:
            vals = np.abs(Cref.ravel()[idx])
            drop = idx[np.argsort(vals)[:idx.size - 10]]
            flat[drop] = False
        S = flat.reshape(10, 2)
        key = (tuple(np.flatnonzero(S[:, 0])), tuple(np.flatnonzero(S[:, 1])))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(S)

    nobs = max(len(data) * t.size * 2, 1)
    penal = np.log(nobs)

    results = []
    for S in uniq:
        if S.sum() == 0:
            continue
        C0 = Cw * S
        Cn, chi2, ok = nls_fit(t, data, C0, S, rtol=2e-7, atol=1e-10,
                               max_nfev=60)
        if not ok or not np.isfinite(chi2):
            continue
        Cn = np.where(np.abs(Cn) < 1e-6, 0.0, Cn)
        K = int(np.sum(Cn != 0.0))
        if K > 10:
            continue
        verrs = candidate_errors(Cn, t, val_data)
        if verrs is None:
            continue
        bic = chi2 + K * penal
        results.append((bic, float(np.mean(verrs)), K, Cn, S))

    if not results:
        C = np.where(np.abs(Cw) < 1e-6, 0.0, Cw)
        return C

    results.sort(key=lambda r: (r[0], r[1]))
    best_bic = results[0][0]
    # keep models with essentially the same BIC support, then favour the one
    # with the smallest public-validation error.
    tol = max(2.0, 0.02 * abs(best_bic))
    pool = [r for r in results if r[0] <= best_bic + tol]
    pool.sort(key=lambda r: (r[1] + 1e-4 * r[2], r[0]))
    _, _, _, Csel, Ssel = pool[0]

    # final, tighter fit on the selected support
    Cf, chi2f, okf = nls_fit(t, data, Csel, Ssel, rtol=1e-8, atol=1e-11,
                             max_nfev=80)
    if okf and np.all(np.isfinite(Cf)):
        Cf = np.where(np.abs(Cf) < 1e-6, 0.0, Cf)
        if int(np.sum(Cf != 0.0)) <= 10:
            Csel = Cf
    Csel = np.where(np.abs(Csel) < 1e-6, 0.0, Csel)

    # last-resort validity check; fall back to the weak fit if necessary
    if candidate_errors(Csel, t, val_data) is None:
        Cw2 = np.where(np.abs(Cw) < 1e-6, 0.0, Cw)
        if candidate_errors(Cw2, t, val_data) is not None:
            Csel = Cw2

    # enforce the coefficient-count constraint
    flat = Csel.ravel().copy()
    nz = np.flatnonzero(flat != 0.0)
    if nz.size > 10:
        order = nz[np.argsort(np.abs(flat[nz]))]
        flat[order[:nz.size - 10]] = 0.0
        Csel = flat.reshape(10, 2)
    return Csel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)

    for case in manifest["cases"]:
        cid = case["id"]
        cdir = os.path.join(args.input, case["path"])
        C = solve_case(cdir)
        C = np.asarray(C, dtype=float)
        C[~np.isfinite(C)] = 0.0
        odir = os.path.join(args.output, "cases", cid)
        os.makedirs(odir, exist_ok=True)
        with open(os.path.join(odir, "model.json"), "w") as f:
            json.dump({"coefficients": C.tolist()}, f, allow_nan=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
