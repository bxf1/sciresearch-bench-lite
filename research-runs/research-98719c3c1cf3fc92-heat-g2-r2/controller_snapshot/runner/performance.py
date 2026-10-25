"""Pure T3 protocol aggregation. This module does not run or certify a timer.

Only host-produced measurements with the explicit formal evidence below are
admitted. Synthetic unit-test records exercise rules, not actual performance.
"""
from __future__ import annotations

import math
import statistics

ORDER = ("B", "C", "C", "B", "B", "C")
EFFICIENCY_PROFILE = "efficiency_gate_1.5"
ACCURACY_PROFILE = "accuracy_with_efficiency_diagnostic"
FORMAL_TIMING_SCOPE = "python_spawn_to_all_descendants_exit"
PROFILES = (EFFICIENCY_PROFILE, ACCURACY_PROFILE)
EXECUTION_FAILURES = {"candidate_failed", "candidate_resource_failure", "timeout", "oom", "log_limit", "invalid_artifact"}


def _positive_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _formal_evidence(samples, evidence):
    reasons = []
    if evidence.get("machine_exclusive_verified") is not True:
        reasons.append("host_did_not_verify_machine_exclusivity")
    if not evidence.get("exclusive_lock_id") or evidence.get("other_workloads") != []:
        reasons.append("missing_exclusive_lock_or_other_workloads_present")
    if not evidence.get("cache_state"):
        reasons.append("missing_cache_state")
    machine = evidence.get("machine_id")
    if not machine:
        reasons.append("missing_machine_identity")
    workers = [sample.get("worker", {}) for sample in samples]
    qualified_failure = lambda worker: (worker.get("attempt_status") in EXECUTION_FAILURES
                                        and worker.get("failure_in_qualified_environment") is True)
    if any(worker.get("formal_timing") is not True and not qualified_failure(worker) for worker in workers):
        reasons.append("diagnostic_timing_cannot_be_promoted")
    for field in ("input_sha256", "resource_contract_sha256"):
        values = [worker.get(field) for worker in workers]
        if not all(isinstance(value, str) and value for value in values) or len(set(values)) != 1:
            reasons.append("missing_or_inconsistent_" + field)
    for role in ("B", "C"):
        hashes = [sample.get("source_hash") for sample in samples if sample["role"] == role]
        if not all(isinstance(value, str) and value for value in hashes) or len(set(hashes)) != 1:
            reasons.append("missing_or_inconsistent_" + role + "_source_hash")
    container_ids = [worker.get("container_id") for worker in workers]
    if not all(container_ids) or len(set(container_ids)) != len(workers):
        reasons.append("workers_are_not_verified_fresh")
    end_previous = None
    for index, worker in enumerate(workers):
        if worker.get("machine_id") != machine:
            reasons.append(f"sample_{index}_machine_mismatch")
        if worker.get("resource_qualified") is not True:
            reasons.append(f"sample_{index}_resources_not_qualified")
        if worker.get("all_processes_terminated") is not True:
            reasons.append(f"sample_{index}_processes_not_terminated")
        # A timeout/OOM has no completed interval. Its fresh-container/resource
        # provenance still qualifies the failure; it can never be a denominator.
        if qualified_failure(worker):
            continue
        if worker.get("output_initially_empty") is not True:
            reasons.append(f"sample_{index}_output_not_verified_empty")
        if worker.get("timing_scope") != FORMAL_TIMING_SCOPE:
            reasons.append(f"sample_{index}_wrong_timing_scope")
        seconds = worker.get("execution_wall_seconds")
        start, end = worker.get("started_monotonic_ns"), worker.get("finished_monotonic_ns")
        if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int)
                or isinstance(end, bool) or start < 0 or end <= start or not _positive_number(seconds)):
            reasons.append(f"sample_{index}_invalid_trusted_clock_record")
            continue
        if not math.isclose(seconds, (end - start) / 1e9, rel_tol=1e-8, abs_tol=1e-9):
            reasons.append(f"sample_{index}_duration_mismatch")
        if end_previous is not None and start < end_previous:
            reasons.append(f"sample_{index}_overlapping_measurement")
        end_previous = end
    return reasons


def _failed(sample):
    worker = sample.get("worker", {})
    return (sample.get("scientific_pass") is False or sample.get("artifact_valid") is False
            or worker.get("resource_qualified") is False
            or sample.get("attempt_status", worker.get("attempt_status")) in EXECUTION_FAILURES)


def summarize_group(samples, *, evidence, profile=None):
    """Summarize exactly one B,C,C,B,B,C group without dropping failures.

    A correct candidate with diagnostic timing has null reward/performance even
    if a caller passes a profile name. A genuine candidate failure is still a
    valid zero. Baseline instability is handled by summarize_attempts.
    """
    if profile is not None and profile not in PROFILES:
        raise ValueError("Unknown T3 profile")
    result = {"profile": profile, "evaluation_status": "valid", "performance_status": "not_measured",
              "scientific_pass": None, "baseline_correct": None, "reward": None, "score": None,
              "speedup": None, "optimization_success": None, "baseline_time_ratio": None,
              "candidate_time_ratio": None, "retry_permitted": False, "formal_evidence_valid": False}
    if not isinstance(samples, list) or tuple(row.get("role") for row in samples) != ORDER:
        return dict(result, evaluation_status="evaluation_invalid", performance_status="invalid_protocol",
                    reasons=["required_order_is_B_C_C_B_B_C"])
    if any(row.get("evaluation_status") != "valid" for row in samples):
        return dict(result, evaluation_status="evaluation_invalid", performance_status="invalid_evaluation",
                    reasons=["trusted_evaluation_failed_or_incomplete"])
    if any(not isinstance(row.get("scientific_pass"), bool) for row in samples):
        return dict(result, evaluation_status="evaluation_invalid", performance_status="invalid_evaluation",
                    reasons=["scientific_verdict_missing"])
    baseline = [row for row in samples if row["role"] == "B"]
    candidate = [row for row in samples if row["role"] == "C"]
    result["baseline_correct"] = all(not _failed(row) for row in baseline)
    result["scientific_pass"] = all(row["scientific_pass"] for row in candidate)
    reasons = _formal_evidence(samples, evidence)
    result["formal_evidence_valid"] = not reasons
    if reasons:
        result["reasons"] = reasons
    # Explicit candidate execution/resource/scientific failure is a normal zero,
    # independent of whether an invalid baseline could provide a denominator.
    if any(_failed(row) for row in candidate):
        return dict(result, performance_status="candidate_failed", reward=0, score=0.0,
                    optimization_success=False)
    if reasons:
        return dict(result, performance_status="diagnostic_only", reasons=reasons)
    if not result["baseline_correct"]:
        return dict(result, performance_status="invalid_baseline", reasons=["baseline_failed_correctness_or_resources"],
                    reward=1 if profile == ACCURACY_PROFILE else None)
    times = {role: [row["worker"]["execution_wall_seconds"] for row in rows]
             for role, rows in (("B", baseline), ("C", candidate))}
    result["baseline_time_ratio"] = max(times["B"]) / min(times["B"])
    result["candidate_time_ratio"] = max(times["C"]) / min(times["C"])
    if result["baseline_time_ratio"] > 1.20:
        return dict(result, performance_status="baseline_unstable", retry_permitted=True,
                    reward=1 if profile == ACCURACY_PROFILE else None,
                    reasons=["baseline_max_min_exceeds_1.20"])
    speedup = statistics.median(times["B"]) / statistics.median(times["C"])
    result.update(performance_status="valid", speedup=speedup,
                  optimization_success=speedup >= 1.5,
                  score=100 * min(1.0, max(0.0, math.log(speedup) / math.log(8))))
    if profile == ACCURACY_PROFILE:
        result["reward"] = 1
    elif profile == EFFICIENCY_PROFILE:
        result["reward"] = int(speedup >= 1.5)
    return result


def summarize_attempts(attempts, *, profile=None):
    """Admit one group, or one linked rerun solely for baseline instability.

    Each input has samples, evidence, attempt_id; a rerun also has
    parent_attempt and interference_resolution. The original is always retained.
    """
    if len(attempts) not in (1, 2):
        raise ValueError("T3 permits one original group and at most one complete rerun")
    summaries = [summarize_group(attempt["samples"], evidence=attempt["evidence"], profile=profile)
                 for attempt in attempts]
    first = summaries[0]
    if len(attempts) == 2:
        if first["performance_status"] != "baseline_unstable":
            raise ValueError("A group rerun is permitted only after baseline instability")
        if not attempts[0].get("attempt_id") or attempts[1].get("parent_attempt") != attempts[0]["attempt_id"]:
            raise ValueError("A rerun must link to its original attempt")
        if not attempts[1].get("interference_resolution"):
            raise ValueError("Record the interference investigation before the rerun")
        selected = dict(summaries[1], selected_attempt=1, retry_permitted=False)
        if selected["performance_status"] == "baseline_unstable":
            selected.update(performance_status="baseline_unstable_after_retry", speedup=None,
                            score=None, optimization_success=None)
    else:
        selected = dict(first, selected_attempt=0)
    selected["attempts"] = [{"record": attempt, "summary": summary}
                            for attempt, summary in zip(attempts, summaries)]
    return selected


def calibrate_profile(groups):
    """Select a profile from three complete Jacobi-vs-LU calibration groups.

    groups contains three lists of one/two attempts, as in summarize_attempts.
    This selects the timing policy only; it does not freeze a whole benchmark.
    """
    if len(groups) != 3:
        raise ValueError("Profile calibration requires exactly three full comparison groups")
    summaries = [summarize_attempts(attempts) for attempts in groups]
    for attempts in groups:
        for attempt in attempts:
            if attempt.get("baseline_method") != "jacobi" or attempt.get("candidate_method") != "lu":
                raise ValueError("Calibration comparison must use trusted Jacobi-CG and reused LU")
    invalid = [index for index, summary in enumerate(summaries)
               if summary["evaluation_status"] != "valid" or not summary["formal_evidence_valid"]]
    if invalid:
        return {"profile": None, "status": "calibration_not_formal", "invalid_groups": invalid,
                "groups": summaries, "formal_profile_ready": False}
    # Explicit failures cannot make an efficient reference; they remain in the
    # calibration records and select only the accuracy/diagnostic policy.
    efficient = all(summary["performance_status"] == "valid" and summary["formal_evidence_valid"]
                    and summary["baseline_correct"] and summary["scientific_pass"]
                    and summary["speedup"] >= 1.8 for summary in summaries)
    return {"profile": EFFICIENCY_PROFILE if efficient else ACCURACY_PROFILE,
            "status": "profile_selected", "formal_profile_ready": True,
            "reference_correct_all_groups": all(summary["scientific_pass"] for summary in summaries),
            "groups": summaries}
