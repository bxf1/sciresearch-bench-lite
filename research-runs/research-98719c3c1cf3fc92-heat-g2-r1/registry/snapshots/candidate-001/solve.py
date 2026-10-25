#!/usr/bin/env python3
"""Recover the initial field of a 1-D heat equation from noisy observations.

The heat propagator is diagonal in the Dirichlet sine basis.  We estimate the
first 32 sine coefficients with a Gaussian-prior (ridge) linear inverse.  The
prior is deliberately conservative for the poorly observed high modes, where
noise is exponentially amplified by the inverse diffusion; the data still
determine any high modes that are actually observable.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

# Prior coefficients variances (unit continuous L2 norm gives sum b_k^2 = 2).
# The first six values are inferred from the development cases.  The small
# floor for the remaining modes keeps the higher harmonics available when the
# observations contain real information about them, while suppressing the
# exponentially amplified noise in the ill-conditioned directions.
PRIOR_VAR = np.array(
    [1.80, 0.170, 0.0126, 0.00494, 0.00431, 0.00331,
     0.00060, 0.00050, 0.00040, 0.00030,
     0.00018, 0.00016, 0.00014, 0.00012, 0.00011, 0.00010] +
    [0.00009] * 16,
    dtype=np.float64,
)


def _read_observations(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read an observations.csv with columns x,t,y, tolerating extra columns."""
    try:
        tab = np.genfromtxt(path, delimiter=",", names=True, dtype=np.float64)
    except Exception:
        tab = np.genfromtxt(path, delimiter=",", skip_header=1, dtype=np.float64)
        if tab.ndim == 1:
            tab = tab[None, :]
        if tab.shape[1] < 3:
            raise
        return tab[:, 0], tab[:, 1], tab[:, 2]

    if tab.ndim == 0:
        tab = tab.reshape(1)
    names = tab.dtype.names
    if names is None:
        if tab.ndim == 1:
            tab = tab[None, :]
        return tab[:, 0], tab[:, 1], tab[:, 2]

    lower = {name.lower(): name for name in names}
    def pick(*candidates):
        for c in candidates:
            if c in lower:
                return tab[lower[c]].astype(np.float64, copy=False)
        raise KeyError(f"missing column among {candidates}; have {names}")

    return pick("x"), pick("t"), pick("y")


def _fit_case(case_dir: Path, kappa: float, sigma: float) -> np.ndarray:
    x, t, y = _read_observations(case_dir / "observations.csv")

    # Keep only finite, in-domain observations.  Retained coordinates are
    # exact, but this makes the solver robust to an empty/irregular row.
    good = np.isfinite(x) & np.isfinite(t) & np.isfinite(y)
    good &= (x > 0.0) & (x < 1.0) & (t >= 0.0)
    x, t, y = x[good], t[good], y[good]
    if y.size == 0:
        return np.zeros(256, dtype=np.float64)

    k = np.arange(1, 33, dtype=np.float64)
    # A[i, j] = exp(-kappa*pi^2*k^2*t_i) * sin(pi*k*x_i), for k=j+1.
    decay = np.exp(-float(kappa) * np.pi**2 * t[:, None] * (k[None, :] ** 2))
    A = decay * np.sin(np.pi * x[:, None] * k[None, :])

    # Prior variances a little above the observed coefficient variances.  For
    # large k the data term is tiny and these directions stay near zero.
    tau2 = np.maximum(PRIOR_VAR, 1e-12)
    # Posterior mean = (A^T A / sigma^2 + diag(1/tau2))^{-1} A^T y / sigma^2.
    # Written without division by sigma^2 to avoid overflow.
    s2 = max(float(sigma), 1e-12) ** 2
    gram = A.T @ A
    gram[np.diag_indices_from(gram)] += s2 / tau2
    b = np.linalg.solve(gram, A.T @ y)
    b = np.nan_to_num(b, nan=0.0, posinf=0.0, neginf=0.0)

    target_path = case_dir / "target_grid.npy"
    try:
        xg = np.asarray(np.load(target_path), dtype=np.float64).reshape(-1)
        if xg.size != 256:
            raise ValueError
    except Exception:
        xg = np.arange(1, 257, dtype=np.float64) / 257.0

    u = np.zeros(256, dtype=np.float64)
    for j, bk in enumerate(b):
        if bk != 0.0:
            u += bk * np.sin(np.pi * float(j + 1) * xg)
    return u


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    inp = Path(args.input)
    out = Path(args.output)
    with (inp / "manifest.json").open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    for entry in manifest.get("cases", []):
        cid = str(entry["id"])
        case_dir = inp / str(entry.get("path", f"cases/{cid}"))
        with (case_dir / "metadata.json").open("r", encoding="utf-8") as f:
            meta = json.load(f)
        kappa = float(meta["kappa"])
        sigma = float(meta["sigma"])
        u = _fit_case(case_dir, kappa, sigma)
        u = np.asarray(u, dtype="<f8").reshape(256)
        if not np.all(np.isfinite(u)):
            u = np.nan_to_num(u, nan=0.0, posinf=0.0, neginf=0.0)
        dest = out / "cases" / cid
        dest.mkdir(parents=True, exist_ok=True)
        np.save(dest / "u0.npy", u)


if __name__ == "__main__":
    main()
