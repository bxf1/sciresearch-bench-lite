"""Host study controller: public research and explicit final replay are separate."""
from __future__ import annotations

import argparse
import asyncio
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
from .phase import checked_hashes, guard_replay
from .registry import Registry
from .run_plan import _file_ref, validate_start

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
    if (plan["model"]["thinking"] not in ("off", {"type": "disabled"})
            or plan["model"]["temperature"] not in (None, 0)):
        raise ValueError("native relay supports only the frozen disabled-thinking/zero-temperature policy")
    base = project / "research-runs" / run_id
    output = base if parent_attempt is None else base / "retries" / attempt_id
    prompt = ((project / "prompts" / row["task"] / "common.md").read_bytes() + b"\n\n"
              + (project / "prompts" / row["task"] / (row["group"] + ".md")).read_bytes())
    if digest(prompt) != plan["tasks"][row["task"]]["combined_prompt_hashes"][row["group"]]:
        raise ValueError("combined research prompt changed")
    settings = {"formal": True, **{key: row[key] for key in ("task", "group", "run_id", "repeat")},
                "research_seconds": 1800, "max_evaluations": 20, "research_vcpu": 4,
                "research_memory_bytes": 4 * 1024**3, "max_turns": None,
                "attempt_id": attempt_id, "parent_attempt": parent_attempt,
                "session_id": row["session_id"] if parent_attempt is None else str(uuid.uuid5(uuid.UUID(row["session_id"]), attempt_id)),
                "plan_ref": plan_ref, "prompt": prompt.decode("utf-8"),
                "prompt_hashes": plan["tasks"][row["task"]]["prompt_hashes"],
                "session_output_limit": plan["model"]["output_token_limit"],
                "request_output_limit": min(4096, plan["model"]["output_token_limit"]),
                "relay_ttl_seconds": 2700,
                "expected_system_sha256": policy["wire_system_sha256"],
                "expected_tools_sha256": policy["wire_tools_sha256"]}
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
        if prior:
            previous = read_attempt(project, prior[-1])
            if retry_of != prior[-1]["attempt_id"] or previous["attempt_status"] not in FAILED:
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


def final(project, plan_path, run_id, data_root, *, timing_contract=None, execute=None):
    """Explicit, single-use final replay after every related session is frozen."""
    from .replay import prepare_judge
    project = Path(project).resolve()
    plan, plan_ref = frozen_plan(project, plan_path)
    row = next((row for row in plan["runs"] if row["run_id"] == run_id), None)
    if row is None:
        raise ValueError("unknown planned run ID")
    if row["task"] == "poisson" and timing_contract is None:
        raise ValueError("formal Poisson replay requires an explicit timing contract")
    with ledger(project, plan, plan_ref) as (manifest_path, manifest):
        latest = {entry["run_id"]: entry for entry in manifest["attempts"]}
        # This barrier is evaluated before resolving or reading any final input
        # or truth path. All task repeats remain independent research sessions.
        related = [item for item in plan["runs"] if item["task"] == row["task"]]
        for item in related:
            if item["run_id"] not in latest:
                raise ValueError("all related research must finish before final data can be read")
            closed_research(project, latest[item["run_id"]], item)
        entry = latest[run_id]
        if entry.get("replay") or entry.get("replay_started_at"):
            raise ValueError("final replay already attempted; existing evidence cannot be replaced")
        registry, state = closed_research(project, entry, row)
        freeze_path = _file_ref(project, plan["freezes"][row["task"]])
        freeze = read_json(freeze_path)
        output = manifest_path.parent / "final-replays" / entry["attempt_id"]
        judge = prepare_judge(project, output / "judge-source")
        if checked_hashes(judge) != freeze["judge_source_hashes"]:
            raise ValueError("trusted judge source differs from freeze before final data access")
        # The barrier and sources passed. Close research permanently before the
        # first final-test read, including a later scoring/guard failure.
        manifest["finalized_tasks"] = sorted(set(manifest["finalized_tasks"]) | {row["task"]})
        entry["replay_started_at"] = time.time()
        write_json(manifest_path, manifest)
        wrapper = {"formal": True, "split": "final-test", "freeze_sha256": plan["freezes"][row["task"]]["sha256"],
                   "registry_sha256": entry["registry"]["sha256"], "run_id": run_id, "attempt_id": entry["attempt_id"],
                   "diagnostics": {"evaluation_status": "invalid", "score": None, "reward": None}}
        try:
            data_root = Path(data_root).resolve()
            config = {"task": row["task"], "input_root": data_root / "inputs" / row["task"] / "final-test",
                      "truth_root": data_root / "private" / row["task"] / "final-test", "output_root": output / "replays",
                      "image": freeze["image_id"], "judge_source_root": judge, "freeze_path": freeze_path, "profile": freeze["profile"]}
            guard_replay(config["task"], config["input_root"], config["truth_root"], config["image"], judge,
                         freeze_path=freeze_path, profile=freeze["profile"])
            if row["task"] == "poisson":
                config.update(baseline_source=project / "baselines/poisson", timing_contract=timing_contract)
            score_checkpoints(registry, state, config, execute=execute, diagnostics=wrapper["diagnostics"])
            _file_ref(project, entry["registry"])
            validate_start(plan, project)
        except BaseException as exc:
            wrapper["diagnostics"].update(evaluation_status="invalid", score=None, reward=None,
                                          reason=f"{type(exc).__name__}: {exc}"[:2048])
        path = output / "result.json"
        write_json(path, wrapper)
        entry["replay"] = reference(project, path)
        write_json(manifest_path, manifest)
        return wrapper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "final"):
        command = sub.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--run-id", required=True)
        if name == "start":
            command.add_argument("--retry-of")
        else:
            command.add_argument("--data", type=Path, required=True)
            command.add_argument("--timing-contract", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    if args.command == "start":
        result = asyncio.run(start(project, args.plan, args.run_id, retry_of=args.retry_of))
        ok = result.get("status") == "research_frozen"
    else:
        result = final(project, args.plan, args.run_id, args.data, timing_contract=args.timing_contract)
        ok = result["diagnostics"]["evaluation_status"] == "valid"
    print(canonical(result).decode())
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
