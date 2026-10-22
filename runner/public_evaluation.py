"""Trusted, deadline-bounded public feedback shared by both research bridges."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

# The isolated checker is launched by absolute trusted script path with -I.
# Only the trusted benchmark code is added; candidate directories never are.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public.bridge_io import parse_json
from runner.common import file_hash, write_json
from runner.phase import validate_manifest
from runner.replay import evaluate_public
from runner.worker import run_worker
from runner.performance import ORDER

MAX_CHECK_OUTPUT = 65536
WORKER_FIELDS = ("attempt_status", "execution_wall_seconds", "total_wall_seconds", "cpu_seconds",
                 "memory_peak_bytes", "processes_quiesced_at_seconds", "timing_scope", "timeout_seconds",
                 "research_timeout_seconds", "budget_timeout", "budget_timeout_stage", "exit_code", "log_bytes_observed", "oom_killed",
                 "candidate_processes_terminated", "all_processes_terminated", "cleanup_status", "reason")


def _diagnostics(worker):
    return {**{key: worker.get(key) for key in WORKER_FIELDS}, "formal_timing": False}


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("public evaluation research deadline expired")
    return remaining


def _check(task, inputs, artifacts, deadline):
    """Kill the checker process group on timeout, including ODE integrators."""
    budget = _remaining(deadline)
    command = [sys.executable, "-I", str(Path(__file__).resolve()), "check", "--task", task,
               "--input", str(inputs), "--artifacts", str(artifacts)]
    environment = os.environ.copy()
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[name] = "1"
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, env=environment)
    try:
        stdout, stderr = process.communicate(timeout=min(budget, _remaining(deadline)))
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=1)
        raise TimeoutError("trusted public checker exhausted the research deadline") from exc
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=1)
    if len(stdout) > MAX_CHECK_OUTPUT or len(stderr) > MAX_CHECK_OUTPUT:
        raise ValueError("trusted public checker output exceeded 64 KiB")
    if process.returncode != 0:
        raise RuntimeError("trusted public checker failed: " + stderr[:1024].decode(errors="replace"))
    rows = parse_json(stdout)
    if not isinstance(rows, list):
        raise ValueError("trusted public checker returned a non-list")
    return rows


def _feedback(task, inputs, run, worker, deadline, check):
    feedback = {"artifact_valid": bool(worker["artifact_valid"]), "attempt_status": worker["attempt_status"],
                "wall_seconds": worker.get("execution_wall_seconds"), "cpu_seconds": worker.get("cpu_seconds"),
                "memory_peak_bytes": worker.get("memory_peak_bytes"), "worker_diagnostics": _diagnostics(worker),
                "formal_timing": False, "public_check_status": "not_run"}
    if feedback["artifact_valid"]:
        try:
            _remaining(deadline)
            rows = _check(task, inputs, run / "artifacts", deadline) if check is None else check(task, inputs, run / "artifacts")
            _remaining(deadline)
            manifest = validate_manifest(task, inputs)
            if (not isinstance(rows, list) or len(rows) != len(manifest["cases"]) or any(not isinstance(row, dict) for row in rows)
                    or [row.get("id") for row in rows] != [case["id"] for case in manifest["cases"]]):
                raise ValueError("public checker case IDs differ from the input manifest")
            feedback.update(public_check_status="completed", cases=rows)
        except (TimeoutError, subprocess.TimeoutExpired) as exc:
            feedback.update(public_check_status="timeout", public_check_error=str(exc)[:1024])
        except Exception as exc:
            feedback.update(public_check_status="failed", public_check_error=type(exc).__name__ + ": " + str(exc)[:1024])
    # Structural validity is decided by W, not by whether diagnostic integration
    # had enough time left. Never erase artifact_valid on a checker timeout.
    return feedback


def run_public_evaluation(task, snapshot, input_root, run, image, timeout, *, execute=None, check=None):
    """Run public-dev/pilot W and diagnostics within one remaining research budget.

    execute/check injection is for unit tests; production uses the fixed W and
    isolated checker. Neither the comparator nor its method is caller-selectable.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("public evaluation timeout must be finite and positive")
    started = time.monotonic()
    deadline = started + timeout
    input_root, run = Path(input_root), Path(run)
    manifest = validate_manifest(task, input_root)
    if manifest["split"] not in ("public-dev", "pilot-smoke"):
        raise ValueError("research feedback accepts only public-dev or explicit pilot-smoke")
    execute = execute or run_worker
    if task == "poisson":
        return _poisson_public(snapshot, input_root, run, image, deadline, started, execute, check)
    worker = execute(task, snapshot, input_root, run, image, timeout=_remaining(deadline))
    feedback = _feedback(task, input_root, run, worker, deadline, check)
    feedback["public_evaluation_wall_seconds"] = time.monotonic() - started
    feedback["research_budget_exhausted"] = time.monotonic() >= deadline
    write_json(run / "public_feedback.json", feedback)
    return feedback


def _poisson_public(snapshot, inputs, run, image, deadline, started, execute, check):
    """One registration consumes one BCCBBC protocol, all within its wall budget."""
    run.mkdir(parents=True, exist_ok=False)
    source = run / "comparison-source"
    source.mkdir()
    fixed_source = Path(__file__).resolve().parents[1] / "public/poisson_compare.py"
    (source / "solve.py").write_bytes(fixed_source.read_bytes())
    samples = {"B": [], "C": []}
    order = []
    protocol_status, reason = "completed", None
    for index, role in enumerate(ORDER):
        try:
            folder = run / f"sample-{index+1}-{role}"
            worker = execute("poisson", source if role == "B" else snapshot, inputs, folder, image, timeout=_remaining(deadline))
            sample = _feedback("poisson", inputs, folder, worker, deadline, check)
            samples[role].append(sample)
            order.append(role)
            if worker.get("attempt_status") == "infrastructure_failed":
                protocol_status, reason = "infrastructure_failed", "trusted worker failed during the public batch"
                break
        except (TimeoutError, subprocess.TimeoutExpired) as exc:
            protocol_status, reason = "budget_timeout", str(exc)[:1024]
            break
        except Exception as exc:
            protocol_status, reason = "infrastructure_failed", type(exc).__name__ + ": " + str(exc)[:1024]
            break
    candidates = samples["C"]
    feedback = dict(candidates[0]) if candidates else {"artifact_valid": False, "public_check_status": "not_run"}
    feedback["artifact_valid"] = len(candidates) == 3 and all(row["artifact_valid"] for row in candidates)
    feedback["attempt_status"] = protocol_status if protocol_status != "completed" else next(
        (row["attempt_status"] for row in candidates if row["attempt_status"] != "completed"), "completed")
    if not feedback["artifact_valid"] and protocol_status == "completed":
        feedback["attempt_status"] = "invalid_artifact"
    correct = lambda row: (row["artifact_valid"] and row["public_check_status"] == "completed"
                           and all(case.get("residual_pass") is True for case in row["cases"]))
    feedback["all_public_residuals_pass"] = len(candidates) == 3 and all(correct(row) for row in candidates)
    comparison = {"method": "jacobi_cg", "source_sha256": file_hash(source / "solve.py"), "formal_timing": False,
                  "status": protocol_status, "reason": reason, "order": order, "required_order": list(ORDER),
                  "baseline_repeats": samples["B"], "candidate_repeats": candidates,
                  "diagnostic_wall_ratio": None, "diagnostic_cpu_ratio": None, "diagnostic_memory_ratio": None,
                  "timing_note": "Three fresh W runs per method in BCCBBC order. Raw process intervals; formal hardware/exclusivity acceptance remains separate."}
    if order == list(ORDER) and all(correct(row) for group in samples.values() for row in group):
        for field, ratio in (("wall_seconds", "diagnostic_wall_ratio"), ("cpu_seconds", "diagnostic_cpu_ratio"),
                             ("memory_peak_bytes", "diagnostic_memory_ratio")):
            values = {role: [row.get(field) for row in samples[role]] for role in ("B", "C")}
            if all(type(value) in (int, float) and math.isfinite(value) and value > 0 for group in values.values() for value in group):
                feedback[field] = statistics.median(values["C"])
                comparison[ratio] = statistics.median(values["B"]) / feedback[field]
    feedback.update(formal_timing=False, comparison=comparison)
    totals={}
    for role,field in (("C","candidate_cpu_seconds_total"),("B","baseline_cpu_seconds_total")):
        values=[row.get("cpu_seconds") for row in samples[role]]
        totals[field]=sum(values) if values and all(type(value) in (int,float) and math.isfinite(value) and value>=0 for value in values) else None
    feedback.update(totals)
    feedback["evaluation_cpu_seconds_total"]=sum(totals.values()) if all(value is not None for value in totals.values()) else None
    feedback["public_evaluation_wall_seconds"] = time.monotonic() - started
    feedback["research_budget_exhausted"] = time.monotonic() >= deadline
    write_json(run / "public_feedback.json", feedback)
    return feedback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check",))
    parser.add_argument("--task", choices=("heat", "ode", "poisson"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate_public(args.task, args.input, args.artifacts), allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
