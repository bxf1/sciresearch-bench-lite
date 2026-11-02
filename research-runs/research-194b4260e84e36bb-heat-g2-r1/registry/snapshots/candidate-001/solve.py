#!/usr/bin/env python3
"""Recover the initial field for a batch of 1D heat inverse problems.

The observation operator is diagonal in the sine basis.  For each problem we
form the exact heat-evolution observation matrix for modes 1..32 and compute a
diagonal-prior Bayesian posterior mean in that basis.  The prior variance is
proportional to k^-2, with total prior energy equal to the problem's
normalization (sum_k a_k^2 = 2), which was verified across the development
cases.  This regularization keeps well-observed low modes essentially
unbiased while suppressing the exponentially ill-conditioned high modes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np


PRIOR_POWER = 2.0
MODE_LIMIT = 32


def read_observations(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read an observations CSV without requiring pandas."""
    try:
        data = np.genfromtxt(path, delimiter=",", names=True, dtype=float,
                             encoding="utf-8", case_sensitive=False)
    except Exception as exc:  # pragma: no cover - defensive fallback
        raw = np.loadtxt(path, delimiter=",", skiprows=1, dtype=float)
        raw = np.atleast_2d(raw)
        return raw[:, 0], raw[:, 1], raw[:, 2]

    names = {name.lower().strip(): name for name in data.dtype.names or ()}
    if not {"x", "t", "y"}.issubset(names):
        raw = np.loadtxt(path, delimiter=",", skiprows=1, dtype=float)
        raw = np.atleast_2d(raw)
        return raw[:, 0], raw[:, 1], raw[:, 2]

    return (np.asarray(data[names["x"]], dtype=np.float64).ravel(),
            np.asarray(data[names["t"]], dtype=np.float64).ravel(),
            np.asarray(data[names["y"]], dtype=np.float64).ravel())


def sine_design(x: np.ndarray, t: np.ndarray, kappa: float,
                modes: int) -> np.ndarray:
    """Observation matrix for sine modes 1..modes of the heat equation."""
    k = np.arange(1, modes + 1, dtype=np.float64)[None, :]
    decay = np.exp(-float(kappa) * math.pi ** 2 * (k ** 2) * t[:, None])
    return np.sin(math.pi * x[:, None] * k) * decay


def prior_variances(modes: int, power: float = PRIOR_POWER) -> np.ndarray:
    """Total prior energy 2, distributed as a power law v_k ∝ k^-power."""
    k = np.arange(1, modes + 1, dtype=np.float64)
    z = float(np.sum(k ** (-power)))
    return (2.0 / z) * (k ** (-power))


def solve_case(case_dir: Path) -> np.ndarray:
    with (case_dir / "metadata.json").open("r", encoding="utf-8") as stream:
        meta = json.load(stream)

    x, t, y = read_observations(case_dir / "observations.csv")
    finite = np.isfinite(x) & np.isfinite(t) & np.isfinite(y)
    x, t, y = x[finite], t[finite], y[finite]

    kappa = float(meta["kappa"])
    sigma = float(meta["sigma"])
    if not math.isfinite(sigma) or sigma <= 0.0:
        sigma = 1.0
    if len(y) == 0:
        raise ValueError(f"no observations in {case_dir}")

    modes = int(meta.get("mode_limit", MODE_LIMIT) or MODE_LIMIT)
    modes = max(1, min(MODE_LIMIT, modes))

    A = sine_design(x, t, kappa, modes)
    v = prior_variances(modes)

    # Gaussian posterior mean with independent N(0, v_k) coefficients:
    # (A^T A / sigma^2 + diag(1/v)) a = A^T y / sigma^2.
    As = A / sigma
    ys = y / sigma
    gram = As.T @ As
    rhs = As.T @ ys
    system = gram + np.diag(1.0 / v)
    system = 0.5 * (system + system.T)

    try:
        coeff = np.linalg.solve(system, rhs)
    except np.linalg.LinAlgError:
        coeff = np.linalg.lstsq(system, rhs, rcond=None)[0]

    # Never let a numerical pathology leak into the submitted artifact.
    coeff = np.asarray(coeff, dtype=np.float64)
    coeff[~np.isfinite(coeff)] = 0.0
    if modes < MODE_LIMIT:
        coeff = np.concatenate([coeff, np.zeros(MODE_LIMIT - modes)])

    # Reconstruct exactly on the requested target grid.
    target_path = case_dir / "target_grid.npy"
    if target_path.is_file():
        grid = np.load(target_path, allow_pickle=False)
        grid = np.asarray(grid, dtype=np.float64).ravel()
    else:
        grid = np.arange(1, 257, dtype=np.float64) / 257.0

    k = np.arange(1, MODE_LIMIT + 1, dtype=np.float64)[None, :]
    u0 = np.sin(math.pi * grid[:, None] * k) @ coeff
    u0 = np.asarray(u0, dtype="<f8").reshape(-1)
    if u0.size != 256:
        # The contract asks for 256 values on x_j = j/257.
        xg = np.arange(1, 257, dtype=np.float64) / 257.0
        u0 = np.sin(math.pi * xg[:, None] * k) @ coeff
        u0 = np.asarray(u0, dtype="<f8").reshape(256)
    u0[~np.isfinite(u0)] = 0.0
    return u0


def discover_cases(input_dir: Path) -> list[tuple[str, Path]]:
    cases: list[tuple[str, Path]] = []
    seen: set[str] = set()

    manifest_path = input_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            with manifest_path.open("r", encoding="utf-8") as stream:
                manifest = json.load(stream)
            for entry in manifest.get("cases", []):
                cid = str(entry["id"])
                rel = entry.get("path", f"cases/{cid}")
                path = input_dir / rel
                if path.is_dir():
                    key = os.path.basename(str(path))
                    if key not in seen:
                        seen.add(key)
                        cases.append((cid, path))
        except Exception:
            cases = []

    if not cases:
        root = input_dir / "cases"
        if root.is_dir():
            for path in sorted(root.iterdir()):
                if path.is_dir() and (path / "metadata.json").is_file():
                    cid = path.name
                    if cid not in seen:
                        seen.add(cid)
                        cases.append((cid, path))

    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_root = output_dir / "cases"
    cases_root.mkdir(parents=True, exist_ok=True)

    cases = discover_cases(input_dir)
    if not cases:
        print(f"no cases found under {input_dir}", file=sys.stderr)
        return 1

    for cid, case_dir in cases:
        u0 = solve_case(case_dir)
        out_dir = cases_root / cid
        out_dir.mkdir(parents=True, exist_ok=True)
        np.save(out_dir / "u0.npy", u0, allow_pickle=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
