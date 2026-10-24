"""Standalone public-input baselines: raw differences, fixed SG/STLSQ, search."""
from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.signal import savgol_filter


def library(states):
    x, y = states[..., 0], states[..., 1]
    return np.stack((np.ones_like(x), x, y, x*x, x*y, y*y, x**3, x*x*y, x*y*y, y**3), axis=-1)


def stlsq(dictionary, derivative, threshold):
    coefficients = np.linalg.lstsq(dictionary, derivative, rcond=None)[0]
    for _ in range(8):
        for channel in range(2):
            active = np.abs(coefficients[:, channel]) >= threshold
            coefficients[~active, channel] = 0
            if active.any():
                coefficients[active, channel] = np.linalg.lstsq(dictionary[:, active], derivative[:, channel], rcond=None)[0]
    return coefficients


def fit(training, times, window=31, threshold=.02):
    delta = float(times[1]-times[0])
    smooth = savgol_filter(training, window, 3, axis=1)
    derivative = savgol_filter(training, window, 3, deriv=1, delta=delta, axis=1)
    trim = window//2
    return stlsq(library(smooth[:, trim:-trim, :].reshape(-1, 2)),
                 derivative[:, trim:-trim, :].reshape(-1, 2), threshold)


def validation_error(coefficients, initial, observed, times):
    def expired(signum, frame):
        raise TimeoutError("public validation deadline")
    old_handler = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 5)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            solution = solve_ivp(lambda t, z: np.einsum("i,ij->j", library(z), coefficients, optimize=False),
                                 (float(times[0]), float(times[-1])), initial, t_eval=times,
                                 method="DOP853", rtol=1e-9, atol=1e-11)
            if not solution.success or solution.y.T.shape != observed.shape or not np.isfinite(solution.y).all():
                raise ValueError("validation integration failed")
            error = float(np.linalg.norm(solution.y.T-observed)/max(np.linalg.norm(observed), 1e-12))
            if not np.isfinite(error):
                raise FloatingPointError("non-finite validation error")
            return error
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def solve_case(input_dir, method):
    training = np.load(input_dir / "train.npy", allow_pickle=False)
    times = np.load(input_dir / "t.npy", allow_pickle=False)
    diagnostics = {"method": method, "fallback": False}
    if method == "raw":
        coefficients = np.linalg.lstsq(library(training.reshape(-1, 2)),
                                       np.gradient(training, times, axis=1).reshape(-1, 2), rcond=None)[0]
    elif method == "fixed":
        coefficients = fit(training, times)
        diagnostics.update(window=31, threshold=.02, iterations=8)
    else:
        validation = np.load(input_dir / "validation.npy", allow_pickle=False)
        initials = np.load(input_dir / "validation_initial.npy", allow_pickle=False)
        choices = []
        diagnostics["attempts"] = []
        for window in (11, 21, 31):
            for threshold in (0., .02, .05, .1):
                candidate = fit(training, times, window, threshold)
                candidate[np.abs(candidate) < 1e-6] = 0
                k = int(np.count_nonzero(candidate))
                entry = {"window": window, "threshold": threshold, "K": k}
                if k > 10:
                    entry["status"] = "too_many_coefficients"
                else:
                    try:
                        errors = [validation_error(candidate, initial, observed, times)
                                  for initial, observed in zip(initials, validation, strict=True)]
                        objective = float(np.mean(errors)) + 1e-4*k
                        choices.append((objective, candidate, window, threshold))
                        entry.update(status="valid", objective=objective, validation_errors=errors)
                    except (ValueError, ArithmeticError, TimeoutError) as exc:
                        entry.update(status="validation_failure", reason=str(exc))
                diagnostics["attempts"].append(entry)
        if choices:
            objective, coefficients, window, threshold = min(choices, key=lambda v: v[0])
            diagnostics.update(window=window, threshold=threshold, objective=objective)
        else:
            coefficients = fit(training, times)
            diagnostics.update(fallback=True, fallback_method="fixed", window=31, threshold=.02)
    coefficients[np.abs(coefficients) < 1e-6] = 0
    return coefficients, diagnostics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--method", choices=("raw", "fixed", "search"), default="fixed")
    args = parser.parse_args()
    manifest = json.loads((args.input / "manifest.json").read_text())
    for case in manifest["cases"]:
        coefficients, diagnostics = solve_case(args.input / case["path"], args.method)
        directory = args.output / "cases" / case["id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "model.json").write_text(json.dumps({"coefficients": coefficients.tolist()}, allow_nan=False) + "\n")
        print(json.dumps({"case": case["id"], **diagnostics}, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
