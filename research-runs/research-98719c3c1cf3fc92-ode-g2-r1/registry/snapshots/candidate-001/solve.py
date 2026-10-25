"""Identify sparse two-dimensional polynomial ODEs from noisy trajectories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares
from scipy.signal import savgol_filter

EXPS = ((0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2),
        (3, 0), (2, 1), (1, 2), (0, 3))


def library(x):
    x = np.asarray(x, dtype=np.float64)
    return np.stack([x[..., 0] ** a * x[..., 1] ** b for a, b in EXPS], axis=-1)


def sequential_threshold(a, y, rel_threshold=0.02, iterations=25):
    """STLSQ on one output column, with columns scaled for conditioning."""
    scales = np.linalg.norm(a, axis=0)
    scales[~np.isfinite(scales) | (scales == 0)] = 1.0
    a = a / scales
    mask = np.ones(a.shape[1], dtype=bool)
    coef = np.linalg.lstsq(a, y, rcond=None)[0]
    for _ in range(iterations):
        coef = np.zeros(a.shape[1], dtype=np.float64)
        if mask.any():
            coef[mask] = np.linalg.lstsq(a[:, mask], y, rcond=None)[0]
        if not mask.any():
            break
        threshold = rel_threshold * np.max(np.abs(coef[mask]))
        new_mask = np.abs(coef) > threshold
        if np.array_equal(new_mask, mask):
            break
        mask = new_mask
    coef = np.zeros(a.shape[1], dtype=np.float64)
    if mask.any():
        coef[mask] = np.linalg.lstsq(a[:, mask], y, rcond=None)[0]
    return coef / scales, mask


def rollout(coef, times, initial, rtol=1e-9, atol=1e-11):
    def rhs(_, state):
        return library(state) @ coef

    sol = solve_ivp(rhs, (float(times[0]), float(times[-1])), initial,
                    method="DOP853", rtol=rtol, atol=atol, t_eval=times)
    if not sol.success or sol.y.shape[1] != len(times):
        return None
    values = sol.y.T
    return values if np.isfinite(values).all() else None


def fit_coefficients(data, initials, sigmas, times, support, start):
    """Nonlinear trajectory matching over an active coefficient support."""
    if not support:
        return np.zeros((10, 2), dtype=np.float64)

    def unpack(p):
        c = np.zeros((10, 2), dtype=np.float64)
        for value, (row, col) in zip(p, support):
            c[row, col] = value
        return c

    def residual(p):
        coef = unpack(p)
        parts = []
        for x, initial, sigma in zip(data, initials, sigmas):
            pred = rollout(coef, times, initial)
            if pred is None:
                return np.full(data.shape[1] * data.shape[2], 1e6)
            parts.append(((pred - x) / sigma).ravel())
        return np.concatenate(parts)

    p0 = np.asarray([start[row, col] for row, col in support], dtype=np.float64)
    result = least_squares(residual, p0, method="trf", x_scale="jac",
                           xtol=1e-11, ftol=1e-11, gtol=1e-11,
                           max_nfev=100)
    return unpack(result.x)


def solve_case(case_dir: Path, out_file: Path):
    train = np.load(case_dir / "train.npy", allow_pickle=False)
    validation = np.load(case_dir / "validation.npy", allow_pickle=False)
    train_initial = np.load(case_dir / "train_initial.npy", allow_pickle=False)
    validation_initial = np.load(case_dir / "validation_initial.npy", allow_pickle=False)
    times = np.load(case_dir / "t.npy", allow_pickle=False)
    with open(case_dir / "metadata.json", "r", encoding="utf-8") as stream:
        metadata = json.load(stream)

    observations = np.concatenate([train, validation], axis=0)
    initials = np.concatenate([train_initial, validation_initial], axis=0)
    sigma = np.asarray(metadata["noise"]["train_sigma"] +
                       metadata["noise"]["validation_sigma"], dtype=np.float64)

    relative_noise = float(metadata.get("noise", {}).get("relative_clean_rms", 0.015))
    window = 21 if relative_noise < 0.01 else (31 if relative_noise < 0.022 else 41)
    window = min(window, observations.shape[1] - 1)
    if window % 2 == 0:
        window -= 1
    window = max(window, 7)
    margin = window // 2
    dt = float(times[1] - times[0])

    # Local polynomial derivatives are used only to propose a sparse support.
    derivatives = np.zeros_like(observations)
    for trajectory in range(observations.shape[0]):
        for channel in range(2):
            derivatives[trajectory, :, channel] = savgol_filter(
                observations[trajectory, :, channel], window, 3, deriv=1,
                delta=dt, mode="interp")

    x = observations[:, margin:observations.shape[1] - margin, :].reshape(-1, 2)
    dy = derivatives[:, margin:observations.shape[1] - margin, :].reshape(-1, 2)
    theta = library(x)
    start = np.zeros((10, 2), dtype=np.float64)
    support = []
    for channel in range(2):
        coef, mask = sequential_threshold(theta, dy[:, channel])
        start[:, channel] = coef
        support.extend((row, channel) for row in range(10) if mask[row])

    if len(support) > 10:
        support = sorted(support, key=lambda rc: -abs(start[rc]))[:10]

    coefficients = fit_coefficients(observations, initials, sigma, times, support, start)

    # Remove numerically negligible active terms, then refit the cleaned support.
    largest = max(1.0, float(np.max(np.abs(coefficients))))
    keep = [rc for rc in support if abs(coefficients[rc]) >= 1e-4 * largest]
    if keep and len(keep) < len(support):
        coefficients = fit_coefficients(observations, initials, sigma, times, keep, coefficients)
    coefficients[np.abs(coefficients) < 1e-6] = 0.0

    # Final hard cap, in the unlikely event that the proposal was too dense.
    active = [(row, col) for row in range(10) for col in range(2)
              if coefficients[row, col] != 0.0]
    if len(active) > 10:
        keep = sorted(active, key=lambda rc: -abs(coefficients[rc]))[:10]
        coefficients = fit_coefficients(observations, initials, sigma, times, keep, coefficients)
        coefficients[np.abs(coefficients) < 1e-6] = 0.0

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as stream:
        json.dump({"coefficients": coefficients.tolist()}, stream,
                  allow_nan=False, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    with open(input_dir / "manifest.json", "r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    for case in manifest["cases"]:
        case_id = case["id"]
        relative_path = case["path"]
        case_dir = input_dir / relative_path
        solve_case(case_dir, output_dir / "cases" / case_id / "model.json")


if __name__ == "__main__":
    main()
