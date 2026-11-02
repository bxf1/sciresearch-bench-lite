"""Private diagnostic views and replay; never part of public research feedback."""
from pathlib import Path
import shutil

from .common import read_json, write_json, file_hash
from .phase import checked_hashes, diagnostic_key, validate_manifest


def prepare_views(data):
    """Copies are byte-identical views of existing cases, not new instances."""
    data = Path(data).resolve()
    destination = data / "diagnostic-views"
    destination.mkdir(exist_ok=False)
    inventory = {}
    for task in ("heat", "ode", "poisson"):
        inventory[task] = {}
        for split in ("diagnostic-calibration", "diagnostic-test"):
            inputs, truth = data/"inputs"/task/split, data/"private"/task/split
            manifest = validate_manifest(task, inputs)
            inventory[task][diagnostic_key(manifest)] = {"input":str(inputs), "truth":str(truth),
                "input_hashes":checked_hashes(inputs), "truth_hashes":checked_hashes(truth)}
            if task != "poisson":
                continue
            for profile in ("large_grid", "five_disks", "cache_order"):
                for order in (("forward", "reverse") if profile == "cache_order" else ("forward",)):
                    selected = [row for row in manifest["cases"] if row["profile_id"] == profile]
                    if order == "reverse":
                        selected.reverse()
                    name = split + "-" + profile + "-" + order
                    view_input, view_truth = destination/"inputs"/task/name, destination/"private"/task/name
                    for row in selected:
                        shutil.copytree(inputs/row["path"], view_input/row["path"])
                        shutil.copytree(truth/row["path"], view_truth/row["path"])
                    view = {**manifest, "profile_id":profile, "order":order, "cases":selected,
                            "view_of_manifest_sha256":file_hash(inputs/"manifest.json")}
                    write_json(view_input/"manifest.json", view)
                    validate_manifest(task, view_input)
                    inventory[task][diagnostic_key(view)] = {"input":str(view_input), "truth":str(view_truth),
                        "input_hashes":checked_hashes(view_input), "truth_hashes":checked_hashes(view_truth)}
    write_json(destination/"inventory.json", inventory)
    return inventory


def evaluate_final(project, plan_path, run_id, data, output, *, execute=None):
    from .study import frozen_plan, completed_task, closed_research
    from .run_plan import _file_ref
    from .replay import prepare_judge, replay_single
    project, data, output = Path(project).resolve(), Path(data).resolve(), Path(output).resolve()
    plan, plan_ref = frozen_plan(project, plan_path)
    if plan.get("execution_policy", {}).get("global_research_closure_before_hidden_scoring") is not True:
        raise ValueError("diagnostics require the global research closure policy")
    row = next(row for row in plan["runs"] if row["run_id"] == run_id)
    ledger = read_json(project/"research-runs"/plan["plan_id"]/"manifest.json")
    entry = completed_task(project, plan, ledger, row["task"])[run_id]
    registry, state = closed_research(project, entry, row)
    output.mkdir(parents=True, exist_ok=False)
    identifier = state["final_id"]
    registered = next((r for r in state["evaluations"] if r["id"] == identifier),None)
    result = {"run_id":run_id, "task":row["task"], "plan":plan_ref, "diagnostic_only":True,
              "excluded_from_main_score":True, "candidate_id":identifier, "profiles":{}}
    if identifier is None or not registered or registered.get("artifact_valid") is not True:
        result.update(status="no_valid_candidate", passed=0, total=12)
        write_json(output/"result.json", result)
        return result
    source = registry.verified_snapshot(identifier)
    frozen = _file_ref(project, plan["freezes"][row["task"]])
    freeze = read_json(frozen)
    judge = prepare_judge(project, output/"judge-source")
    inventory = read_json(data/"diagnostic-views/inventory.json")[row["task"]]
    keys = (["diagnostic-test/all/forward"] if row["task"] != "poisson" else
            ["diagnostic-test/"+p+"/"+o for p,o in (("large_grid","forward"),("five_disks","forward"),("cache_order","forward"),("cache_order","reverse"))])
    for key in keys:
        view = inventory[key]
        config = dict(task=row["task"], input_root=Path(view["input"]), truth_root=Path(view["truth"]),
                      output_root=output/key.replace("/","-"), image=freeze["image_id"],
                      judge_source_root=judge, freeze_path=frozen)
        if row["task"] == "poisson":
            if execute is None:
                raise ValueError("Poisson diagnostics require observed BCCBBC execution")
            result["profiles"][key] = execute(source, **config)
        else:
            result["profiles"][key] = (execute or replay_single)(source, **config)
        write_json(output/"result.json", result)
    result["status"] = "evaluated"
    write_json(output/"result.json", result)
    return result
