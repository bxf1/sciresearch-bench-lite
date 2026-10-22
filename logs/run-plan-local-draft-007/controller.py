"""Refresh only trusted-code bindings after baseline orchestration changes."""
from pathlib import Path
import copy
import datetime

from runner.common import canonical, digest, file_hash, read_json, write_json
from runner.run_plan import start_blockers, trusted_tool_files

root = Path.cwd()
previous = root / "freezes/research-run-plan-local-draft-006.json"
plan = copy.deepcopy(read_json(previous))
out = root / "logs/run-plan-local-draft-007"
out.mkdir(exist_ok=False)
(out / "controller.py").write_bytes(Path(__file__).read_bytes())
def ref(path):
    return {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path)}

plan["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
plan["tool_config"]["files"] = {name: file_hash(root / name) for name in trusted_tool_files(root)}
plan["tool_config_sha256"] = digest(canonical(plan["tool_config"]))
for task, old_ref in plan["freezes"].items():
    task_freeze = read_json(root / old_ref["path"])
    task_freeze["created_at"] = plan["created_at"]
    task_freeze["research"]["tool_config_sha256"] = plan["tool_config_sha256"]
    target = root / f"freezes/{task}-local-draft-007.json"
    assert not target.exists()
    write_json(target, task_freeze)
    plan["freezes"][task] = ref(target)
target = root / "freezes/research-run-plan-local-draft-007.json"
assert not target.exists()
write_json(target, plan)
blockers = start_blockers(plan, root)
assert len(blockers) == 4, blockers
assert plan["runs"] == read_json(previous)["runs"]
write_json(out / "validation.json", {
    "formal_ready": False, "blockers": blockers,
    "previous_plan": ref(previous), "current_plan": ref(target),
    "run_matrix_unchanged": True, "formal_sessions": 0,
    "model_calls": 0, "final_test_scores_accessed": False,
    "scope": "Refresh complete trusted Python manifest; data, judge and methods unchanged; formal acceptance remains pending."
})
print({"formal_ready": False, "blockers": blockers})
