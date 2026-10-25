"""T3 diagnostics using only public inputs and numeric output."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.sparse import load_npz


def load_solution(path, shape):
    solution = np.load(path, allow_pickle=False)
    if not isinstance(solution, np.ndarray) or solution.dtype.str != "<f8" or solution.shape != tuple(shape):
        raise ValueError("solution.npy must be little-endian float64 with the exact required shape")
    if not np.isfinite(solution).all():
        raise ValueError("solution.npy must be finite")
    return solution


def residual_errors(matrix, solution, rhs):
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        residual = matrix @ solution - rhs
        if not np.isfinite(residual).all():
            raise FloatingPointError("candidate produced nonfinite residual")
        errors = [float(np.linalg.norm(residual[:, j]) / max(np.linalg.norm(rhs[:, j]), 1e-12)) for j in range(4)]
        if not np.isfinite(errors).all():
            raise FloatingPointError("candidate residual norm overflow")
    return errors


def check_case(input_dir: Path, artifact_path: Path):
    input_dir = Path(input_dir)
    metadata = json.loads((input_dir / "metadata.json").read_text())
    matrix = load_npz(input_dir / "A.npz")
    rhs = np.load(input_dir / "rhs.npy", allow_pickle=False)
    try:
        solution = load_solution(artifact_path, (metadata["n"] ** 2, 4))
    except (ValueError, OSError, EOFError) as exc:
        return {"artifact_valid": False, "residual_pass": False, "E_res": None, "reason": str(exc)}
    try:
        errors = residual_errors(matrix, solution, rhs)
    except (FloatingPointError, OverflowError) as exc:
        return {"artifact_valid": True, "residual_pass": False, "E_res": None,
                "reason": "candidate_numerical_failure: " + str(exc)}
    return {"artifact_valid": True, "residual_pass": bool(max(errors) <= 1e-8),
            "E_res": errors, "max_relative_residual": max(errors)}
