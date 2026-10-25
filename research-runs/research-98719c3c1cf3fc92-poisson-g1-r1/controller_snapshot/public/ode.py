"""Public polynomial interface and noisy-validation diagnostics; contains no GT."""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

EXPONENTS = ((0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2),
             (3, 0), (2, 1), (1, 2), (0, 3))
BASIS = ["1", "z1", "z2", "z1^2", "z1*z2", "z2^2", "z1^3",
         "z1^2*z2", "z1*z2^2", "z2^3"]


def library(states):
    states = np.asarray(states, dtype=np.float64)
    return np.stack([states[..., 0] ** a * states[..., 1] ** b
                     for a, b in EXPONENTS], axis=-1)


def relative_error(predicted, truth):
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        result = float(np.linalg.norm(predicted - truth) / max(np.linalg.norm(truth), 1e-12))
    if not np.isfinite(result):
        raise FloatingPointError("non-finite relative error")
    return result


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite JSON constant: " + value)


def load_model(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("model must be an ordinary file <=64KiB")
    model = json.loads(path.read_text(), object_pairs_hook=_unique_pairs,
                       parse_constant=_invalid_constant)
    if not isinstance(model, dict) or set(model) != {"coefficients"}:
        raise ValueError("model requires exactly the coefficients key")
    rows = model["coefficients"]
    if (not isinstance(rows, list) or len(rows) != 10 or
            any(not isinstance(row, list) or len(row) != 2 for row in rows)):
        raise ValueError("coefficients must have shape (10,2)")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for row in rows for v in row):
        raise ValueError("coefficients must be JSON numbers")
    coefficients = np.asarray(rows, dtype=np.float64)
    if not np.isfinite(coefficients).all():
        raise ValueError("coefficients must be finite binary64")
    coefficients[np.abs(coefficients) < 1e-6] = 0.0
    return coefficients


def _integrate_child(connection, coefficients, initial, times):
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            def rhs(_, state):
                return np.einsum("i,ij->j", library(state), coefficients, optimize=False)
            result = solve_ivp(rhs, (float(times[0]), float(times[-1])), initial,
                               method="DOP853", rtol=1e-9, atol=1e-11, t_eval=times)
            values = result.y.T
            if not result.success or values.shape != (len(times), 2) or not np.isfinite(values).all():
                connection.send({"status": "integration_failed", "reason": str(result.message)})
            else:
                connection.send({"status": "success", "values": values})
    except (ValueError, ArithmeticError) as exc:
        connection.send({"status": "numerical_failure", "reason": str(exc)})
    except BaseException as exc:
        connection.send({"status": "evaluation_invalid", "reason": type(exc).__name__ + ": " + str(exc)})
    finally:
        connection.close()


def bounded_rollout(coefficients, initial, times, timeout=5.0):
    """The deadline includes process start; always terminate and reap the child."""
    context = mp.get_context("fork" if sys.platform.startswith("linux") else "spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_integrate_child, args=(send, coefficients, initial, times))
    started = time.monotonic()
    process.start()
    send.close()
    try:
        if not receive.poll(max(0, timeout - (time.monotonic() - started))):
            return {"status": "timeout", "reason": "candidate rollout exceeded 5-second deadline"}
        try:
            result = receive.recv()
        except EOFError:
            raise RuntimeError("trusted integration subprocess exited without a result")
        if result["status"] == "evaluation_invalid":
            raise RuntimeError(result["reason"])
        return result
    finally:
        receive.close()
        process.join(timeout=0.05)
        if process.is_alive():
            process.terminate()
            process.join(timeout=0.2)
        if process.is_alive():
            process.kill()
            process.join()


def check_case(input_dir, artifact_path):
    input_dir = Path(input_dir)
    try:
        coefficients = load_model(artifact_path)
    except (ValueError, OSError, OverflowError) as exc:
        return {"artifact_valid": False, "K": None, "validation_errors": [None, None],
                "validation_mean": None, "reason": str(exc)}
    times = np.load(input_dir / "t.npy", allow_pickle=False)
    initials = np.load(input_dir / "validation_initial.npy", allow_pickle=False)
    observed = np.load(input_dir / "validation.npy", allow_pickle=False)
    errors, statuses = [], []
    for initial, truth in zip(initials, observed, strict=True):
        result = bounded_rollout(coefficients, initial, times)
        status = result["status"]
        error = None
        if status == "success":
            try:
                error = relative_error(result["values"], truth)
            except FloatingPointError:
                status = "numerical_failure"
        statuses.append(status)
        errors.append(error)
    return {"artifact_valid": True, "K": int(np.count_nonzero(coefficients)),
            "validation_errors": errors, "validation_mean": float(np.mean(errors)) if None not in errors else None,
            "integration_status": statuses}
