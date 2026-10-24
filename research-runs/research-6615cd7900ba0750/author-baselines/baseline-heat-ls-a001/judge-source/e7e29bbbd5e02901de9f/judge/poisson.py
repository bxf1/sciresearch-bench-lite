"""Private numeric T3 scoring. Candidate source is never loaded here."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.sparse import load_npz

from public.poisson import load_solution, residual_errors


class TruthError(ValueError):
    """Trusted data is invalid: no candidate score can be reported."""


def _trusted_inputs(input_dir, private_dir):
    try:
        metadata = json.loads((input_dir / "metadata.json").read_text())
        n = metadata["n"]
        matrix = load_npz(input_dir / "A.npz").tocsr()
        rhs = np.load(input_dir / "rhs.npy", allow_pickle=False)
        with np.load(private_dir / "truth.npz", allow_pickle=False) as archive:
            truth = archive["solution"]
            independent = archive["independent_rhs"]
        qc = json.loads((private_dir / "qc.json").read_text())
        if not qc["passed"] or matrix.shape != (n * n, n * n) or rhs.shape != (n * n, 4):
            raise ValueError("GT dimensions or QC flag invalid")
        if truth.shape != rhs.shape or independent.shape != rhs.shape:
            raise ValueError("GT truth dimensions invalid")
        if not all(np.isfinite(a).all() for a in (matrix.data, rhs, truth, independent)):
            raise ValueError("GT contains nonfinite data")
        if max(residual_errors(matrix, truth, rhs)) >= 1e-12:
            raise ValueError("GT manufactured solution does not match saved A and B")
        independent_error = np.linalg.norm(independent - rhs) / max(np.linalg.norm(rhs), 1e-12)
        if not np.isfinite(independent_error) or independent_error >= 1e-12:
            raise ValueError("GT independent flux result does not match B")
        if qc["roundoff"]["relative_solution_error_upper_bound"] >= 1e-7:
            raise ValueError("GT roundoff margin invalid")
    except Exception as exc:
        raise TruthError("T3 trusted-input self-check failed: " + str(exc)) from exc
    return matrix, rhs, truth


def score_case(input_dir: Path, private_dir: Path, artifact_path: Path):
    matrix, rhs, truth = _trusted_inputs(Path(input_dir), Path(private_dir))
    base = {"evaluation_status": "valid", "performance_status": "pending_host_measurement"}
    try:
        solution = load_solution(artifact_path, truth.shape)
    except (ValueError, OSError, EOFError) as exc:
        return dict(base, artifact_valid=False, scientific_pass=False, score=0.0,
                    E_res=None, E_sol=None, reason=str(exc))
    try:
        residual = residual_errors(matrix, solution, rhs)
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            error = [float(np.linalg.norm(solution[:, j] - truth[:, j]) /
                           max(np.linalg.norm(truth[:, j]), 1e-12)) for j in range(4)]
            if not np.isfinite(error).all():
                raise FloatingPointError("candidate solution error norm overflow")
    except (FloatingPointError, OverflowError) as exc:
        return dict(base, artifact_valid=True, scientific_pass=False, score=0.0,
                    E_res=None, E_sol=None, reason="candidate_numerical_failure: " + str(exc))
    passed = max(residual) <= 1e-8 and max(error) <= 1e-5
    return dict(base, artifact_valid=True, scientific_pass=bool(passed), score=None if passed else 0.0,
                E_res=residual, E_sol=error, max_relative_residual=max(residual), max_solution_error=max(error))
