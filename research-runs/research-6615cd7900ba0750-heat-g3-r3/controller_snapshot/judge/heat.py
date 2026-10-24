"""Trusted T1 numeric scorer. This module never executes or imports a submission."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class EvaluationInvalid(RuntimeError):
    """Trusted inputs or private ground truth failed their own consistency check."""


def _relative(predicted, truth):
    return float(np.linalg.norm(predicted - truth) / max(np.linalg.norm(truth), 1e-12))


def _truth(input_dir, private_dir):
    try:
        meta = json.loads((input_dir / "metadata.json").read_text())
        grid = np.load(input_dir / "target_grid.npy", allow_pickle=False)
        a = np.load(private_dir / "coefficients.npy", allow_pickle=False)
        initial = np.load(private_dir / "u0_true.npy", allow_pickle=False)
        future = np.load(private_dir / "future_true.npy", allow_pickle=False)
        if grid.shape != (256,) or a.shape != (32,) or initial.shape != (256,) or future.shape != (256,):
            raise ValueError("wrong GT shape")
        if not all(v.dtype.str == "<f8" and np.isfinite(v).all() for v in (grid, a, initial, future)):
            raise ValueError("GT must be finite little-endian binary64")
        if not np.array_equal(grid, np.arange(1, 257) / 257):
            raise ValueError("wrong target grid")
        if not (np.isfinite(meta["kappa"]) and .5 <= meta["kappa"] <= 1.5 and np.isfinite(meta["future_time"]) and meta["future_time"] > 0):
            raise ValueError("invalid propagation parameters")
        k = np.arange(1, 33, dtype=float)
        basis = np.sin(np.pi * grid[:, None] * k)
        expected_initial = np.sum(basis * a, axis=1)
        expected_future = np.sum(basis * (a * np.exp(-meta["kappa"] * np.pi**2 * k**2 * meta["future_time"])), axis=1)
        if abs(np.linalg.norm(a) / np.sqrt(2) - 1) > 1e-12 or _relative(initial, expected_initial) >= 1e-10 or _relative(future, expected_future) >= 1e-10:
            raise ValueError("saved GT disagrees with spectral definition")
        return meta, grid, initial, future
    except (OSError, ValueError, KeyError, TypeError, FloatingPointError, EOFError) as exc:
        raise EvaluationInvalid("T1 ground truth validation failed: " + str(exc)) from exc


def score_case(input_dir: Path, private_dir: Path, artifact_path: Path) -> dict:
    meta, grid, initial, future = _truth(Path(input_dir), Path(private_dir))
    artifact_path = Path(artifact_path)
    base = {"evaluation_status": "valid", "artifact_valid": False, "scientific_pass": False, "score": 0.0, "E_init": None, "E_forward": None}
    try:
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ValueError("output must be a regular file")
        u = np.load(artifact_path, allow_pickle=False)
        if not isinstance(u, np.ndarray) or u.shape != (256,) or u.dtype.str != "<f8" or not np.isfinite(u).all():
            raise ValueError("expected finite little-endian float64 shape (256,)")
    except (OSError, ValueError, EOFError) as exc:
        return {**base, "reason": "invalid_artifact: " + str(exc)}
    base["artifact_valid"] = True
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise", under="ignore"):
            # Full 256-mode sine interpolation, independently computed by direct sums.
            k = np.arange(1, 257, dtype=float)
            sine = np.sin(np.pi * grid[:, None] * k)
            coefficients = (2 / 257) * np.einsum("jk,j->k", sine, u)
            prediction = np.einsum("jk,k->j", sine, coefficients * np.exp(-meta["kappa"] * np.pi**2 * k**2 * meta["future_time"]))
            e_init, e_forward = _relative(u, initial), _relative(prediction, future)
            if not np.isfinite([e_init, e_forward]).all():
                raise FloatingPointError("relative error overflow")
    except (FloatingPointError, OverflowError) as exc:
        return {**base, "reason": "candidate_numeric_failure: " + str(exc)}
    score = 100 * (.8 * float(np.clip(1 - e_init / .30, 0, 1)) + .2 * float(np.clip(1 - e_forward / .06, 0, 1)))
    return {**base, "scientific_pass": bool(e_init <= .15 and e_forward <= .03), "score": score, "E_init": e_init, "E_forward": e_forward}
