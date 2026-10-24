"""T1 public diagnostics only: no private truth, no scientific pass score."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.fft import dst


def check_case(input_dir: Path, artifact_path: Path) -> dict:
    input_dir, artifact_path = Path(input_dir), Path(artifact_path)
    metadata = json.loads((input_dir / "metadata.json").read_text())
    obs = np.loadtxt(input_dir / "observations.csv", delimiter=",", skiprows=1, ndmin=2)
    try:
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ValueError("output must be a regular file")
        u = np.load(artifact_path, allow_pickle=False)
        if not isinstance(u, np.ndarray) or u.shape != (256,) or u.dtype.str != "<f8" or not np.isfinite(u).all():
            raise ValueError("expected finite little-endian float64 shape (256,)")
    except (OSError, ValueError, EOFError) as exc:
        return {"artifact_valid": False, "status": "invalid_artifact", "reason": str(exc), "R": None, "roughness": None}
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise", under="ignore"):
            k = np.arange(1, 257, dtype=float)
            coefficients = dst(u, type=1) / 257
            operator = np.sin(np.pi * obs[:, 0, None] * k) * np.exp(-metadata["kappa"] * np.pi**2 * obs[:, 1, None] * k**2)
            prediction = np.einsum("ij,j->i", operator, coefficients)
            residual = float(np.sum((prediction - obs[:, 2])**2) / (len(obs) * metadata["sigma"]**2))
            second = np.diff(np.pad(u, 1), n=2) * 257**2
            roughness = float(np.sqrt(np.mean(second**2)))
            if not np.isfinite([residual, roughness]).all():
                raise FloatingPointError("diagnostics overflow")
    except (FloatingPointError, OverflowError) as exc:
        return {"artifact_valid": True, "status": "candidate_numeric_failure", "reason": str(exc), "R": None, "roughness": None}
    return {"artifact_valid": True, "status": "ok", "R": residual, "roughness": roughness}
