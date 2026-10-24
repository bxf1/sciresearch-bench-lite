"""Private T3 generation and independent numerical checks (v0.3).

This module and its output must never enter a research or worker image.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, localcontext
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix, save_npz


def coefficient_field(n, contrast, disks):
    axis = np.arange(1, n + 1, dtype=float) / (n + 1)
    x, y = np.meshgrid(axis, axis, indexing="ij")
    inside = np.zeros((n, n), dtype=bool)
    for cx, cy, radius in disks:
        inside |= (x - cx) ** 2 + (y - cy) ** 2 < radius ** 2
    return np.asarray(1 + (contrast - 1) * inside, dtype="<f8")


def assemble(coefficient):
    """Pairwise edge assembly; each undirected interior edge is added once."""
    n = coefficient.shape[0]
    ids = np.arange(n * n).reshape(n, n)
    scale = (n + 1) ** 2
    diagonal = np.zeros(n * n)
    rows, columns, values, edge_weights = [], [], [], []
    for left, right, a, b in (
        (ids[:-1], ids[1:], coefficient[:-1], coefficient[1:]),
        (ids[:, :-1], ids[:, 1:], coefficient[:, :-1], coefficient[:, 1:]),
    ):
        i, j = left.ravel(), right.ravel()
        weight = (2 * a * b / (a + b)).ravel() * scale
        np.add.at(diagonal, i, weight)
        np.add.at(diagonal, j, weight)
        rows.extend((i, j))
        columns.extend((j, i))
        values.extend((-weight, -weight))
        edge_weights.append(weight)
    boundary_weights = []
    for edge in (ids[0], ids[-1], ids[:, 0], ids[:, -1]):
        weight = coefficient.ravel()[edge] * scale
        diagonal[edge] += weight
        boundary_weights.append(weight)
    rows.append(np.arange(n * n))
    columns.append(np.arange(n * n))
    values.append(diagonal)
    matrix = coo_matrix(
        (np.concatenate(values), (np.concatenate(rows), np.concatenate(columns))),
        shape=(n * n, n * n),
    ).tocsr()
    matrix.sort_indices()
    return matrix, np.concatenate(edge_weights), np.concatenate(boundary_weights)


def independent_flux(coefficient, values):
    """Node-centered flux calculation, independent of sparse edge assembly."""
    n = len(coefficient)
    output = np.zeros_like(values)
    h = 1 / (n + 1)
    for i in range(n):
        for j in range(n):
            row = i * n + j
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < n and 0 <= jj < n:
                    a, b = coefficient[i, j], coefficient[ii, jj]
                    weight = 2 * a * b / (a + b) / h ** 2
                    output[row] += weight * (values[row] - values[ii * n + jj])
                else:
                    output[row] += coefficient[i, j] * values[row] / h ** 2
    return output


def independent_dense_stencil(coefficient):
    """Small-grid, row-by-row operator used only for QC."""
    n = len(coefficient)
    matrix = np.zeros((n * n, n * n))
    for i in range(n):
        for j in range(n):
            row = i * n + j
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + di, j + dj
                a = coefficient[i, j]
                if 0 <= ii < n and 0 <= jj < n:
                    b = coefficient[ii, jj]
                    weight = (n + 1) ** 2 / (0.5 / a + 0.5 / b)
                    matrix[row, ii * n + jj] = -weight
                else:
                    weight = a * (n + 1) ** 2
                matrix[row, row] += weight
    return matrix


def roundoff_bound(matrix, coefficient):
    """Stored binary64 diagonal defect + conservative sparse dot error bound."""
    n, scale = len(coefficient), (len(coefficient) + 1) ** 2
    with localcontext() as context:
        context.prec = 80
        max_defect, max_row_sum = Decimal(0), Decimal(0)
        for row in range(matrix.shape[0]):
            i, j = divmod(row, n)
            edge_sum, row_sum, diagonal = Decimal(0), Decimal(0), None
            for pos in range(matrix.indptr[row], matrix.indptr[row + 1]):
                value = Decimal.from_float(float(matrix.data[pos]))
                row_sum += abs(value)
                if int(matrix.indices[pos]) == row:
                    diagonal = value
                else:
                    if value >= 0 or -value < Decimal(scale):
                        raise ValueError("Invalid interior weight for Laplacian lower bound")
                    edge_sum -= value
            boundary_count = sum((i == 0, i == n - 1, j == 0, j == n - 1))
            boundary_weight = Decimal.from_float(float(coefficient[i, j] * scale))
            if boundary_count and boundary_weight < Decimal(scale):
                raise ValueError("Invalid boundary weight for Laplacian lower bound")
            max_defect = max(max_defect, abs(diagonal - edge_sum - boundary_count * boundary_weight))
            max_row_sum = max(max_row_sum, row_sum)
        lower = Decimal(8) - max_defect
        if lower <= 0:
            raise ValueError("Unable to establish positive saved-matrix eigenvalue bound")
        unit = Decimal(2) ** -53
        gamma = 10 * unit / (1 - 10 * unit)
        return {
            "maximum_stored_diagonal_defect": str(max_defect),
            "maximum_absolute_row_sum": str(max_row_sum),
            "lambda_min_lower_bound": str(lower),
            "gamma10": str(gamma),
            "relative_solution_error_upper_bound": float(gamma * max_row_sum / lower),
            "assumptions": "binary64 round-to-nearest; no overflow or material underflow",
        }


def _fingerprint(*arrays):
    digest = hashlib.sha256()
    for array in arrays:
        array = np.asarray(array)
        digest.update(str(array.shape).encode())
        digest.update(array.astype("<i8" if array.dtype.kind in "iu" else "<f8").tobytes())
    return digest.hexdigest()


def generate_case(public_dir: Path, private_dir: Path, level: int, rngs: dict):
    if level not in (0, 1, 2):
        raise ValueError("level must be 0, 1, or 2")
    public_dir, private_dir = Path(public_dir), Path(private_dir)
    n, contrast = ((32, 1), (64, 30), (128, 300))[level]
    disks = np.column_stack((rngs["system"].uniform(.2, .8, (3, 2)),
                             rngs["system"].uniform(.08, .18, 3)))
    coefficient = coefficient_field(n, contrast, disks)
    matrix, interior_weights, boundary_weights = assemble(coefficient)
    truth = rngs["solution"].standard_normal((n * n, 4)).astype("<f8")
    rhs = np.asarray(matrix @ truth, dtype="<f8")
    independent = independent_flux(coefficient, truth)
    small_coefficient = coefficient_field(8, contrast, disks)
    small, _, _ = assemble(small_coefficient)
    small_independent = independent_dense_stencil(small_coefficient)
    np.linalg.cholesky(small_independent)
    difference = matrix - matrix.T
    asymmetry = float(np.linalg.norm(difference.data) / max(np.linalg.norm(matrix.data), 1e-12))
    flux_error = float(np.linalg.norm(rhs - independent) / max(np.linalg.norm(rhs), 1e-12))
    stencil_error = float(np.linalg.norm(small.toarray() - small_independent) /
                          max(np.linalg.norm(small_independent), 1e-12))
    rounding = roundoff_bound(matrix, coefficient)
    qc = {
        "finite": bool(np.isfinite(matrix.data).all() and np.isfinite(rhs).all() and np.isfinite(truth).all()),
        "symmetry_relative_error": asymmetry,
        "off_diagonal_nonpositive": bool(np.all(matrix.tocoo().data[matrix.tocoo().row != matrix.tocoo().col] <= 0)),
        "positive_interior_and_boundary_weights": bool(np.all(interior_weights > 0) and np.all(boundary_weights > 0)),
        "independent_flux_relative_error": flux_error,
        "independent_8x8_stencil_relative_error": stencil_error,
        "small_dense_cholesky": True,
        "roundoff": rounding,
        "gt_kind": "discrete_manufactured_solution",
    }
    qc["passed"] = bool(qc["finite"] and asymmetry < 1e-14 and qc["off_diagonal_nonpositive"]
                        and qc["positive_interior_and_boundary_weights"] and flux_error < 1e-12
                        and stencil_error < 1e-12 and rounding["relative_solution_error_upper_bound"] < 1e-7)
    (private_dir / "qc.json").write_text(json.dumps(qc, indent=2, allow_nan=False) + "\n")
    if not qc["passed"]:
        raise ValueError("T3 generation QC failed; preserve instance and investigate without resampling")
    save_npz(public_dir / "A.npz", matrix, compressed=True)
    np.save(public_dir / "rhs.npy", rhs, allow_pickle=False)
    metadata = {"task": "poisson", "contract_version": "0.3", "n": n, "shape": [n * n, n * n],
                "rhs_shape": [n * n, 4], "dtype": "little-endian float64", "matrix_format": "CSR",
                "matrix_properties": ["symmetric", "positive_definite"], "indexing": "row-major i*n+j",
                "relative_residual_limit": 1e-8, "relative_solution_error_limit": 1e-5,
                "same_operator_different_rhs": level == 0}
    (public_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    np.savez(private_dir / "truth.npz", solution=truth, coefficient=coefficient, disks=disks,
             independent_rhs=independent, interior_weights=interior_weights, boundary_weights=boundary_weights)
    operator = _fingerprint(matrix.indptr, matrix.indices, matrix.data)
    return {"qc": qc, "latent_fingerprint": _fingerprint(coefficient, truth),
            "operator_fingerprint": operator, "coefficient_fingerprint": _fingerprint(coefficient),
            "system_fingerprint": _fingerprint(matrix.indptr, matrix.indices, matrix.data, rhs),
            "same_operator_different_rhs": level == 0, "n": n, "contrast": contrast}
