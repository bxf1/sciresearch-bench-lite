#!/usr/bin/env python3
import argparse, json, os
from pathlib import Path
import numpy as np

PRIOR_P = 1.75
USE_EB = True
C_MULT = 1.0
KMAX = 32

def load_case(case_dir):
    with open(case_dir / 'metadata.json', 'r') as f:
        meta = json.load(f)
    data = np.loadtxt(case_dir / 'observations.csv', delimiter=',', skiprows=1, ndmin=2)
    if data.size == 0:
        data = np.empty((0, 3), dtype=float)
    x = np.asarray(data[:, 0], dtype=np.float64)
    t = np.asarray(data[:, 1], dtype=np.float64)
    y = np.asarray(data[:, 2], dtype=np.float64)
    return meta, x, t, y

def design(x, t, kappa, ks):
    # A[i,k] = decay_k(t_i) sin(pi*k*x_i)
    expo = -kappa * np.pi * np.pi * (ks[None, :] ** 2) * t[:, None]
    decay = np.exp(np.maximum(expo, -745.0))
    return np.sin(np.pi * x[:, None] * ks[None, :]) * decay

def marginal_nll(logC, M0, b, q, z2):
    C = float(np.exp(logC))
    # determinant lemma: det(I_m + C B Q B^T) = det(I_K + C Q^{1/2} B^T B Q^{1/2})
    L = q[:, None] * M0
    sign, logdet = np.linalg.slogdet(np.eye(M0.shape[0]) + C * L)
    if sign <= 0 or not np.isfinite(logdet):
        return 1.0e100
    M = M0 + np.diag(1.0 / (C * q))
    try:
        sol = np.linalg.solve(M, b)
        quad = z2 - float(b @ sol)
    except np.linalg.LinAlgError:
        return 1.0e100
    if not np.isfinite(quad) or quad < -1.0e-7:
        return 1.0e100
    return 0.5 * (logdet + max(quad, 0.0))

def estimate_case(meta, x, t, y):
    kappa = float(meta['kappa'])
    sigma = float(meta['sigma'])
    ks = np.arange(1, KMAX + 1, dtype=np.float64)
    A = design(x, t, kappa, ks)
    y = np.asarray(y, dtype=np.float64)
    sig2 = sigma * sigma
    M = A.T @ A
    rhs = A.T @ y

    p = float(PRIOR_P)
    q = ks ** (-2.0 * p)
    C0 = 2.0 / float(np.sum(np.arange(1, 33, dtype=np.float64) ** (-4.0)))
    C = C_MULT * C0

    if USE_EB and len(y) >= KMAX:
        # Work in units where the noise covariance is the identity.
        B = A / sigma
        z = y / sigma
        M0 = B.T @ B
        b = B.T @ z
        z2 = float(z @ z)
        # A few deterministic grid points plus bounded scalar refinement.
        grid = C0 * np.exp(np.linspace(np.log(0.02), np.log(100.0), 17))
        vals = [marginal_nll(np.log(g), M0, b, q, z2) for g in grid]
        j = int(np.argmin(vals))
        lo = np.log(grid[max(0, j - 1)])
        hi = np.log(grid[min(len(grid) - 1, j + 1)])
        # Golden-section search on the bracket.
        gr = (np.sqrt(5.0) - 1.0) / 2.0
        a, bb = lo, hi
        c = bb - gr * (bb - a)
        d = a + gr * (bb - a)
        fc = marginal_nll(c, M0, b, q, z2)
        fd = marginal_nll(d, M0, b, q, z2)
        for _ in range(42):
            if fc < fd:
                bb, d, fd = d, c, fc
                c = bb - gr * (bb - a)
                fc = marginal_nll(c, M0, b, q, z2)
            else:
                a, c, fc = c, d, fd
                d = a + gr * (bb - a)
                fd = marginal_nll(d, M0, b, q, z2)
        C = float(np.exp(0.5 * (a + bb)))
        if not np.isfinite(C) or C <= 0.0:
            C = C_MULT * C0

    penalty = sig2 * (ks ** (2.0 * p)) / C
    try:
        coef = np.linalg.solve(M + np.diag(penalty), rhs)
    except np.linalg.LinAlgError:
        coef = np.linalg.lstsq(A / sigma, y / sigma, rcond=1.0e-10)[0]

    if not np.isfinite(coef).all():
        coef = np.zeros(KMAX, dtype=np.float64)
    return coef, ks

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()
    inp = Path(args.input)
    out = Path(args.output)
    with open(inp / 'manifest.json', 'r') as f:
        manifest = json.load(f)
    for entry in manifest['cases']:
        case_id = entry['id']
        case_dir = inp / entry['path']
        meta, x, t, y = load_case(case_dir)
        coef, ks = estimate_case(meta, x, t, y)
        # target_grid.npy is the public evaluation grid; use it directly.
        grid = np.load(case_dir / 'target_grid.npy', allow_pickle=False).astype(np.float64)
        field = np.sin(np.pi * grid[:, None] * ks[None, :]) @ coef
        field = np.asarray(field, dtype='<f8')
        dest = out / 'cases' / case_id
        dest.mkdir(parents=True, exist_ok=True)
        np.save(dest / 'u0.npy', field, allow_pickle=False)

if __name__ == '__main__':
    main()
