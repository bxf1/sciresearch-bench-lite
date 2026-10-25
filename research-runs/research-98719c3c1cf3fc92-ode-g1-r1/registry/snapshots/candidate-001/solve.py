"""Prototype of the final ODE identification algorithm (single-case helpers)."""
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"

import json
import time
import numpy as np
from scipy.signal import savgol_filter
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

EXPONENTS = ((0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2),
             (3, 0), (2, 1), (1, 2), (0, 3))
ZERO = 1e-6
MAXK = 10


def library(states):
    states = np.asarray(states, dtype=float)
    return np.stack([states[..., 0] ** a * states[..., 1] ** b
                     for a, b in EXPONENTS], axis=-1)


def make_rhs(C):
    C = np.asarray(C, dtype=float)
    def rhs(_t, state):
        z1, z2 = state
        b = np.array((1.0, z1, z2, z1*z1, z1*z2, z2*z2,
                      z1*z1*z1, z1*z1*z2, z1*z2*z2, z2*z2*z2))
        return b @ C
    return rhs


def relative_error(pred, truth):
    return float(np.linalg.norm(pred - truth) /
                 max(np.linalg.norm(truth), 1e-12))


def integrate(C, initials, t_eval, rtol=1e-9, atol=1e-11, t_span=None,
              max_evals=20000):
    base_f = make_rhs(C)
    out = []
    if t_span is None:
        t_span = (float(t_eval[0]), float(t_eval[-1]))
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            for x0 in initials:
                counter = [0]
                def f(tt, yy):
                    counter[0] += 1
                    if counter[0] > max_evals:
                        raise RuntimeError('rhs evaluation limit')
                    return base_f(tt, yy)
                sol = solve_ivp(f, t_span,
                                np.asarray(x0, dtype=float), method='DOP853',
                                rtol=rtol, atol=atol, t_eval=t_eval)
                if (not sol.success or sol.y.shape != (2, len(t_eval))
                        or not np.isfinite(sol.y).all()):
                    return None
                out.append(sol.y.T)
    except (ValueError, ArithmeticError, FloatingPointError, RuntimeError):
        return None
    return np.asarray(out)


def weighted_residual(C, observed, initials, t, sigma, fit_from=1,
                      rtol=1e-8, atol=1e-10, max_evals=12000):
    pred = integrate(C, initials, t[fit_from:], rtol=rtol, atol=atol,
                     t_span=(float(t[0]), float(t[-1])),
                     max_evals=max_evals)
    if pred is None:
        return None
    return np.concatenate([
        ((pred[k] - observed[k, fit_from:]) / sigma[k]).ravel()
        for k in range(observed.shape[0])])


def all_support():
    return [np.arange(10), np.arange(10)]


def support_of(C):
    return [np.flatnonzero(np.abs(C[:, j]) >= ZERO) for j in range(2)]


def support_key(inds):
    return tuple(tuple(int(i) for i in inds[j]) for j in range(2))


def count_support(inds):
    return sum(len(inds[j]) for j in range(2))


def direct_fit(C0, observed, initials, t, sigma, inds=None,
               max_nfev=80, rtol=1e-8, atol=1e-10, max_evals=12000):
    if inds is None:
        inds = support_of(C0)
    inds = [np.asarray(x, dtype=int) for x in inds]
    npar = count_support(inds)
    if npar == 0:
        return np.zeros((10, 2)), None, None
    offsets = (0, len(inds[0]))

    def unpack(x):
        C = np.zeros((10, 2))
        C[inds[0], 0] = x[:offsets[1]]
        C[inds[1], 1] = x[offsets[1]:]
        return C

    def resid(x):
        r = weighted_residual(unpack(x), observed, initials, t, sigma,
                              rtol=rtol, atol=atol, max_evals=max_evals)
        if r is None:
            return np.full(observed.shape[0] * (len(t) - 1) * 2, 1e6)
        return r

    x0 = np.concatenate([C0[inds[j], j] for j in range(2)])
    if not np.isfinite(x0).all():
        x0 = np.zeros(npar)
    try:
        res = least_squares(
            resid, x0, method='trf', x_scale='jac', max_nfev=max_nfev,
            ftol=1e-10, xtol=1e-10, gtol=1e-10, verbose=0)
        C = unpack(res.x)
        if not np.isfinite(C).all():
            return C0.copy(), None, None
        return C, res, unpack
    except (ValueError, ArithmeticError, FloatingPointError):
        return C0.copy(), None, None


def savgol_arrays(X, t, wl, poly=3):
    S = np.empty_like(X, dtype=float)
    D = np.empty_like(X, dtype=float)
    dt = float(t[1] - t[0])
    for tr in range(X.shape[0]):
        for ch in range(2):
            S[tr, :, ch] = savgol_filter(X[tr, :, ch], wl, poly,
                                         mode='interp')
            D[tr, :, ch] = savgol_filter(X[tr, :, ch], wl, poly, deriv=1,
                                         delta=dt, mode='interp')
    trim = wl // 2
    A = library(S[:, trim:-trim]).reshape(-1, 10)
    B = D[:, trim:-trim].reshape(-1, 2)
    return A, B


def threshold_ls(A, B, C, threshold, rounds=8):
    C = np.asarray(C, dtype=float).copy()
    for _ in range(rounds):
        changed = False
        for j in range(2):
            keep = np.abs(C[:, j]) >= threshold
            if not np.array_equal(keep, np.abs(C[:, j]) >= ZERO):
                changed = True
            C[~keep, j] = 0.0
            if keep.any():
                C[keep, j] = np.linalg.lstsq(A[:, keep], B[:, j],
                                             rcond=None)[0]
        if not changed:
            break
    C[np.abs(C) < ZERO] = 0.0
    return C


def top_support(C, k=MAXK):
    score = np.abs(C).ravel()
    order = np.argsort(score)[::-1]
    chosen = []
    for flat in order[:max(k * 3, k)]:
        i, j = divmod(int(flat), 2)
        if score[flat] >= ZERO:
            chosen.append((i, j))
        if len(chosen) == k:
            break
    inds = [np.array([i for i, j in chosen if j == 0], dtype=int),
            np.array([i for i, j in chosen if j == 1], dtype=int)]
    return [np.sort(x) for x in inds]


SG_WINDOWS = (11, 21, 31, 41)
SG_THRESHOLDS = (0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1,
                 0.15, 0.2, 0.3)


def sg_candidates(X, V, t, initials_val, windows=SG_WINDOWS,
                  thresholds=SG_THRESHOLDS):
    """Derivative-regression candidates, estimated on train data only."""
    cand = []
    dense_by_w = {}
    npts = X.shape[1]
    for wl in windows:
        if wl < 5 or wl >= npts:
            continue
        if wl % 2 == 0:
            wl += 1
        A, B = savgol_arrays(X, t, wl)
        dense = np.linalg.lstsq(A, B, rcond=None)[0]
        dense[np.abs(dense) < ZERO] = 0.0
        dense_by_w[wl] = dense
        variants = [(dense, 'dense')]
        for th in thresholds:
            if th <= 0:
                Ct = dense
            else:
                Ct = threshold_ls(A, B, dense, th)
            variants.append((Ct, th))
        seen = set()
        for C, tag in variants:
            C = np.asarray(C, dtype=float).copy()
            C[np.abs(C) < ZERO] = 0.0
            inds = support_of(C)
            if count_support(inds) == 0:
                continue
            if count_support(inds) > MAXK:
                inds = top_support(C)
                C2 = np.zeros_like(C)
                for j in range(2):
                    C2[inds[j], j] = C[inds[j], j]
                C = C2
                tag = str(tag) + '*'
            key = support_key(inds)
            if key in seen:
                continue
            seen.add(key)
            pred = integrate(C, initials_val, t, max_evals=5000)
            if pred is None:
                continue
            try:
                errs = [relative_error(pred[k], V[k]) for k in range(len(V))]
            except (ArithmeticError, FloatingPointError):
                continue
            if not np.isfinite(errs).all():
                continue
            score = float(np.mean(errs)) + 1e-4 * count_support(inds)
            cand.append({'C': C, 'inds': inds, 'score': score,
                         'errors': tuple(errs), 'window': wl, 'tag': tag})
    return cand, dense_by_w


def dense_supports(C, se=None, tcuts=(4.5, 5.5, 7.0), floors=(0.001, 0.005)):
    out = []
    if se is not None and np.isfinite(se).all():
        with np.errstate(divide='ignore', invalid='ignore'):
            tstat = np.abs(C) / np.maximum(se, 1e-15)
        for tc in tcuts:
            for fl in floors:
                active = (np.abs(C) >= fl) & (tstat >= tc)
                inds = [np.flatnonzero(active[:, j]) for j in range(2)]
                if 0 < count_support(inds) <= MAXK:
                    out.append((support_key(inds), inds))
                elif count_support(inds) > MAXK:
                    Cs = np.where(active, C, 0.0)
                    out.append((None, top_support(Cs)))
    for ac in (0.01, 0.02, 0.05):
        inds = [np.flatnonzero(np.abs(C[:, j]) >= ac) for j in range(2)]
        if 0 < count_support(inds) <= MAXK:
            out.append((support_key(inds), inds))
    out.append((None, top_support(C)))
    return out


def identify_case(X, V, t, I, IV, sigma, verbose=False, max_refits=4,
                  deadline=None):
    timings = {}
    t0 = time.time()
    cand, dense_by_w = sg_candidates(X, V, t, IV)
    timings['sg'] = time.time() - t0
    cand.sort(key=lambda z: z['score'])
    sg_by_key = {}
    for cd in cand:
        sg_by_key.setdefault(support_key(cd['inds']), cd)

    # A dense nonlinear least-squares fit supplies adaptive significance tests.
    if cand:
        wbest = cand[0]['window']
    else:
        wbest = 31 if 31 in dense_by_w else next(iter(dense_by_w), None)
    if wbest in dense_by_w:
        C_start = dense_by_w[wbest].copy()
    elif dense_by_w:
        C_start = next(iter(dense_by_w.values())).copy()
    else:
        C_start = np.zeros((10, 2))
    if deadline is not None and time.monotonic() > deadline:
        if cand:
            return cand[0]['C'].copy(), {'timings': timings,
                                         'fallback': 'sg_deadline'}
        return np.zeros((10, 2)), {'timings': timings,
                                   'fallback': 'zero_deadline'}
    t0 = time.time()
    dres = None
    Cd = C_start.copy()
    if deadline is None or time.monotonic() + 0.7 < deadline:
        Cd, dres, _ = direct_fit(C_start, np.concatenate([X, V], 0),
                                 np.concatenate([I, IV], 0), t, sigma,
                                 all_support(), max_nfev=35,
                                 rtol=1e-7, atol=1e-9, max_evals=5000)
    timings['dense_fit'] = time.time() - t0
    se = None
    if dres is not None:
        try:
            dof = max(1, len(dres.fun) - len(dres.x))
            cov = np.linalg.pinv(dres.jac.T @ dres.jac)
            se_vec = np.sqrt(np.maximum(np.diag(cov), 0.0))
            se = np.full((10, 2), np.inf)
            k = 0
            for j in range(2):
                se[:, j] = se_vec[k:k + 10]
                k += 10
        except (np.linalg.LinAlgError, ValueError):
            se = None

    supports = []
    seen = set()
    if dres is not None:
        for key, inds in dense_supports(Cd, se):
            key2 = support_key(inds)
            if key2 not in seen and 0 < count_support(inds) <= MAXK:
                seen.add(key2)
                supports.append(inds)
    # Preserve a few derivative-regression alternatives.
    for cd in cand[:5]:
        key = support_key(cd['inds'])
        if key not in seen:
            seen.add(key)
            supports.append(cd['inds'])
    if not supports:
        supports = [top_support(C_start)]

    # Rank supports cheaply by validation rollout before doing nonlinear refits.
    ranked = []
    for inds in supports:
        key = support_key(inds)
        if key in sg_by_key:
            C0 = sg_by_key[key]['C'].copy()
        else:
            C0 = np.zeros_like(Cd)
            for j in range(2):
                C0[inds[j], j] = Cd[inds[j], j]
        pred = integrate(C0, IV, t, max_evals=5000)
        if pred is None:
            continue
        try:
            verr = float(np.mean([relative_error(pred[q], V[q])
                                  for q in range(len(V))]))
        except (ArithmeticError, FloatingPointError):
            continue
        if np.isfinite(verr):
            ranked.append((verr, inds, C0))
    ranked.sort(key=lambda zzz: zzz[0])
    if not ranked:
        ranked = [(np.inf, inds, np.zeros_like(Cd)) for inds in supports[:2]]

    Xa = np.concatenate([X, V], 0)
    Ia = np.concatenate([I, IV], 0)
    all_obs = np.concatenate([X, V], 0)
    trials = []
    t0 = time.time()
    for _, inds, C0 in ranked[:max_refits]:
        if deadline is not None and time.monotonic() > deadline:
            break
        Cf, res, _ = direct_fit(C0, all_obs, Ia, t, sigma, inds,
                                max_nfev=28, rtol=1e-7, atol=1e-9,
                                max_evals=5000)
        if res is None or not np.isfinite(Cf).all():
            continue
        rss = float(np.dot(res.fun, res.fun))
        n = len(res.fun)
        k = count_support(inds)
        bic = rss + k * np.log(max(n, 2))
        pred = integrate(Cf, IV, t)
        if pred is None:
            verr = np.inf
        else:
            try:
                verr = float(np.mean([relative_error(pred[q], V[q])
                                      for q in range(len(V))]))
            except (ArithmeticError, FloatingPointError):
                verr = np.inf
        trials.append({'C': Cf, 'inds': inds, 'rss': rss, 'n': n,
                       'K': k, 'bic': bic, 'val': verr, 'res': res})
    timings['refits'] = time.time() - t0
    if not trials:
        # Fallback: best derivative candidate if it exists, otherwise zeros.
        if cand:
            return cand[0]['C'].copy(), {'timings': timings, 'fallback': 'sg'}
        return np.zeros((10, 2)), {'timings': timings, 'fallback': 'zero'}

    trials.sort(key=lambda z: z['bic'])
    best = trials[0]
    # Tight final polish.
    t0 = time.time()
    if deadline is None or time.monotonic() + 0.25 < deadline:
        Cf, res, _ = direct_fit(best['C'], all_obs, Ia, t, sigma, best['inds'],
                                max_nfev=45, rtol=1e-8, atol=1e-10,
                                max_evals=20000)
        if res is not None and np.isfinite(Cf).all():
            best['C'] = Cf
            best['rss'] = float(np.dot(res.fun, res.fun))
    timings['polish'] = time.time() - t0
    C = best['C'].copy()
    C[np.abs(C) < ZERO] = 0.0
    # Never exceed the hard sparsity cap.
    if np.count_nonzero(C) > MAXK:
        C = np.zeros_like(C)
        for j in range(2):
            C[best['inds'][j], j] = best['C'][best['inds'][j], j]
    info = {'timings': timings, 'trials': trials, 'best': best,
            'sg': cand[:10]}
    return C, info


def _metadata_sigma(md, data, ntrain, nval):
    noise = md.get('noise', {}) if isinstance(md, dict) else {}
    rel = float(noise.get('relative_clean_rms', 0.01) or 0.01)
    defaults = np.maximum(rel * np.sqrt(np.mean(data ** 2, axis=1)), 1e-8)
    pieces = []
    for key, count, block in (('train_sigma', ntrain, data[:ntrain]),
                              ('validation_sigma', nval, data[ntrain:])):
        raw = noise.get(key)
        arr = None
        try:
            arr = np.asarray(raw, dtype=float)
            if arr.shape == (count,):
                arr = np.repeat(arr[:, None], 2, axis=1)
            if arr.shape != (count, 2):
                arr = None
        except (TypeError, ValueError):
            arr = None
        if arr is None or not np.isfinite(arr).all() or np.any(arr <= 0):
            arr = defaults[:count].copy()
        pieces.append(arr)
    return np.concatenate(pieces, axis=0)


def _load_case(input_root, entry):
    cid = str(entry['id'])
    rel = entry.get('path', os.path.join('cases', cid))
    path = rel if os.path.isabs(rel) else os.path.join(input_root, rel)
    if not os.path.isdir(path):
        path = os.path.join(input_root, 'cases', cid)
    X = np.load(os.path.join(path, 'train.npy'), allow_pickle=False).astype(float)
    V = np.load(os.path.join(path, 'validation.npy'), allow_pickle=False).astype(float)
    t = np.load(os.path.join(path, 't.npy'), allow_pickle=False).astype(float)
    I = np.load(os.path.join(path, 'train_initial.npy'), allow_pickle=False).astype(float)
    IV = np.load(os.path.join(path, 'validation_initial.npy'), allow_pickle=False).astype(float)
    try:
        with open(os.path.join(path, 'metadata.json')) as fh:
            md = json.load(fh)
    except (OSError, ValueError):
        md = {}
    sigma = _metadata_sigma(md, np.concatenate([X, V], axis=0),
                            X.shape[0], V.shape[0])
    return X, V, t, I, IV, sigma


def _clean_model(C):
    C = np.asarray(C, dtype=float).reshape(10, 2)
    C[~np.isfinite(C)] = 0.0
    C[np.abs(C) < 1e-6] = 0.0
    if np.count_nonzero(C) > 10:
        flat = np.abs(C).ravel()
        keep = set(int(x) for x in np.argsort(flat)[::-1][:10])
        for p in range(20):
            if p not in keep:
                C[p // 2, p % 2] = 0.0
    return C


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args(argv)
    start = time.monotonic()
    budget = 100.0
    with open(os.path.join(args.input, 'manifest.json')) as fh:
        manifest = json.load(fh)
    cases = list(manifest.get('cases', []))
    out_base = os.path.join(args.output, 'cases')
    os.makedirs(out_base, exist_ok=True)

    for pos, entry in enumerate(cases):
        remaining_cases = len(cases) - pos
        elapsed = time.monotonic() - start
        rem = budget - elapsed
        now = time.monotonic()
        # Keep enough time for every remaining case; abandon expensive stages
        # when the batch budget becomes tight.
        if rem <= 0.5 * remaining_cases:
            deadline = now
        else:
            allocation = rem / remaining_cases * 1.5
            reserve = 0.55 * (remaining_cases - 1)
            deadline = now + max(0.25, min(allocation, rem - reserve))
        try:
            X, V, t, I, IV, sigma = _load_case(args.input, entry)
            C, _info = identify_case(X, V, t, I, IV, sigma, deadline=deadline)
        except BaseException:
            try:
                # A valid zero model is better than a missing artifact.
                X, V, t, I, IV, sigma = _load_case(args.input, entry)
                C = np.zeros((10, 2))
            except BaseException:
                C = np.zeros((10, 2))
        C = _clean_model(C)
        cid = str(entry['id'])
        target = os.path.join(out_base, cid)
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, 'model.json'), 'w') as fh:
            json.dump({'coefficients': C.tolist()}, fh,
                      allow_nan=False, separators=(',', ':'))


if __name__ == '__main__':
    main()
