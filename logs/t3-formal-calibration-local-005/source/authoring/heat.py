"""Author-only T1 generator. Never include this module in R or W images."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.fft import dst


def _field(coefficients, x, t, kappa):
    k = np.arange(1, len(coefficients) + 1, dtype=float)
    basis = np.sin(np.pi * np.asarray(x)[..., None] * k)
    return np.einsum("...k,k->...", basis * np.exp(-kappa * np.pi**2 * k**2 * np.asarray(t)[..., None]), coefficients)


def _relative(a, b):
    return float(np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-12))


def generate_case(public_dir: Path, private_dir: Path, level: int, rngs: dict) -> dict:
    """Generate one case with independent system/mask/noise streams, without solver screening."""
    if level not in (0, 1, 2):
        raise ValueError("level must be 0, 1 or 2")
    public_dir, private_dir = Path(public_dir), Path(private_dir)
    system = rngs["system"]
    k = np.arange(1, 33, dtype=float)
    p = float(system.uniform(1.5, 2.5))
    coefficients = system.normal(size=32) / k**p
    coefficients[0] = system.choice([-1.0, 1.0]) * system.uniform(0.8, 1.2)
    norm = np.linalg.norm(coefficients)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("invalid latent field norm; do not resample")
    coefficients *= np.sqrt(2.0) / norm
    kappa = float(system.uniform(0.5, 1.5))
    times = np.array(((.001, .004), (.003, .009), (.006, .018))[level])
    missing_rate = (0.0, .15, .30)[level]
    for rejected_masks in range(1000):
        mask = rngs["mask"].random((2, 128)) >= missing_rate
        if np.all(np.sum(mask, axis=1) >= 64):
            break
    else:
        raise ValueError("mask generation failed after 1000 attempts; latent system preserved")
    x_full = np.broadcast_to(np.arange(1, 129) / 129, (2, 128))
    t_full = np.broadcast_to(times[:, None], (2, 128))
    x, t = x_full[mask], t_full[mask]
    clean = _field(coefficients, x, t, kappa)
    sigma = float((.005, .01, .02)[level] * np.sqrt(np.mean(clean**2)))
    noise = rngs["noise"].normal(size=clean.shape) * sigma
    y = clean + noise
    target = np.arange(1, 257) / 257
    future_time = float(1.25 * times[-1])
    initial = _field(coefficients, target, 0.0, kappa)
    future = _field(coefficients, target, future_time, kappa)

    # DST and the matrix-free FFT implementation are independent of the generating sum.
    recovered = dst(initial, type=1) / 257
    expected = np.pad(coefficients, (0, 224))
    modes = np.arange(1, 257, dtype=float)
    recovered_future = dst(recovered * np.exp(-kappa * np.pi**2 * modes**2 * future_time), type=1) / 2
    mid = _field(coefficients, target, times[0], kappa)
    semigroup = dst(dst(mid, type=1) / 257 * np.exp(-kappa * np.pi**2 * modes**2 * (future_time - times[0])), type=1) / 2
    direct_t0 = np.sum(coefficients * np.sin(np.pi * target[:, None] * k), axis=1)
    rates = kappa * np.pi**2 * k**2
    probe_time = float(times[-1])
    q = coefficients * np.exp(-rates * probe_time)
    # Complex-step derivative avoids subtractive cancellation at strongly damped modes.
    derivative = np.imag(coefficients * np.exp(-rates * (probe_time + 1e-25j))) / 1e-25
    rhs = -rates * q
    pde_residual = float(np.max(np.abs(derivative - rhs) / np.maximum(np.maximum(np.abs(derivative), np.abs(rhs)), 1e-12)))
    boundary = float(np.max(np.abs(_field(coefficients, np.array([0.0, 1.0]), 0.0, kappa))))
    qc = {
        "continuous_rms_absolute_error": float(abs(np.linalg.norm(coefficients) / np.sqrt(2) - 1)),
        "discrete_rms": float(np.sqrt(np.mean(initial**2))),
        "t0_relative_error": _relative(direct_t0, initial),
        "dst_coefficients_relative_error": _relative(recovered, expected),
        "dst_forward_relative_error": _relative(recovered_future, future),
        "semigroup_relative_error": _relative(semigroup, future),
        "boundary_absolute_error": boundary,
        "boundary_tolerance": float(1e-12 * max(1, np.max(np.abs(initial)))),
        "modal_pde_scaled_residual": pde_residual,
        "observations_per_time": np.sum(mask, axis=1).tolist(),
        "mask_rejections": rejected_masks,
        "mask_attempts": rejected_masks + 1,
        "solver_screening": False,
    }
    qc["passed"] = bool(
        qc["continuous_rms_absolute_error"] <= 1e-12
        and all(qc[key] < 1e-10 for key in ("t0_relative_error", "dst_coefficients_relative_error", "dst_forward_relative_error", "semigroup_relative_error"))
        and boundary <= qc["boundary_tolerance"] and pde_residual <= 1e-10
        and all(np.isfinite(a).all() for a in (coefficients, initial, future, clean, noise, y))
    )
    # Write evidence even if QC fails; the orchestrator must stop, never replace a case.
    np.savetxt(public_dir / "observations.csv", np.column_stack((x, t, y)), delimiter=",", header="x,t,y", comments="", fmt="%.17g")
    np.save(public_dir / "target_grid.npy", target.astype("<f8"), allow_pickle=False)
    metadata = {
        "task": "heat", "contract_version": "0.3", "kappa": kappa,
        "sigma": sigma, "mode_limit": 32, "times": times.tolist(),
        "future_time": future_time, "target_size": 256,
        "noise": "independent zero-mean Gaussian with common absolute sigma",
        "boundary": "u(0,t)=u(1,t)=0", "units": "dimensionless",
        "observation_columns": ["x", "t", "y"],
    }
    (public_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    arrays = {"coefficients": coefficients, "u0_true": initial, "future_true": future, "clean": clean, "noise": noise, "mask": mask}
    for name, value in arrays.items():
        np.save(private_dir / (name + ".npy"), value, allow_pickle=False)
    fingerprint = hashlib.sha256(coefficients.astype("<f8").tobytes()).hexdigest()
    private_metadata = {"p": p, "kappa": kappa, "latent_fingerprint": fingerprint, "level": level, "sigma_definition": "eta times RMS of retained clean observations"}
    (private_dir / "private_metadata.json").write_text(json.dumps(private_metadata, indent=2, allow_nan=False) + "\n")
    (private_dir / "qc.json").write_text(json.dumps(qc, indent=2, allow_nan=False) + "\n")
    if not qc["passed"]:
        raise ValueError("T1 GT QC failed; evidence saved and instance must not be replaced")
    return {"qc": qc, "latent_fingerprint": fingerprint}
