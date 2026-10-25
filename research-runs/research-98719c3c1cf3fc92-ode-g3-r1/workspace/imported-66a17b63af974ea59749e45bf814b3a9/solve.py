#!/usr/bin/env python3
"""Identify a sparse degree-three planar polynomial ODE from noisy trajectories."""
from __future__ import annotations

import os
# Keep numerical libraries single-threaded.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import UnivariateSpline
from scipy.optimize import least_squares
from scipy.signal import savgol_filter

ZERO = 1.0e-6
MAX_K = 10


def basis(z: np.ndarray) -> np.ndarray:
    z = np.asarray(z, dtype=float)
    z1 = z[..., 0]
    z2 = z[..., 1]
    return np.stack(
        [np.ones_like(z1), z1, z2, z1 * z1, z1 * z2, z2 * z2,
         z1 ** 3, z1 * z1 * z2, z1 * z2 * z2, z2 ** 3],
        axis=-1,
    )



def basis_derivs(z: np.ndarray):
    z = np.asarray(z, dtype=float)
    z1 = z[..., 0]
    z2 = z[..., 1]
    one = np.ones_like(z1)
    zero = np.zeros_like(z1)
    d1 = np.stack([zero, one, zero, 2.0 * z1, z2, zero,
                   3.0 * z1 * z1, 2.0 * z1 * z2, z2 * z2, zero], axis=-1)
    d2 = np.stack([zero, zero, one, zero, z1, 2.0 * z2,
                   zero, z1 * z1, 2.0 * z1 * z2, 3.0 * z2 * z2], axis=-1)
    return d1, d2

def rhs_from_coef(coef: np.ndarray):
    def rhs(_t, u):
        uu = np.asarray(u, dtype=float).reshape(-1, 2)
        return (basis(uu) @ coef).ravel()
    return rhs


def simulate(coef: np.ndarray, u0: np.ndarray, t: np.ndarray,
             rtol: float = 1e-8, atol: float = 1e-10) -> np.ndarray:
    u0 = np.asarray(u0, dtype=float)
    sol = solve_ivp(
        rhs_from_coef(coef), (float(t[0]), float(t[-1])), u0.ravel(),
        method="DOP853", rtol=rtol, atol=atol, t_eval=t,
    )
    if (not sol.success) or sol.y.shape[1] != len(t) or not np.all(np.isfinite(sol.y)):
        raise RuntimeError("integration failed")
    return sol.y.T.reshape(len(t), -1, 2).transpose(1, 0, 2)



def simulate_fast(coef: np.ndarray, u0: np.ndarray, t: np.ndarray,
                  substeps: int = 4) -> np.ndarray:
    """Fixed-step RK4 for optimization; bounded cost even for bad trial fields."""
    u0 = np.asarray(u0, dtype=float)
    t = np.asarray(t, dtype=float)
    nt = len(t)
    if nt < 2:
        raise RuntimeError("time grid too short")
    dt = float(t[1] - t[0])
    if dt <= 0.0 or not np.allclose(np.diff(t), dt, rtol=1e-9, atol=1e-12):
        return simulate(coef, u0, t)
    substeps = max(1, int(substeps))
    h = dt / substeps
    nsteps = (nt - 1) * substeps
    ntraj = u0.shape[0]
    u = u0.copy()
    out = np.empty((nt, ntraj, 2), dtype=float)
    out[0] = u

    def f(uu):
        return basis(uu) @ coef

    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        for step in range(1, nsteps + 1):
            k1 = f(u)
            k2 = f(u + (0.5 * h) * k1)
            k3 = f(u + (0.5 * h) * k2)
            k4 = f(u + h * k3)
            u = u + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
            if (not np.all(np.isfinite(u))) or np.max(np.abs(u)) > 1.0e10:
                raise RuntimeError("trial trajectory diverged")
            if step % substeps == 0:
                out[step // substeps] = u
    return out.transpose(1, 0, 2)


def simulate_sens(coef: np.ndarray, u0: np.ndarray, t: np.ndarray,
                  mask: np.ndarray, substeps: int = 2):
    """State and forward parameter sensitivities for a selected support."""
    u0 = np.asarray(u0, dtype=float)
    t = np.asarray(t, dtype=float)
    mask = np.asarray(mask, bool)
    nt = len(t)
    dt = float(t[1] - t[0])
    if dt <= 0.0 or not np.allclose(np.diff(t), dt, rtol=1e-9, atol=1e-12):
        raise RuntimeError("nonuniform time grid")
    substeps = max(1, int(substeps))
    h = dt / substeps
    nsteps = (nt - 1) * substeps
    ntraj = u0.shape[0]
    qidx = np.argwhere(mask)
    kparam = len(qidx)
    lq = qidx[:, 0]
    iq = qidx[:, 1]
    colq = np.arange(kparam)
    u = u0.copy()
    S = np.zeros((ntraj, 2, kparam), dtype=float)
    out_u = np.empty((nt, ntraj, 2), dtype=float)
    out_s = np.empty((nt, ntraj, 2, kparam), dtype=float)
    out_u[0] = u
    out_s[0] = S

    def deriv(uu, ss):
        ps = basis(uu)
        fu = ps @ coef
        d1, d2 = basis_derivs(uu)
        j1 = d1 @ coef
        j2 = d2 @ coef
        ds = (j1[:, :, None] * ss[:, 0:1, :] +
              j2[:, :, None] * ss[:, 1:2, :])
        if kparam:
            bb = np.zeros_like(ds)
            bb[:, iq, colq] = ps[:, lq]
            ds = ds + bb
        return fu, ds

    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        for step in range(1, nsteps + 1):
            k1u, k1s = deriv(u, S)
            k2u, k2s = deriv(u + (0.5 * h) * k1u, S + (0.5 * h) * k1s)
            k3u, k3s = deriv(u + (0.5 * h) * k2u, S + (0.5 * h) * k2s)
            k4u, k4s = deriv(u + h * k3u, S + h * k3s)
            u = u + (h / 6.0) * (k1u + 2.0 * k2u + 2.0 * k3u + k4u)
            S = S + (h / 6.0) * (k1s + 2.0 * k2s + 2.0 * k3s + k4s)
            if (not np.all(np.isfinite(u))) or (not np.all(np.isfinite(S))) or np.max(np.abs(u)) > 1.0e10:
                raise RuntimeError("trial trajectory diverged")
            if step % substeps == 0:
                out_u[step // substeps] = u
                out_s[step // substeps] = S
    return out_u.transpose(1, 0, 2), out_s.transpose(1, 0, 2, 3)

def load_case(case_dir: Path):
    def arr(name):
        return np.load(case_dir / name, allow_pickle=False)
    tr = np.asarray(arr("train.npy"), dtype=float)
    va = np.asarray(arr("validation.npy"), dtype=float)
    t = np.asarray(arr("t.npy"), dtype=float)
    tri = np.asarray(arr("train_initial.npy"), dtype=float)
    vai = np.asarray(arr("validation_initial.npy"), dtype=float)
    with open(case_dir / "metadata.json", "r", encoding="utf-8") as f:
        md = json.load(f)
    sig_tr = np.asarray(md["noise"]["train_sigma"], dtype=float)
    sig_va = np.asarray(md["noise"]["validation_sigma"], dtype=float)
    # Be tolerant of either (n,2) or abbreviated metadata.
    if sig_tr.shape != tri.shape:
        sig_tr = np.broadcast_to(np.asarray(sig_tr, float).reshape(-1, 2)[0], tri.shape).copy()
    if sig_va.shape != vai.shape:
        sig_va = np.broadcast_to(np.asarray(sig_va, float).reshape(-1, 2)[0], vai.shape).copy()
    sig_tr = np.maximum(sig_tr, 1e-8)
    sig_va = np.maximum(sig_va, 1e-8)
    return tr, va, t, tri, vai, sig_tr, sig_va


def derivative_initial_estimates(tr, t, tri, sig):
    """Several fast, derivative-based all-term initial guesses."""
    nt = len(t)
    out = []

    def add_from_smoothed(yz, dy):
        Z = yz.reshape(-1, 2)
        Phi = basis(Z)
        nt_local = yz.shape[1]
        cc = np.zeros((10, 2))
        for j in range(2):
            W = np.repeat(1.0 / np.asarray(sig, float)[:, j] ** 2, nt_local)
            A = Phi * np.sqrt(W)[:, None]
            b = dy[:, :, j].reshape(-1) * np.sqrt(W)
            try:
                c, *_ = np.linalg.lstsq(A, b, rcond=None)
                cc[:, j] = c
            except np.linalg.LinAlgError:
                return
        out.append(cc)

    # Savitzky-Golay derivative estimates with a few bandwidths.
    for win, poly in ((21, 4), (15, 3), (31, 4), (41, 4)):
        if win > nt:
            continue
        if win % 2 == 0:
            win -= 1
        yz = np.empty_like(tr)
        dy = np.empty_like(tr)
        for k in range(tr.shape[0]):
            yy = tr[k].copy()
            yy[0] = tri[k]
            for j in range(2):
                yz[k, :, j] = savgol_filter(yy[:, j], win, poly, mode="interp")
                dy[k, :, j] = savgol_filter(yy[:, j], win, poly, deriv=1,
                                            delta=float(t[1] - t[0]), mode="interp")
        add_from_smoothed(yz, dy)

    # Cubic smoothing spline derivative estimates.
    for alpha in (0.5, 2.0, 8.0):
        yz = np.empty_like(tr)
        dy = np.empty_like(tr)
        ok = True
        for k in range(tr.shape[0]):
            yy = tr[k].copy()
            yy[0] = tri[k]
            for j in range(2):
                try:
                    s = alpha * np.sum(sig[k, j] ** 2)
                    sp = UnivariateSpline(t, yy[:, j], s=s, k=3)
                    yz[k, :, j] = sp(t)
                    dy[k, :, j] = sp.derivative()(t)
                except Exception:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            add_from_smoothed(yz, dy)

    # Integral (weak) regression: x(t)-x(0) = int_0^t Phi(x) dt.
    try:
        yy = tr.copy()
        yy[:, 0, :] = tri
        Phi = basis(yy)
        dt = float(t[1] - t[0])
        integ = np.zeros_like(Phi)
        integ[:, 1:, :] = np.cumsum(0.5 * (Phi[:, 1:, :] + Phi[:, :-1, :]) * dt, axis=1)
        tg = yy[:, 1:, :] - tri[:, None, :]
        A = integ[:, 1:, :].reshape(-1, 10)
        W = (1.0 / np.asarray(sig, float)[:, None, :]) ** 2
        W = np.broadcast_to(W, (tr.shape[0], nt - 1, 2)).reshape(-1)
        cc = np.zeros((10, 2))
        for j in range(2):
            Aw = A * np.sqrt(W)[:, None]
            bw = tg[:, :, j].reshape(-1) * np.sqrt(W)
            c, *_ = np.linalg.lstsq(Aw, bw, rcond=None)
            cc[:, j] = c
        out.append(cc)
    except Exception:
        pass

    return out


class NonlinearFitter:
    def __init__(self, data, inits, sig, t):
        self.data = np.asarray(data, float)
        self.inits = np.asarray(inits, float)
        self.sig = np.maximum(np.asarray(sig, float), 1e-8)
        self.t = np.asarray(t, float)
        self.n = self.data.size

    def residual(self, coef, substeps=2):
        try:
            pred = simulate_fast(coef, self.inits, self.t, substeps=substeps)
            r = (pred - self.data) / self.sig[:, None, :]
            if not np.all(np.isfinite(r)):
                raise FloatingPointError
            return r.ravel()
        except Exception:
            return np.full(self.n, 1.0e6)

    def fit(self, mask, x0, max_nfev=120, substeps=2, use_jac=True):
        mask = np.asarray(mask, bool)
        if mask.sum() == 0:
            c = np.zeros((10, 2))
            return c, float(np.sum(self.residual(c, substeps) ** 2)), 0
        kparam = int(mask.sum())

        def unpack(x):
            c = np.zeros((10, 2))
            c[mask] = x
            return c

        def fun(x):
            return self.residual(unpack(x), substeps)

        def jac(x):
            try:
                c = unpack(x)
                pred, sens = simulate_sens(c, self.inits, self.t, mask, substeps)
                if not np.all(np.isfinite(pred)) or not np.all(np.isfinite(sens)):
                    raise FloatingPointError
                jj = sens / self.sig[:, None, :, None]
                return jj.reshape(self.n, kparam)
            except Exception:
                return np.zeros((self.n, kparam))

        try:
            x_start = np.asarray(x0, float)[mask]
            r = least_squares(fun, x_start, jac=(jac if use_jac else "2-point"),
                              method="trf", xtol=1e-11, ftol=1e-11,
                              gtol=1e-11, max_nfev=max_nfev)
            c = unpack(r.x)
            sse = float(np.sum(r.fun ** 2))
            if not np.isfinite(sse):
                raise FloatingPointError
            return c, sse, int(r.nfev)
        except Exception:
            c = np.asarray(x0, float).copy()
            c[~mask] = 0.0
            return c, float(np.sum(self.residual(c, substeps) ** 2)), 0


def select_and_refine(case_dir: Path):
    tr, va, t, tri, vai, sig_tr, sig_va = load_case(case_dir)
    fitter = NonlinearFitter(tr, tri, sig_tr, t)
    n = fitter.n
    logn = math.log(max(n, 2))

    # Collect cheap derivative/integral estimates and rank them by trajectory fit.
    guesses = derivative_initial_estimates(tr, t, tri, sig_tr)
    if not guesses:
        guesses = [np.zeros((10, 2))]
    scored = []
    for g in guesses:
        sse0 = float(np.sum(fitter.residual(g, substeps=1) ** 2))
        scored.append((sse0, g))
    scored.sort(key=lambda x: x[0])

    # Dense nonlinear fit.  Normally the first good guess succeeds; extra guesses
    # are only used if the weighted residual is implausibly larger than n.
    best_c = scored[0][1].copy()
    best_sse = float("inf")
    all_mask = np.ones((10, 2), bool)
    for _, g in scored[:3]:
        c, sse, _ = fitter.fit(all_mask, g, max_nfev=100, substeps=1, use_jac=True)
        if np.all(np.isfinite(c)) and sse < best_sse:
            best_sse = sse
            best_c = c
        if best_sse < 1.02 * n:
            break
    if not np.isfinite(best_sse):
        best_c = scored[0][1].copy()
        best_sse = float(np.sum(fitter.residual(best_c, substeps=1) ** 2))

    # Candidate supports: magnitude thresholds plus top-K supports.
    masks = {}

    def add_mask(m):
        m = np.asarray(m, bool)
        k = int(m.sum())
        if 1 <= k <= MAX_K:
            masks[m.tobytes()] = m.copy()

    thresholds = [0.0, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 3e-2,
                  5e-2, 0.1, 0.2]
    row_thresholds = [5e-3, 1e-2, 2e-2, 3e-2, 5e-2]
    for th in thresholds:
        add_mask(np.abs(best_c) > th)
    rowmag = np.max(np.abs(best_c), axis=1)
    for th in row_thresholds:
        mr = np.zeros_like(best_c, dtype=bool)
        for row in np.where(rowmag > th)[0]:
            mr[row, :] = np.abs(best_c[row, :]) > max(th * 0.1, 1e-8)
        add_mask(mr)

    flat = np.abs(best_c).ravel()
    order = np.argsort(-flat)
    for k in range(1, MAX_K + 1):
        m = np.zeros(20, bool)
        m[order[:k]] = True
        m = m.reshape(10, 2)
        m &= np.abs(best_c) > 1e-12
        add_mask(m)

    # Screen supports with the dense coefficients before doing nonlinear refits.
    screened = []
    for m in masks.values():
        c0 = best_c.copy()
        c0[~m] = 0.0
        c0[np.abs(c0) < ZERO] = 0.0
        k0 = int(np.count_nonzero(c0))
        if k0 == 0 or k0 > MAX_K:
            continue
        sse0 = max(float(np.sum(fitter.residual(c0, substeps=1) ** 2)), 1e-12)
        bic0 = n * math.log(sse0 / n) + k0 * logn
        screened.append((bic0, sse0, m))
    screened.sort(key=lambda x: (x[0], x[1]))

    # Refit a shortlist nonlinearly, then choose by BIC on the training data.
    shortlist = [x[2] for x in screened[:6]]
    if screened:
        shortlist += [x[2] for x in sorted(screened, key=lambda x: x[1])[:2]]
    uniq = {}
    for m in shortlist:
        uniq[m.tobytes()] = m
    candidates = []
    for m in uniq.values():
        c, sse, _ = fitter.fit(m, best_c, max_nfev=80, substeps=1, use_jac=True)
        c[np.abs(c) < ZERO] = 0.0
        k = int(np.count_nonzero(c))
        if k == 0 or k > MAX_K:
            continue
        sse = max(float(np.sum(fitter.residual(c, substeps=1) ** 2)), 1e-12)
        bic = n * math.log(sse / n) + k * logn
        candidates.append((bic, sse, k, c))

    if not candidates:
        c = best_c.copy()
        c[np.abs(c) < ZERO] = 0.0
        return c

    candidates.sort(key=lambda x: (x[0], x[2]))
    chosen = candidates[0][3]

    # Final fit uses all available trajectories and finer integration, with the
    # support fixed by the BIC selection.
    all_data = np.concatenate([tr, va], axis=0)
    all_inits = np.concatenate([tri, vai], axis=0)
    all_sig = np.concatenate([sig_tr, sig_va], axis=0)
    full = NonlinearFitter(all_data, all_inits, all_sig, t)
    mask = np.abs(chosen) >= ZERO
    final, _, _ = full.fit(mask, chosen, max_nfev=150, substeps=3, use_jac=True)
    final[np.abs(final) < ZERO] = 0.0
    if np.count_nonzero(final) == 0 or np.count_nonzero(final) > MAX_K:
        final = chosen
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    np.random.seed(args.seed)
    inp = Path(args.input)
    out = Path(args.output)
    with open(inp / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    for entry in manifest["cases"]:
        cid = str(entry["id"])
        case_dir = inp / str(entry["path"])
        try:
            coef = select_and_refine(case_dir)
        except Exception as exc:
            print(f"case {cid}: fit failed: {exc}", file=sys.stderr)
            coef = np.zeros((10, 2))
        # Never emit non-finite numbers.
        coef = np.nan_to_num(np.asarray(coef, float), nan=0.0, posinf=0.0, neginf=0.0)
        coef[np.abs(coef) < ZERO] = 0.0
        dest = out / "cases" / cid
        dest.mkdir(parents=True, exist_ok=True)
        with open(dest / "model.json", "w", encoding="utf-8") as f:
            json.dump({"coefficients": coef.tolist()}, f, allow_nan=False,
                      separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
