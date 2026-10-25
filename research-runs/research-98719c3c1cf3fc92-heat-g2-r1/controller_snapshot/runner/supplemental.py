"""Explicitly authorized, selectively rerun token-only studies; never replace formal-003."""
from __future__ import annotations

import argparse
import asyncio
import copy
import datetime
from pathlib import Path
import uuid

from .common import canonical, digest, file_hash, read_json, tree_hashes, write_json

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "freezes/supplemental-500k-2026-10-24.json"
EXPECTED = {("poisson", "g3", 1), ("heat", "g3", 2), ("heat", "g1", 2),
            ("heat", "g3", 3), ("heat", "g1", 3), ("heat", "g2", 3)}


def reference(path):
    path = Path(path).resolve(strict=True)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": file_hash(path)}


def checked(ref):
    path = (ROOT / ref["path"]).resolve(strict=True)
    if not path.is_relative_to(ROOT) or file_hash(path) != ref["sha256"]:
        raise ValueError("supplemental evidence changed: " + ref["path"])
    return path


def budget_prompt(task, group):
    common = (ROOT / "prompts" / task / "common.md").read_text()
    if task == "heat":
        old = "The common research budget is 30 minutes and at most 20 accepted registered evaluations, including failed candidates."
    elif task == "poisson":
        old = "Research has 30 minutes, 4 vCPU, 4 GiB and at most 20 registered public\nevaluations."
    else:
        raise ValueError("only the six authorized heat/poisson sessions may rerun")
    if common.count(old) != 1:
        raise ValueError("original budget sentence changed")
    new = ("The research session has a cumulative limit of 500,000 output tokens, including context compaction. "
           "There is no research wall-clock limit and no cumulative request or registered-evaluation count limit. "
           "Research resources remain 4 vCPU and 4 GiB. Individual request and candidate-worker protections remain unchanged.")
    common = common.replace(old, new)
    return common + "\n\n" + (ROOT / "prompts" / task / (group + ".md")).read_text()


def create_plan():
    if PLAN.exists():
        raise ValueError("supplemental plan already exists")
    prior_path = ROOT / "freezes/research-run-plan-formal-003.json"
    prior = read_json(prior_path)
    ledger_path = ROOT / "research-runs" / prior["plan_id"] / "manifest.json"
    ledger = read_json(ledger_path)
    latest = {entry["run_id"]: entry for entry in ledger["attempts"]}
    policy = read_json(checked(prior["tool_config"]["runtime_enforcement"]))
    plan_id = "supplemental-500k-2026-10-24"
    plan = {"schema_version": 1, "study_kind": "selective_supplemental", "plan_id": plan_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "authorization": "User explicitly requested the six no-submission sessions at 500000 output tokens, no research wall limit, plus Poisson G2 timing only; successful runs retained. Delivery requested by 2026-10-24 15:00 Asia/Shanghai.",
            "previous_plan": reference(prior_path), "previous_ledger": reference(ledger_path),
            "limitations": ["Selected after observing formal-003 outcomes; not an independent equal-budget guidance comparison.",
                            "Original failures and invalid measurements are retained; no outcome is replaced.",
                            "Same already-used hidden set; no new held-out generalization claim.",
                            "No research total time/count cap; per-request and individual worker safety timeouts remain.",
                            "Known failed-request output remains unknown and is conservatively reserved."],
            "model": copy.deepcopy(prior["model"]), "runs": []}
    plan["model"]["output_token_limit"] = 500000
    # Original model-enforcement receipts describe 200k. Do not relabel them.
    plan["model"]["prior_enforcement"] = plan["model"].pop("enforcement", None)
    for row in prior["runs"]:
        if (row["task"], row["group"], row["repeat"]) not in EXPECTED:
            continue
        entry = latest[row["run_id"]]
        result = read_json(checked(entry["result"]))
        state = read_json(checked(entry["registry"]))
        if (result["status"] != "research_frozen" or not state["closed"]
                or state["first_id"] is not None or state["final_id"] is not None):
            raise ValueError("authorized no-submission prerequisite failed")
        run_id = f"{plan_id}-{row['task']}-{row['group']}-r{row['repeat']}"
        freeze = read_json(checked(prior["freezes"][row["task"]]))
        settings = {"formal": True, "task": row["task"], "group": row["group"], "repeat": row["repeat"],
                    "run_id": run_id, "attempt_id": run_id + "-a001", "parent_attempt": None,
                    "session_id": str(uuid.uuid4()), "research_seconds": None, "max_evaluations": None,
                    "research_vcpu": 4, "research_memory_bytes": 4 * 1024**3, "max_turns": None,
                    "session_output_limit": 500000, "request_output_limit": 4096,
                    "relay_ttl_seconds": None, "max_requests": None,
                    "prompt": budget_prompt(row["task"], row["group"]),
                    "prompt_hashes": prior["tasks"][row["task"]]["prompt_hashes"],
                    "expected_system_sha256": policy["wire_system_sha256"],
                    "expected_tools_sha256": policy["wire_tools_sha256"],
                    "expected_compaction_system_sha256": policy["native_compaction"]["wire_system_sha256"],
                    "expected_compaction_sources": policy["native_compaction"]["source_sha256"]}
        plan["runs"].append({"original_run_id": row["run_id"], "original_attempt": entry,
                             "freeze": prior["freezes"][row["task"]], "settings": settings,
                             "research_image": prior["research_images"][row["task"]]["image_id"],
                             "numeric_image": freeze["image_id"],
                             "input_hashes": tree_hashes(ROOT / "tasks" / row["task"] / "environment/public-dev")})
    if len(plan["runs"]) != 6:
        raise ValueError("expected exactly six supplemental sessions")
    plan["source_hashes"] = {p.relative_to(ROOT).as_posix(): file_hash(p)
                             for folder in ("runner", "judge", "public", "authoring", "prompts", "baselines")
                             for p in sorted((ROOT / folder).rglob("*"))
                             if p.is_file() and "__pycache__" not in p.parts and "data" not in p.parts}
    write_json(PLAN, plan)
    return plan


def load_plan():
    plan = read_json(PLAN)
    checked(plan["previous_plan"])
    checked(plan["previous_ledger"])
    for name, sha in plan["source_hashes"].items():
        if file_hash(ROOT / name) != sha:
            raise ValueError("supplemental frozen source changed: " + name)
    return plan


def spec_for(row):
    settings = dict(row["settings"], plan_ref=reference(PLAN))
    return {"supplemental": True, "project": str(ROOT), "plan_path": str(PLAN), "settings": settings,
            "output_root": str(ROOT / "research-runs" / settings["run_id"]),
            "public_input": str(ROOT / "tasks" / settings["task"] / "environment/public-dev"),
            "research_image": row["research_image"], "numeric_image": row["numeric_image"]}


def validate_session(spec):
    plan = load_plan()
    row = next(row for row in plan["runs"] if row["settings"]["run_id"] == spec["settings"]["run_id"])
    if spec != spec_for(row) or tree_hashes(spec["public_input"]) != row["input_hashes"]:
        raise ValueError("supplemental session differs from frozen plan")
    return spec


async def run_all():
    from .harbor_pilot import run_research_session
    plan = load_plan()
    ledger_path = ROOT / "research-runs" / plan["plan_id"] / "manifest.json"
    if ledger_path.exists():
        manifest = read_json(ledger_path)
        if manifest["plan"] != reference(PLAN):
            raise ValueError("supplemental ledger plan mismatch")
    else:
        manifest = {"study_kind": plan["study_kind"], "plan": reference(PLAN), "attempts": []}
    for row in plan["runs"]:
        spec = spec_for(row)
        previous = [x for x in manifest["attempts"] if x["run_id"] == spec["settings"]["run_id"]]
        if previous:
            if previous[-1]["status"] == "running":
                raise ValueError("an unfinished supplemental session already exists")
            continue
        entry = {"run_id": spec["settings"]["run_id"], "original_run_id": row["original_run_id"], "status": "running"}
        manifest["attempts"].append(entry)
        write_json(ledger_path, manifest)
        print(__import__("json").dumps(entry), flush=True)
        result = await run_research_session(spec)
        entry.update(status=result["status"], attempt_status=result["attempt_status"],
                     result=reference(Path(spec["output_root"]) / "result.json"))
        state = Path(spec["output_root"]) / "registry/state.json"
        if state.exists():
            entry["registry"] = reference(state)
            entry.update({k: read_json(state)[k] for k in ("first_id", "final_id")})
        write_json(ledger_path, manifest)
        print(__import__("json").dumps(entry), flush=True)
        if result["status"] != "research_frozen":
            raise RuntimeError("supplemental infrastructure failure; retained for investigation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("freeze", "run"))
    args = parser.parse_args()
    if args.operation == "freeze":
        plan = create_plan()
        print(plan["plan_id"], len(plan["runs"]))
    else:
        asyncio.run(run_all())


if __name__ == "__main__":
    main()
