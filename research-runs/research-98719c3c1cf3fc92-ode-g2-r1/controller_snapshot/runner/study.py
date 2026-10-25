"""Host study controller: public research and explicit final replay are separate."""
from __future__ import annotations

import argparse
import asyncio
import copy
from contextlib import contextmanager
import fcntl
import math
from pathlib import Path
import re
import time
import uuid

from harbor.models.verifier.result import VerifierResult
from harbor.verifier.base import BaseVerifier

from .common import canonical, digest, file_hash, read_json, tree_hashes, write_json
from .calibrate import METHODS, FIXED
from .phase import checked_hashes, guard_replay
from .registry import Registry
from .run_plan import _file_ref, thinking_truncation_retry, validate_start

NORMAL = {"completed", "research_timeout"}
FAILED = {"api_failed", "infrastructure_failed", "cancelled"}


def reference(project, path):
    path = Path(path).resolve(strict=True)
    return {"path": path.relative_to(Path(project).resolve()).as_posix(), "sha256": file_hash(path)}


def frozen_plan(project, plan_path):
    project, plan_path = Path(project).resolve(), Path(plan_path).resolve(strict=True)
    ref = reference(project, plan_path)
    plan = read_json(_file_ref(project, ref))
    validate_start(plan, project)
    return plan, ref


def session_spec(project, plan_path, run_id, attempt_id, parent_attempt=None):
    """Construct immutable settings from the validated plan, never CLI overrides."""
    project = Path(project).resolve()
    plan, plan_ref = frozen_plan(project, plan_path)
    rows = [row for row in plan["runs"] if row["run_id"] == run_id]
    if len(rows) != 1:
        raise ValueError("run ID is absent from the frozen matrix")
    row = rows[0]
    identity = re.escape(run_id) + r"-a\d{3}"
    if not re.fullmatch(identity, attempt_id) or parent_attempt is not None and not re.fullmatch(identity, parent_attempt):
        raise ValueError("attempt identity must belong to the planned run")
    freeze = read_json(_file_ref(project, plan["freezes"][row["task"]]))
    policy = read_json(_file_ref(project, plan["tool_config"]["runtime_enforcement"]))
    thinking_max = (plan["model"]["thinking"] == {"type": "enabled"}
                    and plan["model"].get("output_config") == {"effort": "max"}
                    and plan["model"]["temperature"] is None)
    disabled = (plan["model"]["thinking"] in ("off", {"type": "disabled"})
                and plan["model"]["temperature"] in (None, 0)
                and plan["model"].get("output_config") is None)
    if not (thinking_max or disabled):
        raise ValueError("native relay requires verified disabled-thinking or thinking-max policy")
    base = project / "research-runs" / run_id
    output = base if parent_attempt is None else base / "retries" / attempt_id
    prompt = ((project / "prompts" / row["task"] / "common.md").read_bytes() + b"\n\n"
              + (project / "prompts" / row["task"] / (row["group"] + ".md")).read_bytes())
    if digest(prompt) != plan["tasks"][row["task"]]["combined_prompt_hashes"][row["group"]]:
        raise ValueError("combined research prompt changed")
    settings = {"formal": True, **{key: row[key] for key in ("task", "group", "run_id", "repeat")},
                **({"thinking_effort": "max"} if thinking_max else {}),
                "research_seconds": 1800, "max_evaluations": 20, "research_vcpu": 4,
                "research_memory_bytes": 4 * 1024**3, "max_turns": None,
                "attempt_id": attempt_id, "parent_attempt": parent_attempt,
                "session_id": row["session_id"] if parent_attempt is None else str(uuid.uuid5(uuid.UUID(row["session_id"]), attempt_id)),
                "plan_ref": plan_ref, "prompt": prompt.decode("utf-8"),
                "prompt_hashes": plan["tasks"][row["task"]]["prompt_hashes"],
                "session_output_limit": plan["model"]["output_token_limit"],
                "request_output_limit": min(4096, plan["model"]["output_token_limit"]),
                "relay_ttl_seconds": 2700,
                "max_requests": plan.get("runtime_policy", {}).get("max_requests", 512),
                "expected_system_sha256": policy["wire_system_sha256"],
                "expected_tools_sha256": policy["wire_tools_sha256"],
                "expected_compaction_system_sha256": policy.get("native_compaction", {}).get("wire_system_sha256"),
                "expected_compaction_sources": policy.get("native_compaction", {}).get("source_sha256", {})}
    return {"project": str(project), "plan_path": str(Path(plan_path).resolve()), "settings": settings,
            "output_root": str(output), "public_input": str(project / "tasks" / row["task"] / "environment/public-dev"),
            "research_image": plan["research_images"][row["task"]]["image_id"], "numeric_image": freeze["image_id"]}


def validate_session(spec):
    settings = spec["settings"]
    expected = session_spec(spec["project"], spec["plan_path"], settings["run_id"], settings["attempt_id"], settings["parent_attempt"])
    if spec != expected:
        raise ValueError("formal session differs from its frozen plan")
    return spec


class RegistrationVerifier(BaseVerifier):
    """Native Harbor verifier hook records registration only; it never scores."""
    def __init__(self, *, registry_root, task_name, **kwargs):
        super().__init__(**kwargs)
        self.registry = Registry(Path(registry_root).resolve(strict=True))
        self.task_name = task_name

    async def verify(self):
        record = {"formal": True, "registration_status": "invalid", "evaluation_status": "not_run", "score": None, "reward": None}
        try:
            state = read_json(self.registry.root / "state.json")
            mode = self.task.config.verifier.environment_mode
            if getattr(mode, "value", mode) != "separate" or state.get("closed") is not True:
                raise ValueError("registration requires a separate verifier and closed registry")
            if state.get("task") != self.task_name:
                raise ValueError("registration task differs from the host registry")
            artifacts = self.trial_paths.artifacts_dir
            if artifacts.exists() and any(path.is_symlink() or
                    (path.is_file() and path != artifacts / "manifest.json") for path in artifacts.rglob("*")):
                raise ValueError("unexpected automatic research artifact transfer")
            observed = await self.environment.exec(command="if [ -d /logs/artifacts ]; then find /logs/artifacts -mindepth 1 -print -quit; fi")
            if observed.return_code or (observed.stdout or "").strip():
                raise ValueError("verifier artifact directory is not empty")
            if self.registry.root.is_relative_to(Path(state["workspace"]).resolve()):
                raise ValueError("host registry is inside the research workspace")
            if state.get("attempt_status") not in NORMAL | FAILED or (state.get("attempt_outcome") or {}).get("status") != state["attempt_status"]:
                raise ValueError("registration requires an explicit trusted research outcome")
            for identifier in (state["first_id"], state["final_id"]):
                if identifier is None:
                    continue
                row = next((row for row in state["evaluations"] if row["id"] == identifier), None)
                if row is None or "completed_at" not in row:
                    raise ValueError("selection is absent from completed host evaluations")
                if row.get("source_hash") is not None:
                    snapshot = self.registry.verified_snapshot(identifier)
                    if digest(canonical(tree_hashes(snapshot))) != row["source_hash"]:
                        raise ValueError("registered source hash changed")
            record.update(registration_status="registered", registry_sha256=file_hash(self.registry.root / "state.json"),
                          first_id=state["first_id"], final_id=state["final_id"], attempt_status=state["attempt_status"])
        except Exception as exc:
            record["reason"] = f"{type(exc).__name__}: {exc}"
        write_json(self.trial_paths.verifier_dir / "research-registration.json", record)
        return VerifierResult(rewards=None)


@contextmanager
def ledger(project, plan, plan_ref):
    """One host operation owns a study at a time; unfinished rows stay visible."""
    root = Path(project) / "research-runs" / plan["plan_id"]
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = root / "manifest.json"
        value = read_json(path) if path.exists() else {"schema_version": 1, "run_plan": plan_ref, "attempts": [], "finalized_tasks": []}
        if value["run_plan"] != plan_ref:
            raise ValueError("study ledger is bound to a different plan hash")
        yield path, value


def read_attempt(project, entry):
    value = read_json(_file_ref(project, entry["result"]))
    if any(value.get(key) != entry[key] for key in ("run_id", "attempt_id", "parent_attempt")):
        raise ValueError("attempt result differs from ledger identity")
    if value.get("formal") is not True or value.get("attempt_status") not in NORMAL | FAILED:
        raise ValueError("attempt has no terminal trusted host outcome")
    return value


def retain_post_registry_failure(result, output):
    """Record a later host failure without rewriting immutable research state."""
    path = Path(output) / "registry/state.json"
    invalid = (result.get("status") != "research_frozen" or result.get("cleanup_errors") or result.get("bridge_errors"))
    if not invalid or not path.is_file():
        return result
    state = read_json(path)
    original = state.get("attempt_status")
    if (state.get("closed") is True and original in NORMAL
            and (state.get("attempt_outcome") or {}).get("status") == original
            and result.get("attempt_status") in NORMAL | {"infrastructure_failed", "cancelled"}):
        result = dict(result, attempt_status="infrastructure_failed", status="research_invalid",
                      registry_attempt_status=original, post_registry_failure=True,
                      reason="Host cleanup, verifier, or controller failed after the research registry was closed",
                      evaluation_status="not_run", score=None, reward=None)
    return result


async def start(project, plan_path, run_id, *, retry_of=None, launch=None):
    """Run one predeclared session. Every launched attempt remains indexed."""
    project = Path(project).resolve()
    plan, plan_ref = frozen_plan(project, plan_path)  # Before any Docker/API work.
    row = next((row for row in plan["runs"] if row["run_id"] == run_id), None)
    if row is None:
        raise ValueError("unknown planned run ID")
    with ledger(project, plan, plan_ref) as (manifest_path, manifest):
        if row["task"] in manifest["finalized_tasks"]:
            raise ValueError("task research is permanently closed after final replay admission")
        prior = [entry for entry in manifest["attempts"] if entry["run_id"] == run_id]
        retry_authorization = None
        if prior:
            previous = read_attempt(project, prior[-1])
            if retry_of == prior[-1]["attempt_id"] and previous["attempt_status"] == "completed":
                retry_authorization = thinking_truncation_retry(project, plan, prior[-1])
            if retry_of != prior[-1]["attempt_id"] or (previous["attempt_status"] not in FAILED and retry_authorization is None):
                raise ValueError("only an explicit linked retry of a non-scientific failure is permitted")
        elif retry_of is not None:
            raise ValueError("retry parent does not exist")
        seen_runs = {entry["run_id"] for entry in manifest["attempts"]}
        for earlier in plan["runs"][:row["sequence"] - 1]:
            if earlier["run_id"] not in seen_runs:
                raise ValueError("run order differs from the predeclared matrix")
        for entry in manifest["attempts"]:
            read_attempt(project, entry)
        attempt_id = run_id + f"-a{len(prior) + 1:03d}"
        spec = session_spec(project, plan_path, run_id, attempt_id, retry_of)
        host_path = manifest_path.parent / "host-attempts" / (attempt_id + ".json")
        pending = {"formal": True, **{key: row[key] for key in ("run_id", "task", "group", "repeat")},
                   "attempt_id": attempt_id, "parent_attempt": retry_of, "status": "research_running",
                   "attempt_status": "running", "evaluation_status": "not_run", "replay_split": None,
                   "score": None, "reward": None, "model_run_started": False, "started_at": time.time()}
        write_json(host_path, pending)
        entry = {"run_id": run_id, "attempt_id": attempt_id, "parent_attempt": retry_of, "result": reference(project, host_path)}
        if retry_authorization:
            entry["retry_authorization"] = retry_authorization
        manifest["attempts"].append(entry)
        write_json(manifest_path, manifest)
        try:
            if launch is None:
                from .harbor_pilot import run_research_session
                launch = run_research_session
            result = await launch(spec)
            if result.get("attempt_status") not in NORMAL | FAILED:
                raise ValueError("controller omitted the terminal host outcome")
            if any(result.get(key) != pending[key] for key in ("formal", "run_id", "attempt_id", "parent_attempt", "task", "group")):
                raise ValueError("controller result differs from planned session")
        except BaseException as exc:
            result = dict(pending, status="research_invalid", attempt_status="cancelled" if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) else "infrastructure_failed",
                          error=f"{type(exc).__name__}: {exc}"[:2048], finished_at=time.time())
        result = retain_post_registry_failure(result, spec["output_root"])
        if retry_authorization:
            result = dict(result, retry_authorization=retry_authorization, retry_kind="thinking_truncation_protocol_repair")
        write_json(host_path, result)
        entry["result"] = reference(project, host_path)
        output = Path(spec["output_root"])
        for key, path in (("registry", output / "registry/state.json"), ("relay_events", output / "relay-evidence/evidence/events.jsonl")):
            if path.exists():
                entry[key] = reference(project, path)
        write_json(manifest_path, manifest)
        return result


def closed_research(project, entry, row):
    result = read_attempt(project, entry)
    if (result["attempt_status"] not in NORMAL or result.get("status") != "research_frozen"
            or result.get("cleanup_errors") or result.get("bridge_errors")):
        raise ValueError("all related research must finish validly before final data can be read")
    state_path = _file_ref(project, entry.get("registry"))
    state = read_json(state_path)
    if (state.get("closed") is not True or state.get("task") != row["task"] or state.get("condition") != row["group"]
            or state.get("attempt_status") != result["attempt_status"]
            or (state.get("attempt_outcome") or {}).get("status") != result["attempt_status"]):
        raise ValueError("final replay requires an unchanged closed host registry")
    registry = Registry(state_path.parent)
    for role in ("first", "final"):
        identifier = state.get(role + "_id")
        if identifier is None:
            continue
        registered = next((item for item in state["evaluations"] if item["id"] == identifier), None)
        if not registered or "completed_at" not in registered:
            raise ValueError("selected source is not a completed registered candidate")
        if registered.get("source_hash") is not None:
            source = registry.verified_snapshot(identifier)
            if digest(canonical(tree_hashes(source))) != registered["source_hash"]:
                raise ValueError("selected source differs from its frozen registration hash")
    return registry, state


def completed_task(project, plan, manifest, task):
    """The common pre-hidden-data barrier for research and author baselines."""
    latest = {entry["run_id"]: entry for entry in manifest["attempts"]}
    for row in (row for row in plan["runs"] if row["task"] == task):
        if row["run_id"] not in latest:
            raise ValueError("all related research must finish before final data can be read")
        closed_research(project, latest[row["run_id"]], row)
    return latest


def score_checkpoints(registry, state, config, *, execute=None, diagnostics=None):
    """Replay closed first/final selections without creating a research session."""
    if execute is None:
        from .replay import replay_checkpoint
        execute = replay_checkpoint
    if diagnostics is None:
        diagnostics = {}
    diagnostics.update(adapter="study-final", evaluation_status="invalid", score=None, reward=None,
                       first=None, final=None, selection_reason=state.get("selection_reason"))
    cache = {}
    for role in ("first", "final"):
        identifier = state[role + "_id"]
        row = next((item for item in state["evaluations"] if item["id"] == identifier), None)
        if row and (row.get("result") or {}).get("attempt_status") in ("infrastructure_failed", "infrastructure_error"):
            raise ValueError("selected public evaluation failed in trusted infrastructure; no scientific zero is assigned")
        if identifier is None or row and row.get("artifact_valid") is False:
            diagnostics[role] = {"checkpoint_id": identifier, "source_hash": row.get("source_hash") if row else None,
                                 "score": 0.0, "reward": 0, "replay_count": 0, "evaluation_status": "valid",
                                 "reason": "selected_evaluation_artifact_invalid" if row else state.get("selection_reason", "no_valid_submission")}
            continue
        if not row or "completed_at" not in row:
            raise ValueError("unregistered source selection")
        snapshot = registry.verified_snapshot(identifier)
        source_hash = digest(canonical(tree_hashes(snapshot)))
        if source_hash != row["source_hash"]:
            raise ValueError("registered source hash changed")
        if source_hash in cache:
            original = cache[source_hash]
            diagnostics[role] = dict(original, checkpoint_id=identifier, reused_from=original["checkpoint_id"], replay_count=0)
            continue
        repeats = []
        record = {"checkpoint_id": identifier, "source_hash": source_hash, "repeats": repeats,
                  "replay_count": 0, "score": None, "reward": None, "evaluation_status": "invalid"}
        diagnostics[role] = record
        for repeat in range(1 if state["task"] == "poisson" else 3):
            current = dict(config, output_root=Path(config["output_root"]) / identifier / f"repeat-{repeat + 1}")
            result = execute(snapshot, identifier, source_hash, **current)
            repeats.append(result)
            record["replay_count"] = len(repeats)
            registry.verified_snapshot(identifier)
        rewards, scores = [item.get("reward") for item in repeats], [item.get("score") for item in repeats]
        if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value)) for value in scores + rewards):
            raise ValueError("replay returned nonfinite or nonnumeric scores")
        if any(value is not None and value not in (0, 1) for value in rewards):
            raise ValueError("replay returned a nonbinary reward")
        valid = all(item.get("evaluation_status") == "valid" for item in repeats)
        record.update(evaluation_status="valid" if valid else "invalid",
                      reward=int(all(rewards)) if valid and None not in rewards else None,
                      score=sum(scores) / len(scores) if valid and None not in scores else None)
        cache[source_hash] = record
    if all(diagnostics[role]["evaluation_status"] == "valid" for role in ("first", "final")):
        diagnostics.update(evaluation_status="valid", score=diagnostics["final"]["score"], reward=diagnostics["final"]["reward"])
    return diagnostics


def retry_checkpoints(registry, state, config, original, *, interference_resolution, execute=None, diagnostics=None):
    """Repeat each unstable T3 checkpoint once; retain every original group."""
    if state["task"] != "poisson":
        raise ValueError("only Poisson baseline instability permits a final replay retry")
    if not isinstance(interference_resolution, str) or not interference_resolution.strip():
        raise ValueError("record the interference investigation before retry")
    if execute is None:
        from .replay import retry_t3_attempt
        execute = retry_t3_attempt
    if diagnostics is None:
        diagnostics = {}
    diagnostics.update(copy.deepcopy(original))
    changed, cache = False, {}
    for role in ("first", "final"):
        record = diagnostics.get(role)
        if not isinstance(record, dict) or record.get("checkpoint_id") != state[role + "_id"]:
            raise ValueError("retry checkpoint differs from its closed registry")
        if record.get("checkpoint_id") is None or record.get("replay_count") == 0 and not record.get("reused_from"):
            continue
        source_hash = record.get("source_hash")
        if source_hash in cache:
            first = cache[source_hash]
            diagnostics[role] = dict(first, checkpoint_id=record["checkpoint_id"], reused_from=first["checkpoint_id"], replay_count=0)
            continue
        repeats = record.get("repeats", [])
        if record.get("replay_count") != 1 or len(repeats) != 1:
            raise ValueError("retry requires an original complete T3 group")
        prior = repeats[0]
        if prior.get("performance_status") != "baseline_unstable" or prior.get("retry_permitted") is not True:
            cache[source_hash] = record
            continue
        row = next((item for item in state["evaluations"] if item["id"] == record["checkpoint_id"]), None)
        if not row or row.get("source_hash") != source_hash:
            raise ValueError("retry source differs from its registered candidate")
        snapshot = registry.verified_snapshot(record["checkpoint_id"])
        if digest(canonical(tree_hashes(snapshot))) != source_hash:
            raise ValueError("retry snapshot changed")
        current = dict(config, output_root=Path(config["output_root"]) / record["checkpoint_id"] / "retry-1")
        repeated = execute(prior, snapshot, interference_resolution=interference_resolution, **current)
        repeated.update(checkpoint_id=record["checkpoint_id"], source_hash=source_hash)
        registry.verified_snapshot(record["checkpoint_id"])
        record.update(repeats=[repeated], replay_count=1, evaluation_status="valid" if repeated.get("evaluation_status") == "valid" else "invalid",
                      score=repeated.get("score"), reward=repeated.get("reward"), replay_retry=True)
        write_json(Path(current["output_root"]) / "result.json", repeated)
        cache[source_hash], changed = record, True
    if not changed:
        raise ValueError("no original baseline instability permits a final replay retry")
    valid = all(diagnostics[role].get("evaluation_status") == "valid" for role in ("first", "final"))
    diagnostics.update(evaluation_status="valid" if valid else "invalid",
                       score=diagnostics["final"]["score"] if valid else None,
                       reward=diagnostics["final"]["reward"] if valid else None)
    return diagnostics


def final(project, plan_path, run_id, data_root, *, timing_contract=None, execute=None,
          retry_replay=None, interference_resolution=None):
    """One final replay, or one investigated T3 retry, after research freezes."""
    from .replay import prepare_judge
    project = Path(project).resolve()
    plan, plan_ref = frozen_plan(project, plan_path)
    row = next((row for row in plan["runs"] if row["run_id"] == run_id), None)
    if row is None:
        raise ValueError("unknown planned run ID")
    if row["task"] == "poisson" and timing_contract is None:
        raise ValueError("formal Poisson replay requires an explicit timing contract")
    with ledger(project, plan, plan_ref) as (manifest_path, manifest):
        # This barrier is evaluated before resolving or reading any final input
        # or truth path. All task repeats remain independent research sessions.
        latest = completed_task(project, plan, manifest, row["task"])
        entry = latest[run_id]
        original = None
        if retry_replay is not None:
            if (row["task"] != "poisson" or entry.get("replay_history") or entry.get("replay_retry_started_at")
                    or not entry.get("replay") or not isinstance(interference_resolution, str) or not interference_resolution.strip()):
                raise ValueError("only one investigated, linked Poisson replay retry is permitted")
            old_path = _file_ref(project, entry["replay"])
            if Path(retry_replay).resolve(strict=True) != old_path.resolve():
                raise ValueError("replay retry must identify the exact original replay")
            original = read_json(old_path)
            if (original.get("formal") is not True or original.get("split") != "final-test"
                    or original.get("registry_sha256") != entry["registry"]["sha256"]
                    or original.get("freeze_sha256") != plan["freezes"][row["task"]]["sha256"]):
                raise ValueError("replay retry differs from original frozen evidence")
            eligible = [item for role in ("first", "final") for item in (original.get("diagnostics", {}).get(role) or {}).get("repeats", [])
                        if item.get("performance_status") == "baseline_unstable" and item.get("retry_permitted") is True]
            if not eligible:
                raise ValueError("no original baseline instability permits a final replay retry")
        elif entry.get("replay") or entry.get("replay_started_at"):
            raise ValueError("final replay already attempted; existing evidence cannot be replaced")
        elif interference_resolution is not None:
            raise ValueError("interference resolution requires an explicit replay retry")
        registry, state = closed_research(project, entry, row)
        freeze_path = _file_ref(project, plan["freezes"][row["task"]])
        freeze = read_json(freeze_path)
        output = manifest_path.parent / "final-replays" / entry["attempt_id"]
        if original is not None:
            output = output / "retry-1"
        judge = prepare_judge(project, output / "judge-source")
        if checked_hashes(judge) != freeze["judge_source_hashes"]:
            raise ValueError("trusted judge source differs from freeze before final data access")
        # The barrier and sources passed. Close research permanently before the
        # first final-test read, including a later scoring/guard failure.
        manifest["finalized_tasks"] = sorted(set(manifest["finalized_tasks"]) | {row["task"]})
        entry["replay_retry_started_at" if original is not None else "replay_started_at"] = time.time()
        write_json(manifest_path, manifest)
        wrapper = {"formal": True, "split": "final-test", "freeze_sha256": plan["freezes"][row["task"]]["sha256"],
                   "registry_sha256": entry["registry"]["sha256"], "run_id": run_id, "attempt_id": entry["attempt_id"],
                   "replay_retry_number": 1 if original is not None else 0,
                   "diagnostics": {"evaluation_status": "invalid", "score": None, "reward": None}}
        if original is not None:
            wrapper.update(parent_replay=entry["replay"], interference_resolution=interference_resolution)
        try:
            data_root = Path(data_root).resolve()
            config = {"task": row["task"], "input_root": data_root / "inputs" / row["task"] / "final-test",
                      "truth_root": data_root / "private" / row["task"] / "final-test", "output_root": output / "replays",
                      "image": freeze["image_id"], "judge_source_root": judge, "freeze_path": freeze_path, "profile": freeze["profile"]}
            guard_replay(config["task"], config["input_root"], config["truth_root"], config["image"], judge,
                         freeze_path=freeze_path, profile=freeze["profile"])
            if row["task"] == "poisson":
                config.update(baseline_source=project / "baselines/poisson", timing_contract=timing_contract)
            if original is None:
                score_checkpoints(registry, state, config, execute=execute, diagnostics=wrapper["diagnostics"])
            else:
                retry_checkpoints(registry, state, config, original["diagnostics"], execute=execute,
                                  interference_resolution=interference_resolution, diagnostics=wrapper["diagnostics"])
            _file_ref(project, entry["registry"])
            validate_start(plan, project)
        except BaseException as exc:
            wrapper["diagnostics"].update(evaluation_status="invalid", score=None, reward=None,
                                          reason=f"{type(exc).__name__}: {exc}"[:2048])
        path = output / "result.json"
        write_json(path, wrapper)
        if original is not None:
            entry["replay_history"] = [entry["replay"]]
        entry["replay"] = reference(project, path)
        write_json(manifest_path, manifest)
        return wrapper


def baseline_source(project, plan, task, destination=None):
    """Copy only the pre-frozen author source, never a caller-selected solver."""
    prefix = f"baselines/{task}/"
    expected = {name.removeprefix(prefix): sha for name, sha in plan["tool_config"]["files"].items() if name.startswith(prefix)}
    source = Path(project) / "baselines" / task
    actual = checked_hashes(source)  # Reject links/special files before excluding ordinary bytecode caches.
    for name in list(actual):
        path = Path(name)
        if (path.parent.name == "__pycache__" and re.fullmatch(r"[A-Za-z_]\w*\.(cpython|pypy)-\d+(\.opt-\d+)?\.pyc", path.name)
                and (path.parent.parent / (path.name.split(".")[0] + ".py")).as_posix() in expected):
            del actual[name]
    if not expected or "solve.py" not in expected or actual != expected:
        raise ValueError("author baseline source differs from the frozen tool configuration")
    if destination is None:
        return expected
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name in expected:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / name).read_bytes())
        target.chmod(0o444)
    if checked_hashes(destination) != expected:
        raise ValueError("author baseline source changed while snapshotting")
    for path in sorted(destination.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o555)
    destination.chmod(0o555)
    return expected


def baseline(project, plan_path, task, method, data_root, *, timing_contract=None,
             retry_of=None, retry_reason=None, interference_resolution=None, execute=None):
    """One of eleven frozen author methods, separate from research replication."""
    from .replay import prepare_judge, replay_checkpoint, retry_t3_attempt
    project = Path(project).resolve()
    plan, plan_ref = frozen_plan(project, plan_path)
    if task not in METHODS or method not in METHODS[task]:
        raise ValueError("baseline task/method is not in the predeclared eleven methods")
    if task == "poisson" and timing_contract is None:
        raise ValueError("formal Poisson baseline requires an explicit timing contract")
    with ledger(project, plan, plan_ref) as (manifest_path, manifest):
        completed_task(project, plan, manifest, task)
        entries = manifest.setdefault("baselines", [])
        prior = [entry for entry in entries if entry["task"] == task and entry["method"] == method]
        previous, retry_kind = None, None
        if prior:
            if retry_of != prior[-1]["attempt_id"]:
                raise ValueError("baseline rerun requires the exact latest parent attempt")
            previous = read_json(_file_ref(project, prior[-1]["result"]))
            if (previous.get("task") != task or previous.get("method") != method
                    or previous.get("attempt_id") != retry_of or previous.get("run_plan_sha256") != plan_ref["sha256"]
                    or previous.get("freeze_sha256") != plan["freezes"][task]["sha256"]
                    or previous.get("formal") is not True or previous.get("split") != "final-test"):
                raise ValueError("baseline parent differs from its frozen final-test identity")
            old = previous.get("diagnostics", {})
            group = old.get("repeats", [])
            if previous.get("status") == "baseline_invalid" and old.get("evaluation_status") == "invalid":
                if not isinstance(retry_reason, str) or not retry_reason.strip() or interference_resolution is not None:
                    raise ValueError("infrastructure retry requires its explicit investigation reason")
                retry_kind = "infrastructure"
            elif (task == "poisson" and previous.get("status") == "baseline_completed" and len(group) == 1
                  and group[0].get("performance_status") == "baseline_unstable" and group[0].get("retry_permitted") is True):
                if (not isinstance(interference_resolution, str) or not interference_resolution.strip()
                        or any(read_json(_file_ref(project, entry["result"])).get("retry_kind") == "baseline_instability" for entry in prior)):
                    raise ValueError("only one investigated baseline-instability retry is permitted")
                retry_kind = "baseline_instability"
                retry_reason = interference_resolution
            else:
                raise ValueError("a completed baseline, including scientific zero, cannot be rerun")
        elif retry_of is not None or retry_reason is not None or interference_resolution is not None:
            raise ValueError("baseline retry requires an existing parent attempt")
        attempt_id = f"baseline-{task}-{method}-a{len(prior) + 1:03d}"
        checkpoint_id = f"baseline-{task}-{method}"
        output = manifest_path.parent / "author-baselines" / attempt_id
        source = output / "source"
        sources = baseline_source(project, plan, task)
        source_hash = digest(canonical(sources))
        if previous is not None and previous.get("source_hash") != source_hash:
            raise ValueError("baseline retry source differs from its original source")
        freeze_path = _file_ref(project, plan["freezes"][task])
        freeze = read_json(freeze_path)
        wrapper = {"schema_version": 1, "formal": True, "split": "final-test", "task": task, "method": method,
                   "attempt_id": attempt_id, "parent_attempt": retry_of, "retry_kind": retry_kind,
                   "retry_reason": retry_reason, "interference_resolution": interference_resolution,
                   "source_hash": source_hash, "source_files": sources, "freeze_sha256": plan["freezes"][task]["sha256"],
                   "run_plan_sha256": plan_ref["sha256"], "image_id": freeze["image_id"], "profile": freeze["profile"],
                   "fixed_reference": method == FIXED[task], "status": "baseline_running", "started_at": time.time(),
                   "diagnostics": {"checkpoint_id": checkpoint_id, "source_hash": source_hash, "repeats": [], "replay_count": 0,
                                   "score": None, "reward": None, "evaluation_status": "invalid"}}
        path = output / "result.json"
        write_json(path, wrapper)
        entry = {"task": task, "method": method, "attempt_id": attempt_id, "parent_attempt": retry_of,
                 "result": reference(project, path)}
        entries.append(entry)
        manifest["finalized_tasks"] = sorted(set(manifest["finalized_tasks"]) | {task})
        write_json(manifest_path, manifest)  # Before resolving or reading final data.
        diagnostic = wrapper["diagnostics"]
        try:
            baseline_source(project, plan, task, source)
            judge = prepare_judge(project, output / "judge-source")
            if checked_hashes(judge) != freeze["judge_source_hashes"]:
                raise ValueError("trusted judge source differs from freeze before final data access")
            data = Path(data_root).resolve()
            config = {"task": task, "input_root": data / "inputs" / task / "final-test",
                      "truth_root": data / "private" / task / "final-test", "image": freeze["image_id"],
                      "judge_source_root": judge, "freeze_path": freeze_path, "profile": freeze["profile"]}
            guard_replay(task, config["input_root"], config["truth_root"], config["image"], judge,
                         freeze_path=freeze_path, profile=freeze["profile"])
            if task == "poisson":
                config.update(baseline_source=source, candidate_method=method, timing_contract=timing_contract)
            else:
                config["method"] = method
            for repeat in range(1 if task == "poisson" else 3):
                current = dict(config, output_root=output / "replays" / f"repeat-{repeat + 1}")
                if checked_hashes(source) != sources:
                    raise ValueError("author baseline snapshot changed before execution")
                if retry_kind == "baseline_instability":
                    result = (execute or retry_t3_attempt)(previous["diagnostics"]["repeats"][0], source,
                                interference_resolution=interference_resolution, **current)
                    result.update(checkpoint_id=checkpoint_id, source_hash=source_hash)
                else:
                    result = (execute or replay_checkpoint)(source, checkpoint_id, source_hash, **current)
                diagnostic["repeats"].append(result)
                diagnostic["replay_count"] = len(diagnostic["repeats"])
                if checked_hashes(source) != sources:
                    raise ValueError("author baseline snapshot changed during execution")
            repeats = diagnostic["repeats"]
            rewards, scores = [item.get("reward") for item in repeats], [item.get("score") for item in repeats]
            if (any(value is not None and (type(value) not in (int, float) or not math.isfinite(value)) for value in rewards + scores)
                    or any(value is not None and value not in (0, 1) for value in rewards)):
                raise ValueError("trusted baseline replay returned an invalid numeric verdict")
            valid = all(item.get("evaluation_status") == "valid" for item in repeats)
            diagnostic.update(evaluation_status="valid" if valid else "invalid",
                              score=sum(scores) / len(scores) if valid and None not in scores else None,
                              reward=int(all(rewards)) if valid and None not in rewards else None)
            validate_start(plan, project)
            wrapper["status"] = "baseline_completed" if valid else "baseline_invalid"
        except BaseException as exc:
            wrapper["status"] = "baseline_invalid"
            diagnostic.update(evaluation_status="invalid", score=None, reward=None, reason=f"{type(exc).__name__}: {exc}"[:2048])
        wrapper["finished_at"] = time.time()
        write_json(path, wrapper)
        entry["result"] = reference(project, path)
        write_json(manifest_path, manifest)
        return wrapper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "final", "baseline"):
        command = sub.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        if name == "baseline":
            command.add_argument("--task", choices=tuple(METHODS), required=True)
            command.add_argument("--method", required=True)
            command.add_argument("--retry-of")
            command.add_argument("--retry-reason")
        else:
            command.add_argument("--run-id", required=True)
        if name == "start":
            command.add_argument("--retry-of")
        else:
            command.add_argument("--data", type=Path, required=True)
            command.add_argument("--timing-contract", type=Path)
            if name == "final":
                command.add_argument("--retry-replay", type=Path)
            command.add_argument("--interference-resolution")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    if args.command == "start":
        result = asyncio.run(start(project, args.plan, args.run_id, retry_of=args.retry_of))
        ok = result.get("status") == "research_frozen"
    elif args.command == "final":
        result = final(project, args.plan, args.run_id, args.data, timing_contract=args.timing_contract,
                       retry_replay=args.retry_replay, interference_resolution=args.interference_resolution)
        ok = result["diagnostics"]["evaluation_status"] == "valid"
    else:
        result = baseline(project, args.plan, args.task, args.method, args.data, timing_contract=args.timing_contract,
                          retry_of=args.retry_of, retry_reason=args.retry_reason, interference_resolution=args.interference_resolution)
        ok = result["status"] == "baseline_completed"
    print(canonical(result).decode())
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
