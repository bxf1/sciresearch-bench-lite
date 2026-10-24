"""Author-only ODE generation and independent ground-truth checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

TRAIN_INITIAL = np.array([[1.2, 0], [-1.2, 0], [0, 1.2], [0, -1.2], [.8, .8], [-.8, -.8]])
VALIDATION_INITIAL = np.array([[.7, -.5], [-.6, .9]])
HIDDEN_INITIAL = np.array([[1.4, -.4], [-1.3, .3], [.3, 1.4], [-.4, -1.4]])


def analytic_rhs(states, parameters):
    a, b, c, d = parameters
    x, v = np.asarray(states)[..., 0], np.asarray(states)[..., 1]
    return np.stack((v, -a*x - b*v - c*x**3 - d*x*x*v), axis=-1)


def polynomial_library(states):
    x, v = states[..., 0], states[..., 1]
    return np.stack((np.ones_like(x), x, v, x*x, x*v, v*v, x**3, x*x*v, x*v*v, v**3), axis=-1)


def _trajectory(parameters, initial, times, method="DOP853"):
    tolerances = (1e-12, 1e-14) if method == "DOP853" else (1e-11, 1e-13)
    solution = solve_ivp(lambda t, z: analytic_rhs(z, parameters),
                         (float(times[0]), float(times[-1])), initial, t_eval=times,
                         method=method, rtol=tolerances[0], atol=tolerances[1])
    if not solution.success or solution.y.shape != (2, len(times)) or not np.isfinite(solution.y).all():
        raise RuntimeError("GT integration failed: " + str(solution.message))
    return solution.y.T


def _relative(a, b):
    return float(np.linalg.norm(a-b) / max(np.linalg.norm(b), 1e-12))


def generate_case(public_dir: Path, private_dir: Path, level: int, rngs: dict):
    public_dir, private_dir = Path(public_dir), Path(private_dir)
    if level not in (0, 1, 2):
        raise ValueError("level must be 0,1,2")
    rng = rngs["system"]
    parameters = np.array([rng.uniform(.6, 1.4), rng.uniform(.15, .4),
                           rng.uniform(.2, .8), rng.uniform(.1, .4) if level == 2 else 0.])
    a, b, c, d = parameters
    coefficients = np.zeros((10, 2), dtype="<f8")
    coefficients[2, 0] = 1
    coefficients[[1, 2, 6, 7], 1] = -parameters
    times, hidden_times = np.linspace(0, 6, 301), np.linspace(0, 8, 401)
    train = np.stack([_trajectory(parameters, initial, times) for initial in TRAIN_INITIAL])
    validation = np.stack([_trajectory(parameters, initial, times) for initial in VALIDATION_INITIAL])
    hidden = np.stack([_trajectory(parameters, initial, hidden_times) for initial in HIDDEN_INITIAL])
    cross_errors = {
        "train_0": _relative(_trajectory(parameters, TRAIN_INITIAL[0], times, "Radau"), train[0]),
        "hidden_0": _relative(_trajectory(parameters, HIDDEN_INITIAL[0], hidden_times, "Radau"), hidden[0]),
    }
    axis = np.linspace(-1.5, 1.5, 21)
    grid = np.stack(np.meshgrid(axis, axis, indexing="ij"), axis=-1).reshape(-1, 2)
    field = analytic_rhs(grid, parameters)
    clean_states = np.concatenate((train.reshape(-1, 2), validation.reshape(-1, 2), hidden.reshape(-1, 2), grid))
    dictionary = polynomial_library(clean_states)
    coefficient_rhs = np.einsum("ij,jk->ik", dictionary, coefficients, optimize=False)
    derivatives = analytic_rhs(clean_states, parameters)
    rhs_error = _relative(coefficient_rhs, derivatives)
    x, v = clean_states.T
    energy_dot_chain = (a*x + c*x**3)*derivatives[:, 0] + v*derivatives[:, 1]
    energy_dot_analytic = -b*v*v - d*x*x*v*v
    energy_identity_error = float(np.max(np.abs(energy_dot_chain-energy_dot_analytic)))
    energy_rows = []
    energy_arrays = {}
    for name, trajectories in (("train", train), ("validation", validation), ("hidden", hidden)):
        x, v = trajectories[..., 0], trajectories[..., 1]
        energies = v*v/2 + a*x*x/2 + c*x**4/4
        energy_arrays[name + "_energy"] = energies
        for i, energy in enumerate(energies):
            increase = float(np.max(np.diff(energy)))
            limit = float(1e-9*max(1, energy[0]))
            energy_rows.append({"set": name, "trajectory": i, "max_increase": increase, "limit": limit})
    train_dictionary = polynomial_library(train.reshape(-1, 2))
    singular = np.linalg.svd(train_dictionary, compute_uv=False)
    rank = int(np.linalg.matrix_rank(train_dictionary))
    qc = {
        "cross_integrator_relative_errors": cross_errors,
        "analytic_coefficient_rhs_relative_error": rhs_error,
        "energy_identity_absolute_error": energy_identity_error,
        "energy_monotonicity": energy_rows,
        "dictionary_rank": rank, "dictionary_singular_values": singular.tolist(),
        "dictionary_condition": float(singular[0]/singular[-1]),
        "state_min": clean_states[:-len(grid)].min(axis=0).tolist(),
        "state_max": clean_states[:-len(grid)].max(axis=0).tolist(),
        "trajectory_box_is_not_a_failure_gate": True, "rejection_count": 0,
    }
    passed = (all(v < 1e-8 for v in cross_errors.values()) and rhs_error < 1e-12 and
              energy_identity_error <= 1e-10 and all(r["max_increase"] <= r["limit"] for r in energy_rows))
    qc["passed"] = bool(passed)
    if not passed:
        (private_dir / "qc.json").write_text(json.dumps(qc, indent=2, allow_nan=False) + "\n")
        raise RuntimeError("ODE ground-truth QC failed; preserve instance and investigate")
    eta = (.005, .015, .03)[level]
    train_sigma = eta*np.sqrt(np.mean(train**2, axis=1))
    validation_sigma = eta*np.sqrt(np.mean(validation**2, axis=1))
    train_noise = rngs["noise"].normal(size=train.shape)*train_sigma[:, None, :]
    validation_noise = rngs["noise"].normal(size=validation.shape)*validation_sigma[:, None, :]
    public_arrays = {"train": train + train_noise, "validation": validation + validation_noise,
                     "t": times, "train_initial": TRAIN_INITIAL, "validation_initial": VALIDATION_INITIAL}
    private_arrays = {
        "parameters": parameters, "coefficients": coefficients, "train_clean": train,
        "validation_clean": validation, "hidden_clean": hidden, "hidden_t": hidden_times,
        "hidden_initial": HIDDEN_INITIAL, "field_grid": grid, "field_true": field,
        "train_noise": train_noise, "validation_noise": validation_noise,
        "train_derivatives": analytic_rhs(train, parameters),
        "validation_derivatives": analytic_rhs(validation, parameters),
        "hidden_derivatives": analytic_rhs(hidden, parameters),
        "train_sigma": train_sigma, "validation_sigma": validation_sigma, **energy_arrays,
    }
    for directory, arrays in ((public_dir, public_arrays), (private_dir, private_arrays)):
        for name, values in arrays.items():
            if not np.isfinite(values).all():
                raise RuntimeError("non-finite generated array: " + name)
            np.save(directory / (name + ".npy"), np.asarray(values, dtype="<f8"), allow_pickle=False)
    metadata = {
        "task": "ode", "contract_version": "0.3", "level": level,
        "state_names": ["z1", "z2"], "units": "dimensionless", "autonomous": True,
        "maximum_polynomial_degree": 3,
        "basis": ["1", "z1", "z2", "z1^2", "z1*z2", "z2^2", "z1^3", "z1^2*z2", "z1*z2^2", "z2^3"],
        "coefficient_shape": [10, 2], "derivative_columns": ["dz1/dt", "dz2/dt"],
        "noise": {"kind": "independent Gaussian", "relative_clean_rms": eta,
                  "train_sigma": train_sigma.tolist(), "validation_sigma": validation_sigma.tolist(),
                  "includes_initial_observation": True, "exact_initial_states_separate": True},
        "field_grid": {"lower": -1.5, "upper": 1.5, "points_per_axis": 21,
                       "trajectory_bounds": False},
        "candidate_rollout": {"method": "DOP853", "rtol": 1e-9, "atol": 1e-11,
                              "timeout_seconds": 5, "hidden_t_end": 8, "hidden_time_points": 401},
        "zero_threshold_strict": 1e-6, "maximum_nonzero_coefficients": 10,
    }
    (public_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    qc["private_file_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(private_dir.glob("*.npy"))}
    (private_dir / "qc.json").write_text(json.dumps(qc, indent=2, allow_nan=False) + "\n")
    return {"qc": qc, "latent_fingerprint": hashlib.sha256(coefficients.tobytes()).hexdigest(),
            "parameters": parameters.tolist(), "rejection_count": 0}
