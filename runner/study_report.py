"""Read an explicitly indexed, frozen study; never launch research or scoring.

Manifest references use project-relative {path, sha256} objects. A replay
reference wraps the existing verifier diagnostics with formal=true,
split=final-test, freeze_sha256 and registry_sha256. Research-only attempts
remain unscored. No input arrays, agent logs, credentials or solver are read.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics

from .common import file_hash, read_json, write_json
from .report import _csv
from .run_plan import GROUPS, SHA256, _file_ref, validate_start

NONSCIENTIFIC = {"api_failed", "infrastructure_failed", "cancelled"}
NORMAL = {"completed", "research_timeout"}
METRICS = ("score", "E_init", "E_forward", "E_roll", "E_field", "K", "E_res", "E_sol",
           "max_relative_residual", "max_solution_error")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _mean(values):
    return statistics.mean(values) if values and all(_number(value) for value in values) else None


def _difference(final, first):
    return final - first if _number(final) and _number(first) else None


def _read(project, ref):
    path = _file_ref(project, ref)
    if path.suffix != ".json":
        raise ValueError("study records must be JSON files")
    return read_json(path)


def validate_research_result(result, run):
    if result.get("formal") is not True:
        raise ValueError("pilot/nonformal evidence cannot enter a formal study")
    if result.get("replay_split") not in (None, "final-test"):
        raise ValueError("formal study refuses pilot replay labels")
    for key in ("run_id", "task", "group"):
        if key in result and result[key] != run[key]:
            raise ValueError("host result differs from the frozen run identity")
    if result.get("attempt_status") not in NORMAL | NONSCIENTIFIC:
        raise ValueError("missing trusted research attempt outcome")


def _candidate_cpu_seconds(feedback):
    # T3 runs three candidate workers; its legacy cpu_seconds is their median.
    # A present but unknown total must stay unknown, never fall back to it.
    return feedback.get("candidate_cpu_seconds_total", feedback.get("cpu_seconds"))


def post_first_costs(registry, result, events):
    """Request-level costs; unknown/overlapping usage is null, never imputed.

Times are the recorded host/relay Unix timestamps. A request spanning the
first-valid boundary cannot be divided into before/after tokens. Conservative
relay charges are exported separately from measured output usage.
"""
    names = ("wall_seconds", "evaluations", "candidate_cpu_seconds", "api_requests", "input_tokens",
             "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "charged_output_tokens")
    answer = {"after_first_" + name: None for name in names}
    rows = registry.get("evaluations", []) if registry else []
    first = next((row for row in rows if row.get("id") == registry.get("first_id")), None) if registry else None
    if not first or not _number(first.get("completed_at")):
        return answer
    boundary = first["completed_at"]
    end = result.get("research_stop_requested_at")
    if _number(end) and end >= boundary:
        answer["after_first_wall_seconds"] = end - boundary
    if all(_number(row.get("accepted_at")) for row in rows):
        later = [row for row in rows if row["accepted_at"] > boundary]
        answer["after_first_evaluations"] = len(later)
        cpus = [_candidate_cpu_seconds(row.get("result") or {}) for row in later]
        answer["after_first_candidate_cpu_seconds"] = sum(cpus) if all(_number(x) and x >= 0 for x in cpus) else None
    if events is None:
        return answer
    accepted, finished = {}, {}
    for event in events:
        target = accepted if event.get("event") == "request_accepted" else finished if event.get("event") == "request_finished" else None
        if target is not None:
            key = event.get("request_id")
            if not isinstance(key, str) or key in target:
                raise ValueError("duplicate or missing relay request identity")
            target[key] = event
    status = result.get("relay_status") or {}
    if (status.get("request_count") != len(accepted) or status.get("inflight") != 0
            or status.get("evidence_error") is not False
            or not all(_number(row.get("timestamp")) for row in [*accepted.values(), *finished.values()])):
        return answer
    after = [key for key, row in accepted.items() if row["timestamp"] > boundary]
    answer["after_first_api_requests"] = len(after)
    overlap = any(row["timestamp"] <= boundary and
                  (key not in finished or finished[key]["timestamp"] > boundary) for key, row in accepted.items())
    if overlap or any(key not in finished for key in after):
        return answer
    records = [finished[key] for key in after]
    charges = [row.get("charged_output_tokens") for row in records]
    if all(type(x) is int and x >= 0 for x in charges):
        answer["after_first_charged_output_tokens"] = sum(charges)
    if all(row.get("outcome") == "success" and row.get("output_usage_complete") is True for row in records):
        for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            values = [row.get(name) for row in records]
            if all(type(x) is int and x >= 0 for x in values):
                answer["after_first_" + name] = sum(values)
    return answer


def total_costs(registry, result, events):
    """Expose failed attempts' known costs without accepting auxiliary usage."""
    status = result.get("relay_status") or {}
    evaluations = (registry or {}).get("evaluations", [])
    cpus = [_candidate_cpu_seconds(row.get("result") or {}) for row in evaluations]
    counts = status.get("request_count")
    answer = {"total_evaluations": len(evaluations),
              "total_candidate_cpu_seconds": sum(cpus) if all(_number(x) and x >= 0 for x in cpus) else None,
              "total_api_requests": counts if type(counts) is int and counts >= 0 else None,
              "total_charged_output_tokens": status.get("charged_output_tokens"),
              "research_wall_seconds": _difference(result.get("research_stop_requested_at"), (registry or {}).get("started_at")),
              "attempt_wall_seconds": _difference(result.get("finished_at"), result.get("started_at"))}
    finished = [row for row in events or [] if row.get("event") == "request_finished"]
    complete = (events is not None and status.get("evidence_error") is False and status.get("inflight") == 0
                and type(counts) is int and len(finished) == counts
                and all(row.get("outcome") == "success" and row.get("output_usage_complete") is True for row in finished))
    for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        values = [row.get(name) for row in finished]
        answer["total_" + name] = sum(values) if complete and all(type(x) is int and x >= 0 for x in values) else None
    return answer


def _phase(result, freeze_sha):
    phase = result.get("phase") or {}
    if phase.get("formal") is not True or phase.get("split") != "final-test" or phase.get("freeze_sha256") != freeze_sha:
        raise ValueError("replay phase does not match the frozen final-test contract")


def _batches(repeat, task, freeze_sha):
    if task != "poisson":
        _phase(repeat, freeze_sha)
        return [repeat]
    samples = repeat.get("samples")
    if isinstance(samples, dict) and set(samples) == {"B", "C"} and all(len(samples[key]) == 3 for key in samples):
        all_rows, candidates = samples["B"] + samples["C"], samples["C"]
    elif isinstance(samples, list) and [row.get("role") for row in samples] == list("BCCBBC"):
        all_rows, candidates = samples, [row for row in samples if row["role"] == "C"]
    else:
        raise ValueError("T3 replay must retain its three B/C measurements")
    for row in all_rows:
        _phase(row, freeze_sha)
    return candidates


def _replay_history(project, entry, replay, run, freeze_sha):
    """Admit one linked T3 rerun without replacing or relabelling old evidence."""
    history = entry.get("replay_history", [])
    if not history:
        if replay.get("replay_retry_number", 0) != 0 or replay.get("parent_replay") is not None:
            raise ValueError("replay retry requires its original history reference")
        return
    if (run["task"] != "poisson" or not isinstance(history, list) or len(history) != 1
            or type(replay.get("replay_retry_number")) is not int or replay["replay_retry_number"] != 1
            or replay.get("parent_replay") != history[0]
            or not isinstance(replay.get("interference_resolution"), str) or not replay["interference_resolution"].strip()):
        raise ValueError("only one investigated, linked T3 replay retry is permitted")
    original = _read(project, history[0])
    for wrapper in (original, replay):
        if (wrapper.get("formal") is not True or wrapper.get("split") != "final-test"
                or wrapper.get("freeze_sha256") != freeze_sha
                or wrapper.get("registry_sha256") != entry["registry"]["sha256"]
                or wrapper.get("run_id") != entry["run_id"] or wrapper.get("attempt_id") != entry["attempt_id"]):
            raise ValueError("replay retry differs from its original registry, freeze or session")
    if original.get("replay_retry_number", 0) != 0 or original.get("parent_replay") is not None:
        raise ValueError("a replay retry cannot be retried again")
    before, after = original["diagnostics"], replay["diagnostics"]
    eligible, changed = False, False
    for role in ("first", "final"):
        prior, current = before.get(role) or {}, after.get(role) or {}
        old_repeats = prior.get("repeats", [])
        permitted = (len(old_repeats) == 1 and old_repeats[0].get("performance_status") == "baseline_unstable"
                     and old_repeats[0].get("retry_permitted") is True)
        eligible = eligible or permitted
        if current == prior or not current and after.get("evaluation_status") != "valid":
            continue
        if (not permitted or any(current.get(key) != prior.get(key) for key in ("checkpoint_id", "source_hash"))
                or current.get("replay_retry") is not True or len(current.get("repeats", [])) != 1):
            raise ValueError("only an originally unstable checkpoint can be remeasured")
        repeated, old_group = current["repeats"][0], old_repeats[0]
        attempts = repeated.get("attempts")
        if (not isinstance(attempts, list) or len(attempts) != 2
                or attempts[0].get("record") != old_group.get("protocol_attempt")
                or not isinstance(attempts[0].get("record"), dict)
                or attempts[1].get("record") != repeated.get("protocol_attempt")
                or not isinstance(attempts[1].get("record"), dict)
                or attempts[1]["record"].get("parent_attempt") != attempts[0]["record"].get("attempt_id")
                or not attempts[0]["record"].get("attempt_id")
                or attempts[1]["record"].get("interference_resolution") != replay["interference_resolution"]
                or repeated.get("selected_attempt") != 1 or repeated.get("retry_permitted") is not False):
            raise ValueError("T3 retry must retain both linked protocol attempts")
        _batches(old_group, "poisson", freeze_sha)
        _batches(repeated, "poisson", freeze_sha)
        changed = True
    if not eligible or (after.get("evaluation_status") == "valid" and not changed):
        raise ValueError("replay retry lacks an original unstable checkpoint and new measurements")


def _case_rows(batch, case_ids):
    supplied = batch.get("cases", [])
    by_id = {row.get("id"): row for row in supplied}
    if len(by_id) != len(supplied) or set(by_id) - set(case_ids):
        raise ValueError("duplicate or foreign replay case ID")
    invalid = batch.get("evaluation_status") != "valid"
    rows = [{"case_id": identifier, "observed": identifier in by_id,
             **({key: value for key, value in by_id[identifier].items() if key != "id"} if identifier in by_id else
                {"score": None if invalid else 0.0, "scientific_pass": None if invalid else False,
                 "artifact_valid": False, "reason": "trusted_evaluation_incomplete" if invalid else "missing_or_failed_batch_case"})}
            for identifier in case_ids]
    if not invalid and _number(batch.get("score")):
        calculated = _mean([row.get("score") for row in rows])
        if calculated is None or not math.isclose(batch["score"], calculated, abs_tol=1e-9):
            raise ValueError("batch score does not preserve the complete case denominator")
    if not invalid and batch.get("reward") is not None and batch["reward"] != int(all(row.get("scientific_pass") is True for row in rows)):
        raise ValueError("batch reward disagrees with all-case correctness")
    return rows


def _checkpoint(role, record, registry, run, freeze_sha, case_ids, first=None):
    identifier = registry.get(role + "_id")
    if not isinstance(record, dict) or record.get("checkpoint_id") != identifier:
        raise ValueError("verifier selection differs from closed registry")
    selected = next((row for row in registry["evaluations"] if row["id"] == identifier), None)
    summary = {"checkpoint_role": role, "checkpoint_id": identifier, "source_hash": record.get("source_hash"),
               "reused_from": record.get("reused_from"), "replay_count": record.get("replay_count"),
               "score": record.get("score"), "reward": record.get("reward"), "case_denominator": len(case_ids),
               "evaluation_status": record.get("evaluation_status", "valid"), "reason": record.get("reason"),
               "performance_status": None, "artifact_valid": None, "scientific_pass": None}
    if identifier is None or selected and selected.get("artifact_valid") is False:
        if record.get("replay_count") != 0 or record.get("score") != 0 or record.get("reward") != 0:
            raise ValueError("missing/invalid submission must be an explicit zero without replay")
        summary.update(source_hash=selected.get("source_hash") if selected else None,
                       score=None if role == "first" and identifier is None else 0.0, passed=0.0,
                       artifact_valid=False, scientific_pass=False)
        rows = [] if role == "first" and identifier is None else [dict(row, repeat=0, observed=False)
                for row in _case_rows({"evaluation_status": "valid"}, case_ids)]
        return summary, rows
    if (not selected or not isinstance(selected.get("source_hash"), str) or not SHA256.fullmatch(selected["source_hash"])
            or record.get("source_hash") != selected.get("source_hash")):
        raise ValueError("replay source hash differs from registered source")
    if record.get("reused_from") is not None:
        if (role != "final" or first is None or record["reused_from"] != first[0]["checkpoint_id"]
                or record["source_hash"] != first[0]["source_hash"] or record.get("replay_count") != 0
                or any(record.get(key) != first[0].get(key) for key in ("score", "reward"))):
            raise ValueError("invalid same-source replay reuse")
        # Validate the inherited repeats too, but never count them as fresh runs.
        for repeat in record.get("repeats", []):
            _batches(repeat, run["task"], freeze_sha)
        summary["passed"] = first[0]["passed"]
        summary.update({key: first[0][key] for key in ("performance_status", "artifact_valid", "scientific_pass")})
        return summary, []
    expected = 1 if run["task"] == "poisson" else 3
    repeats = record.get("repeats", [])
    if record.get("replay_count") != expected or len(repeats) != expected:
        raise ValueError("checkpoint does not contain the prescribed replay count")
    rows, batch_passes = [], []
    for repeat in repeats:
        if repeat.get("checkpoint_id") != identifier or repeat.get("source_hash") != summary["source_hash"]:
            raise ValueError("individual replay source differs from its checkpoint")
        for batch in _batches(repeat, run["task"], freeze_sha):
            batch_rows = _case_rows(batch, case_ids)
            batch_passes.append(sum(row.get("scientific_pass") is True for row in batch_rows)
                                if batch.get("evaluation_status") == "valid" else None)
            rows.extend(dict(row, repeat=len(batch_passes)) for row in batch_rows)
    summary["passed"] = _mean(batch_passes)
    summary["performance_status"] = sorted({item.get("performance_status") for item in repeats if item.get("performance_status")}) or None
    summary["scientific_pass"] = all(value == len(case_ids) for value in batch_passes) if all(value is not None for value in batch_passes) else None
    summary["artifact_valid"] = all(row["artifact_valid"] for row in rows) if all(type(row.get("artifact_valid")) is bool for row in rows) else None
    if any(repeat.get("evaluation_status") != "valid" for repeat in repeats):
        if summary["score"] is not None or summary["reward"] is not None:
            raise ValueError("invalid trusted replay cannot have a numeric verdict")
        summary["evaluation_status"] = "invalid"
    expected_score = _mean([repeat.get("score") for repeat in repeats])
    expected_reward = int(all(repeat.get("reward") == 1 for repeat in repeats)) if all(repeat.get("reward") in (0, 1) for repeat in repeats) else None
    if (summary["score"] is None) != (expected_score is None) or _number(expected_score) and not math.isclose(summary["score"], expected_score, abs_tol=1e-9):
        raise ValueError("checkpoint score differs from trusted replay aggregation")
    if summary["reward"] != expected_reward:
        raise ValueError("checkpoint reward differs from trusted replay aggregation")
    return summary, rows


def _metric_means(rows):
    return {key: _mean([row.get(key) for row in rows]) for key in METRICS}


def group_summary(plan, attempts):
    rows, comparisons = [], []
    for task in ("heat", "ode", "poisson"):
        indexed = {}
        for group in GROUPS:
            all_attempts = [row for row in attempts if row["task"] == task and row["group"] == group]
            scientific = [row for row in all_attempts if row["scientific_evaluated"]]
            scores = [row["final_score"] for row in scientific if _number(row["final_score"])]
            planned = sum(run["task"] == task and run["group"] == group for run in plan["runs"])
            indexed[group] = {row["repeat"]: row for row in scientific}
            rows.append({"task": task, "group": group, "planned_sessions": planned, "attempts": len(all_attempts),
                         "scientific_sessions": len(scientific), "score_n": len(scores),
                         "unscored_scientific_sessions": len(scientific) - len(scores),
                         "non_scientific_attempts": sum(row["attempt_status"] in NONSCIENTIFIC for row in all_attempts),
                         "unscored_attempts": sum(not row["scientific_evaluated"] for row in all_attempts),
                         "reward_zero_sessions": sum(row["final_reward"] == 0 for row in scientific),
                         "score_zero_sessions": sum(row["final_score"] == 0 for row in scientific),
                         "score_median": statistics.median(scores) if scores else None,
                         "score_min": min(scores) if scores else None, "score_max": max(scores) if scores else None,
                         "interpretation": "n=1 is descriptive only" if planned == 1 else "n=3 is exploratory; no broad significance claim"})
        for left, right in (("g1", "g3"), ("g2", "g3"), ("g1", "g2")):
            pairs = [(repeat, indexed[left][repeat], indexed[right][repeat])
                     for repeat in sorted(indexed[left].keys() & indexed[right].keys())]
            deltas = [{"repeat": repeat, "delta_score": _difference(a["final_score"], b["final_score"]),
                       "delta_reward": _difference(a["final_reward"], b["final_reward"])} for repeat, a, b in pairs]
            scores = [row["delta_score"] for row in deltas if _number(row["delta_score"])]
            comparisons.append({"task": task, "contrast": left + "-" + right, "paired_scientific_n": len(pairs),
                                "paired_score_n": len(scores), "pairs": deltas,
                                "median_delta_score": statistics.median(scores) if scores else None,
                                "min_delta_score": min(scores) if scores else None, "max_delta_score": max(scores) if scores else None})
    return rows, comparisons


def export_study(project, plan_path, manifest_path, output):
    project, plan_path, manifest_path, output = map(Path, (project, plan_path, manifest_path, output))
    plan, manifest = read_json(plan_path), read_json(manifest_path)
    validate_start(plan, project)  # Public package/freeze/evidence validation only.
    if manifest.get("schema_version") != 1 or _file_ref(project, manifest.get("run_plan")).resolve() != plan_path.resolve():
        raise ValueError("manifest must bind the exact frozen run plan")
    if not isinstance(manifest.get("attempts"), list):
        raise ValueError("study manifest must explicitly index all attempts")
    planned = {run["run_id"]: run for run in plan["runs"]}
    attempts, checkpoints, cases, case_deltas, evaluations = [], [], [], [], []
    seen, previous, completed = {}, {}, set()
    for entry in manifest["attempts"]:
        run = planned.get(entry.get("run_id"))
        attempt_id = entry.get("attempt_id")
        if not run or not isinstance(attempt_id, str) or not attempt_id or attempt_id in seen:
            raise ValueError("unknown run or duplicate attempt identity")
        parent = entry.get("parent_attempt")
        if parent != previous.get(run["run_id"]):
            raise ValueError("retries must link to the preceding attempt of the same planned run")
        if parent and seen[parent]["attempt_status"] not in NONSCIENTIFIC:
            raise ValueError("a scientific result, including zero, cannot be replaced by a retry")
        result = _read(project, entry.get("result"))
        validate_research_result(result, run)
        registry = _read(project, entry["registry"]) if entry.get("registry") else None
        status = result["attempt_status"]
        post_registry_failure = False
        if registry is not None:
            registry_status = registry.get("attempt_status")
            post_registry_failure = (status == "infrastructure_failed" and result.get("post_registry_failure") is True
                                     and result.get("status") == "research_invalid" and registry_status in NORMAL
                                     and result.get("registry_attempt_status") == registry_status
                                     and isinstance(result.get("reason"), str) and bool(result["reason"].strip()))
            if (registry.get("closed") is not True or registry.get("task") != run["task"] or registry.get("condition") != run["group"]
                    or (registry.get("attempt_outcome") or {}).get("status") != registry_status
                    or (registry_status != status and not post_registry_failure)
                    or (result.get("post_registry_failure") is True and not post_registry_failure)):
                raise ValueError("research registry is open or differs from the host outcome")
        elif status not in NONSCIENTIFIC or result.get("post_registry_failure") is True:
            raise ValueError("normal research requires a closed registry")
        common = {key: run[key] for key in ("run_id", "task", "group", "repeat")}
        common.update(attempt_id=attempt_id, parent_attempt=parent, formal=True)
        row = {**common, "attempt_status": status, "research_status": result.get("status"), "cost_usd": None,
               "registry_attempt_status": registry.get("attempt_status") if registry else None,
               "post_registry_failure": post_registry_failure,
               "research_valid": status in NORMAL and result.get("status") == "research_frozen"
                                 and not result.get("cleanup_errors") and not result.get("bridge_errors"),
               "scientific_evaluated": False, "evaluation_status": "not_run", "first_score": None, "final_score": None,
               "first_reward": None, "final_reward": None, "delta_score": None, "delta_passed": None,
               "first_id": registry.get("first_id") if registry else None,
               "final_id": registry.get("final_id") if registry else None,
               "selection_reason": registry.get("selection_reason") if registry else None,
               "result_evidence": entry["result"], "registry_evidence": entry.get("registry"), "replay_evidence": entry.get("replay"),
               "replay_history_evidence": entry.get("replay_history", []),
               "failure_reason": result["reason"] if post_registry_failure else
                                 (registry.get("attempt_outcome") or {}).get("reason") if registry else result.get("error")}
        events = None
        if entry.get("relay_events"):
            events = [json.loads(line) for line in _file_ref(project, entry["relay_events"]).read_text().splitlines()]
        row.update(post_first_costs(registry, result, events))
        row.update(total_costs(registry, result, events))
        public = {}
        for evaluation in (registry or {}).get("evaluations", []):
            feedback = evaluation.get("result") or {}
            evaluations.append({**common, "candidate_id": evaluation["id"], "source_hash": evaluation.get("source_hash"),
                                "accepted_at": evaluation.get("accepted_at"), "completed_at": evaluation.get("completed_at"),
                                "artifact_valid": evaluation.get("artifact_valid"), "attempt_status": feedback.get("attempt_status"),
                                "cpu_seconds": _candidate_cpu_seconds(feedback), "wall_seconds": feedback.get("wall_seconds"),
                                "public_check_status": feedback.get("public_check_status"), "public_cases": feedback.get("cases")})
            public[evaluation["id"]] = _metric_means(feedback.get("cases", []))
        row["public_metric_deltas"] = {key: _difference(public.get(row["final_id"], {}).get(key), public.get(row["first_id"], {}).get(key)) for key in METRICS}
        if entry.get("replay"):
            replay = _read(project, entry["replay"])
            freeze_ref = plan["freezes"][run["task"]]
            if (replay.get("formal") is not True or replay.get("split") != "final-test"
                    or replay.get("freeze_sha256") != freeze_ref["sha256"]
                    or registry is None or replay.get("registry_sha256") != entry["registry"]["sha256"]):
                raise ValueError("replay must bind final-test, the task freeze and closed registry")
            _replay_history(project, entry, replay, run, freeze_ref["sha256"])
            diagnostic = replay["diagnostics"]
            row["evaluation_status"] = diagnostic.get("evaluation_status")
            if row["research_valid"]:
                frozen = _read(project, freeze_ref)
                case_ids = sorted({name.split("/")[1] for name in frozen["data"]["final-test"]["input_hashes"] if name.startswith("cases/")})
                if len(case_ids) != 12:
                    raise ValueError("frozen final-test hashes must identify all 12 cases")
                if diagnostic.get("evaluation_status") != "valid":
                    if diagnostic.get("score") is not None or diagnostic.get("reward") is not None:
                        raise ValueError("trusted scoring failure must retain a null verdict")
                    row["failure_reason"] = diagnostic.get("reason")
                    for role in ("first", "final"):
                        record = diagnostic.get(role) or {}
                        selected = next((item for item in registry["evaluations"] if item["id"] == registry.get(role + "_id")), None)
                        if record and (record.get("checkpoint_id") != registry.get(role + "_id") or
                                       record.get("source_hash") is not None and record["source_hash"] != (selected or {}).get("source_hash")):
                            raise ValueError("failed verifier record differs from registered checkpoint")
                        checkpoint = {**common, "checkpoint_role": role, "checkpoint_id": registry.get(role + "_id"),
                                      "source_hash": record.get("source_hash"), "replay_count": record.get("replay_count"),
                                      "evaluation_status": "invalid", "score": None, "reward": None,
                                      "reason": diagnostic.get("reason")}
                        checkpoints.append(checkpoint)
                        batch_number = 0
                        for repeat in record.get("repeats", []):
                            for batch in _batches(repeat, run["task"], freeze_ref["sha256"]):
                                batch_number += 1
                                cases.extend({**common, "checkpoint_role": role, "checkpoint_id": checkpoint["checkpoint_id"],
                                              "source_hash": checkpoint["source_hash"], "repeat": batch_number, **case}
                                             for case in _case_rows(batch, case_ids))
                    row["iteration_status"] = "unavailable"
                    attempts.append(row)
                    seen[attempt_id], previous[run["run_id"]] = row, attempt_id
                    continue
                first = _checkpoint("first", diagnostic.get("first"), registry, run, freeze_ref["sha256"], case_ids)
                final = _checkpoint("final", diagnostic.get("final"), registry, run, freeze_ref["sha256"], case_ids, first)
                if any(diagnostic.get(key) != final[0][key] for key in ("score", "reward")):
                    raise ValueError("verifier aggregate differs from final checkpoint")
                valid = diagnostic.get("evaluation_status") == "valid" and all(item[0]["evaluation_status"] == "valid" for item in (first, final))
                row["scientific_evaluated"] = valid
                for role, (checkpoint, case_records) in (("first", first), ("final", final)):
                    checkpoints.append({**common, **checkpoint})
                    cases.extend({**common, "checkpoint_role": role, "checkpoint_id": checkpoint["checkpoint_id"],
                                  "source_hash": checkpoint["source_hash"], **case} for case in case_records)
                    row.update({role + "_source_hash": checkpoint["source_hash"], role + "_replay_count": checkpoint["replay_count"],
                                role + "_reused_from": checkpoint["reused_from"], role + "_score": checkpoint["score"] if valid else None,
                                role + "_reward": checkpoint["reward"] if valid else None,
                                role + "_performance_status": checkpoint["performance_status"],
                                role + "_artifact_valid": checkpoint["artifact_valid"], role + "_scientific_pass": checkpoint["scientific_pass"]})
                if valid and row["first_id"] is not None:
                    row["delta_score"] = _difference(row["final_score"], row["first_score"])
                    row["delta_passed"] = _difference(final[0]["passed"], first[0]["passed"])
                    final_rows = first[1] if final[0]["reused_from"] else final[1]
                    for identifier in case_ids:
                        selected_rows = [[item for item in values if item["case_id"] == identifier] for values in (first[1], final_rows)]
                        a, b = map(_metric_means, selected_rows)
                        pass_rates = [_mean([int(item["scientific_pass"]) if type(item.get("scientific_pass")) is bool else None for item in values]) for values in selected_rows]
                        case_deltas.append({**common, "case_id": identifier, "delta_pass_rate": _difference(pass_rates[1], pass_rates[0]),
                                            **{"delta_" + key: _difference(b[key], a[key]) for key in METRICS}})
                if valid:
                    completed.add(run["run_id"])
            else:
                row["evaluation_status"] = "invalid_research_attempt"
        delta = row["delta_score"]
        row["iteration_status"] = ("not_observed_same_source" if row.get("first_source_hash") and row.get("first_source_hash") == row.get("final_source_hash")
                                   else "improved" if _number(delta) and delta > 0 else "degraded" if _number(delta) and delta < 0
                                   else "unchanged" if delta == 0 else "unavailable")
        attempts.append(row)
        seen[attempt_id], previous[run["run_id"]] = row, attempt_id
    groups, contrasts = group_summary(plan, attempts)
    summary = {"formal": True, "plan_sha256": file_hash(plan_path), "manifest_sha256": file_hash(manifest_path),
               "planned_sessions": len(plan["runs"]), "attempts": len(attempts), "scientific_sessions": len(completed),
               "scientific_guidance_cells": len({(row["task"], row["group"]) for row in attempts if row["scientific_evaluated"]}),
               "pending_run_ids": [run["run_id"] for run in plan["runs"] if run["run_id"] not in completed],
               "case_rows": len(cases), "checkpoint_rows": len(checkpoints), "groups": groups, "contrasts": contrasts,
               "limitations": ["Independent research sessions are the replication unit; cases/replays/evaluations are not independent samples.",
                               "Contrasts are within task and paired repeat only; n=1 descriptive, n=3 exploratory.",
                               "First-to-final changes do not identify the causal effect of feedback.",
                               "Missing costs remain null; relay reservation charges are not token usage or currency."]}
    output.mkdir(parents=True, exist_ok=False)
    for name, values in (("attempts", attempts), ("checkpoints", checkpoints), ("cases", cases), ("case-deltas", case_deltas),
                         ("public-evaluations", evaluations), ("groups", groups), ("contrasts", contrasts)):
        fields = list(dict.fromkeys(key for row in values for key in row)) or ["attempt_id"]
        _csv(output / (name + ".csv"), values, fields)
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "plan", "manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_study(args.project, args.plan, args.manifest, args.output), allow_nan=False))


if __name__ == "__main__":
    main()
