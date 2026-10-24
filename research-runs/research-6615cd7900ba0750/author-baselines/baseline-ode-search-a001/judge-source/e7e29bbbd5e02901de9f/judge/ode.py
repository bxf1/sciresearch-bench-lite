"""Trusted T2 scoring: numeric coefficients only; never import submitted code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from public.ode import bounded_rollout, library, load_model, relative_error


def _ground_truth(private_dir):
    private_dir = Path(private_dir)
    qc = json.loads((private_dir / "qc.json").read_text())
    if not qc.get("passed"):
        raise RuntimeError("evaluation_invalid: GT QC did not pass")
    expected_shapes = {"coefficients": (10, 2), "hidden_clean": (4, 401, 2),
                       "hidden_t": (401,), "hidden_initial": (4, 2),
                       "field_grid": (441, 2), "field_true": (441, 2)}
    truth = {}
    for name, shape in expected_shapes.items():
        path = private_dir / (name + ".npy")
        if hashlib.sha256(path.read_bytes()).hexdigest() != qc["private_file_sha256"][path.name]:
            raise RuntimeError("evaluation_invalid: GT checksum mismatch: " + name)
        values = np.load(path, allow_pickle=False)
        if values.shape != shape or values.dtype != np.dtype("<f8") or not np.isfinite(values).all():
            raise RuntimeError("evaluation_invalid: malformed GT: " + name)
        truth[name] = values
    if not np.array_equal(truth["hidden_t"], np.linspace(0, 8, 401)):
        raise RuntimeError("evaluation_invalid: wrong GT time grid")
    field = np.einsum("ij,jk->ik", library(truth["field_grid"]), truth["coefficients"], optimize=False)
    if relative_error(field, truth["field_true"]) >= 1e-12:
        raise RuntimeError("evaluation_invalid: coefficient/field inconsistency")
    if not np.allclose(truth["hidden_clean"][:, 0, :], truth["hidden_initial"], rtol=0, atol=1e-14):
        raise RuntimeError("evaluation_invalid: initial-state mismatch")
    return truth


def score_case(input_dir, private_dir, artifact_path):
    truth = _ground_truth(private_dir)
    result = {"artifact_valid": False, "scientific_pass": False, "score": 0.0,
              "evaluation_status": "valid", "K": None, "E_field": None,
              "E_roll": None, "rollout_errors": [None]*4, "integration_status": []}
    try:
        coefficients = load_model(artifact_path)
    except (ValueError, OSError, OverflowError) as exc:
        result["reason"] = "invalid_artifact: " + str(exc)
        return result
    result["artifact_valid"] = True
    result["K"] = int(np.count_nonzero(coefficients))
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            field = np.einsum("ij,jk->ik", library(truth["field_grid"]), coefficients, optimize=False)
            result["E_field"] = relative_error(field, truth["field_true"])
    except FloatingPointError:
        result["reason"] = "candidate_field_numerical_failure"
        return result
    errors, statuses = [], []
    for initial, expected in zip(truth["hidden_initial"], truth["hidden_clean"], strict=True):
        integrated = bounded_rollout(coefficients, initial, truth["hidden_t"])
        status, error = integrated["status"], None
        if status == "success":
            try:
                error = relative_error(integrated["values"], expected)
            except FloatingPointError:
                status = "numerical_failure"
        errors.append(error)
        statuses.append(status)
    result.update(rollout_errors=errors, integration_status=statuses)
    if None in errors:
        result["reason"] = "candidate_rollout_failure"
        return result
    result["E_roll"] = max(errors)
    if result["K"] > 10:
        result["reason"] = "coefficient_count_exceeds_10"
        return result
    result["scientific_pass"] = result["E_roll"] <= .05 and result["E_field"] <= .05
    result["score"] = 100*(.5*float(np.clip(1-result["E_roll"]/.10, 0, 1)) +
                           .5*float(np.clip(1-result["E_field"]/.10, 0, 1)))
    return result
