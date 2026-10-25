"""Prepare, but never launch or freeze, the 15-session research run matrix.

`draft` records independent order entropy and current public package hashes.
`validate` is a fail-closed prerequisite check, not a run controller. A controller
must call validate_start immediately before allocating a formal research run.
"""
from __future__ import annotations

import argparse
import copy
import datetime
from pathlib import Path
import re
import secrets
import uuid

from .artifact_gate import safe_relative
from .common import TASKS, VERSION, canonical, digest, file_hash, read_json, write_json
from .phase import ACCEPTANCE, IMAGE_ID, RESOURCES, checked_hashes, validate_freeze_document

GROUPS = ("g1", "g2", "g3")
BLOCKS = (("heat", 1), ("ode", 1), ("poisson", 1), ("heat", 2), ("heat", 3))
MODEL_FIXED = {"model_id": "deepseek-flash", "pi_version": "0.84.1",
               "harbor_commit": "38b9be0164a910015a0be9a37ba6e8e78c562dfe",
               "api_format": "anthropic_messages", "endpoint": "https://api.deepseek.com/anthropic"}
PARAMETERS = ("thinking", "temperature", "output_token_limit")
def trusted_tool_files(project):
    """Freeze the complete trusted Python surface, including comparison methods."""
    root = Path(project)
    paths = {path.relative_to(root).as_posix()
             for folder in ("runner", "public", "judge", "baselines")
             for path in (root / folder).rglob("*.py") if "__pycache__" not in path.parts}
    paths.add("authoring/package_tasks.py")  # Research input allowlist imported by the controller.
    return tuple(sorted(paths))


TOOL_FILES = trusted_tool_files(Path(__file__).resolve().parents[1])
ORDER_ALGORITHM = "sha256-rank-within-task-repeat-v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class RunPlanError(ValueError):
    def __init__(self, blockers):
        self.blockers = blockers
        super().__init__("Formal research is blocked: " + "; ".join(blockers))


def matrix(order_entropy, *, identity_revision=None):
    """Hash-ranking gives a stable randomized order independent of library PRNGs."""
    if not isinstance(order_entropy, str) or SHA256.fullmatch(order_entropy) is None:
        raise ValueError("order entropy must be 32 bytes encoded as lowercase hex")
    entropy = bytes.fromhex(order_entropy)
    identity = b"run-plan-v1\0" + entropy
    if identity_revision is not None:
        if not isinstance(identity_revision, str) or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identity_revision) is None:
            raise ValueError("invalid protocol identity revision")
        identity += b"\0revision\0" + identity_revision.encode()
    namespace = uuid.UUID(bytes=bytes.fromhex(digest(identity)[:32]))
    plan_id = "research-" + namespace.hex[:16]
    runs = []
    for block, (task, repeat) in enumerate(BLOCKS, 1):
        order = sorted(GROUPS, key=lambda group: (digest(entropy + f"\0{task}\0{repeat}\0{group}".encode()), group))
        for group in order:
            run_id = f"{plan_id}-{task}-{group}-r{repeat}"
            runs.append({"sequence": len(runs) + 1, "block": block, "task": task, "group": group,
                         "repeat": repeat, "run_id": run_id, "session_id": str(uuid.uuid5(namespace, run_id)),
                         "workdir": f"research-runs/{run_id}/workspace", "resume": False,
                         "solver_seed": 0, "research_seconds": 1800, "max_evaluations": 20})
    return plan_id, runs


def snapshots(project):
    """Only public task packages, prompts and trusted tooling are read here."""
    project = Path(project)
    result = {}
    for task in TASKS:
        prompt_bytes = {name: (project / "prompts" / task / name).read_bytes()
                        for name in ("common.md", "g1.md", "g2.md", "g3.md")}
        result[task] = {
            "package_files": checked_hashes(project / "tasks" / task),
            "prompt_hashes": {name: digest(value) for name, value in prompt_bytes.items()},
            "combined_prompt_hashes": {group: digest(prompt_bytes["common.md"] + b"\n\n" + prompt_bytes[group + ".md"])
                                       for group in GROUPS},
        }
    return result


def create_draft(project, *, order_entropy=None, identity_revision=None):
    project = Path(project)
    entropy = order_entropy if order_entropy is not None else secrets.token_hex(32)
    plan_id, runs = matrix(entropy, identity_revision=identity_revision)
    tool_config = {"files": {name: file_hash(project / name) for name in trusted_tool_files(project)},
                   "skills": [], "extensions": [], "mcp_servers": [], "resume": False,
                   "runtime_tools": None, "runtime_enforcement": None}
    return {
        "schema_version": 1, "contract_version": VERSION, "status": "draft", "formal_ready": False,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "plan_id": plan_id,
        **({"identity_revision": identity_revision} if identity_revision is not None else {}),
        "order": {"algorithm": ORDER_ALGORITHM, "entropy_hex": entropy,
                  "scope": "Independent of private data-generation entropy; condition order within task/repeat blocks."},
        "runs": runs, "run_matrix_sha256": digest(canonical(runs)),
        "resources": copy.deepcopy(RESOURCES),
        "model": {**MODEL_FIXED, "model_version": None, "version_resolution": None, **{name: None for name in PARAMETERS},
                  "enforcement": {name: None for name in PARAMETERS}},
        "system_prompt": None, "tool_config": tool_config, "tool_config_sha256": digest(canonical(tool_config)),
        "tasks": snapshots(project), "package_manifest_sha256": file_hash(project / "tasks/package-manifest.json"),
        "freezes": {task: None for task in TASKS},
        "research_images": {task: None for task in TASKS},
        "acceptance_evidence": {task: {check: None for check in ((*ACCEPTANCE, "timing_profile") if task == "poisson" else ACCEPTANCE)}
                                for task in TASKS},
        "limitations": ["Draft only; no research session/workspace was created and no final score was read.",
                        "Model version, sampling/reasoning/output limit and their effective enforcement remain unresolved; verified unsupported sampling may be null.",
                        "System prompt, effective tool inventory, resources, isolation and three complete task freezes are required.",
                        "Budgets are 1800 seconds and 20 accepted evaluations per independent session; no automatic reduction."]}


def _file_ref(project, ref):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("missing path/hash reference")
    relative = safe_relative(ref["path"])
    if not isinstance(ref["sha256"], str) or SHA256.fullmatch(ref["sha256"]) is None:
        raise ValueError("invalid reference SHA256")
    path = Path(project)
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("linked evidence is forbidden")
    if not path.is_file() or path.stat().st_size > 16 * 1024**2 or file_hash(path) != ref["sha256"]:
        raise ValueError("missing, oversized or changed evidence file")
    return path


def validate_tool_files(plan, project):
    """Allow only an explicitly evidenced relay repair of an unchanged plan."""
    frozen = plan["tool_config"]["files"]
    actual = {name: file_hash(Path(project) / name) for name in trusted_tool_files(project)}
    if frozen == actual:
        return
    if set(frozen) != set(actual):
        raise ValueError("trusted tooling files changed")
    changed = {name for name in frozen if frozen[name] != actual[name]}
    allowed = {"runner/model_relay.py", "runner/run_plan.py"}
    if not changed <= allowed or not re.fullmatch(r"research-[0-9a-f]{16}", plan["plan_id"]):
        raise ValueError("trusted tooling files changed")
    path = Path(project) / "freezes" / (plan["plan_id"] + "-relay-usage-repair.json")
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError("trusted tooling files changed; missing bounded relay repair addendum")
    repair = read_json(path)
    if (not isinstance(repair, dict) or repair.get("schema_version") != 1
            or repair.get("kind") != "relay_input_usage_compatibility"
            or read_json(_file_ref(project, repair.get("run_plan"))) != plan):
        raise ValueError("relay repair is not bound to this unchanged frozen plan")
    files = repair.get("files")
    if not isinstance(files, dict) or set(files) != changed:
        raise ValueError("relay repair file set differs from actual changes")
    for name in changed:
        if files[name] != {"before_sha256": frozen[name], "after_sha256": actual[name]}:
            raise ValueError("relay repair source hash mismatch")
    evidence = repair.get("evidence")
    required = {"authorization", "regression_tests", "synthetic_probe", "patch"}
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ValueError("relay repair requires authorization, tests, probe and exact patch evidence")
    for ref in evidence.values():
        _file_ref(project, ref)


def start_blockers(plan, project):
    """Return every independently checkable blocker without executing any workload."""
    blockers = []
    if not isinstance(plan, dict):
        return ["run plan must be an object"]
    if plan.get("schema_version") != 1 or plan.get("contract_version") != VERSION:
        blockers.append("run-plan schema/contract mismatch")
    if plan.get("status") != "frozen" or plan.get("formal_ready") is not True:
        blockers.append("run plan requires status=frozen and formal_ready=true; draft cannot start")
    try:
        order = plan["order"]
        if order["algorithm"] != ORDER_ALGORITHM:
            raise ValueError("unsupported ordering algorithm")
        revision = plan.get("identity_revision")
        plan_id, expected = matrix(order["entropy_hex"], identity_revision=revision)
        if revision is not None:
            prior = read_json(_file_ref(project, plan.get("previous_plan")))
            if prior.get("order") != order or prior.get("plan_id") == plan_id:
                raise ValueError("revision must preserve the previous order with fresh identities")
            stable = lambda rows: [{k: v for k, v in row.items() if k not in ("run_id", "session_id", "workdir")} for row in rows]
            if stable(prior["runs"]) != stable(expected):
                raise ValueError("revision changed the previous matrix or budgets")
        if plan.get("plan_id") != plan_id or plan.get("runs") != expected:
            raise ValueError("matrix differs from the predeclared 15 independent sessions or their full budgets")
        if plan.get("run_matrix_sha256") != digest(canonical(expected)):
            raise ValueError("run matrix hash mismatch")
    except (ValueError, KeyError, TypeError) as exc:
        blockers.append("run matrix: " + str(exc))
    if plan.get("resources") != RESOURCES:
        blockers.append("resource/budget contract differs; automatic budget reductions are forbidden")

    model = plan.get("model")
    if not isinstance(model, dict):
        model = {}
    if any(model.get(key) != value for key, value in MODEL_FIXED.items()):
        blockers.append("model ID, endpoint, Pi or Harbor revision differs from the shared fixed configuration")
    try:
        resolution = model.get("version_resolution")
        version = model.get("model_version")
        if "model_version" not in model:
            raise ValueError("model_version must be explicitly recorded, including verified null")
        if not isinstance(resolution, dict):
            raise ValueError("model version is unresolved")
        if version is None:
            if resolution.get("status") != "unavailable_verified" or not isinstance(resolution.get("reason"), str) or not resolution["reason"].strip():
                raise ValueError("a null model version requires verified unavailability and a reason")
        elif not isinstance(version, str) or not version.strip() or resolution.get("status") != "verified":
            raise ValueError("model version must be nonempty and verified")
        _file_ref(project, resolution.get("evidence"))
    except (ValueError, OSError, TypeError) as exc:
        blockers.append("model version: " + str(exc))
    for parameter in PARAMETERS:
        value = model.get(parameter)
        declarations = model.get("enforcement")
        enforcement = declarations.get(parameter) if isinstance(declarations, dict) else None
        unsupported = (parameter == "temperature" and parameter in model and value is None and isinstance(enforcement, dict)
                       and enforcement.get("status") == "unsupported")
        valid = value is not None
        if parameter == "thinking":
            valid = valid and isinstance(value, (str, dict)) and bool(value)
        elif parameter == "temperature":
            valid = unsupported or (valid and type(value) in (int, float) and 0 <= value <= 2)
        else:
            valid = type(value) is int and value > 0
        if not valid:
            blockers.append(f"model parameter {parameter} is unresolved/invalid (unverified null cannot authorize a run)")
        try:
            if unsupported:
                if not isinstance(enforcement.get("reason"), str) or not enforcement["reason"].strip():
                    raise ValueError("unsupported temperature requires a reason")
            elif not isinstance(enforcement, dict) or enforcement.get("status") != "verified":
                raise ValueError("effective enforcement is not verified")
            _file_ref(project, enforcement.get("evidence"))
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            blockers.append(f"{parameter} enforcement: {exc}")
    try:
        if model.get("thinking") == {"type": "enabled"}:
            if model.get("output_config") != {"effort": "max"} or model.get("temperature") is not None:
                raise ValueError("thinking control requires max effort and unsupported temperature recorded as null")
            enforcement = model.get("enforcement", {}).get("output_config", {})
            if enforcement.get("status") != "verified":
                raise ValueError("thinking effort requires verified wire enforcement")
            _file_ref(project, enforcement.get("evidence"))
    except (ValueError, OSError, TypeError) as exc:
        blockers.append("thinking effort: " + str(exc))
    try:
        _file_ref(project, plan.get("system_prompt"))
    except (ValueError, OSError, TypeError) as exc:
        blockers.append("system prompt: " + str(exc))

    tools = plan.get("tool_config")
    try:
        if not isinstance(tools, dict) or plan.get("tool_config_sha256") != digest(canonical(tools)):
            raise ValueError("missing or mismatched tool configuration hash")
        validate_tool_files(plan, project)
        if any(tools.get(key) != [] for key in ("skills", "extensions", "mcp_servers")) or tools.get("resume") is not False:
            raise ValueError("unrelated skills/extensions/MCP or session resume must be disabled")
        if not isinstance(tools.get("runtime_tools"), list) or not tools["runtime_tools"] or not all(isinstance(x, str) and x for x in tools["runtime_tools"]):
            raise ValueError("effective runtime tool inventory is unresolved")
        policy = read_json(_file_ref(project, tools.get("runtime_enforcement")))
        if not isinstance(policy, dict):
            raise ValueError("wire policy must be an object")
        from .model_relay import encoded
        system = read_json(_file_ref(project, plan.get("system_prompt")))
        inventory = read_json(_file_ref(project, policy.get("tools")))
        if policy.get("status") != "verified":
            raise ValueError("wire policy is not verified")
        if not isinstance(system, (str, list)) or not system:
            raise ValueError("system prompt must contain the actual wire JSON value")
        if not isinstance(inventory, list) or not inventory or not all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in inventory):
            raise ValueError("wire tools must contain actual tool schemas")
        names = [item["name"] for item in inventory]
        if names != tools["runtime_tools"] or names != policy.get("runtime_tools") or len(set(names)) != len(names):
            raise ValueError("wire tool inventory differs from frozen runtime tools")
        if policy.get("wire_system_sha256") != digest(encoded(system)) or policy.get("wire_tools_sha256") != digest(encoded(inventory)):
            raise ValueError("wire system/tools hash does not bind the retained policy JSON")
        if "native_compaction" in policy:
            from .policy_capture import COMPACTION_SOURCES
            from .model_relay import Limits
            compaction = policy["native_compaction"]
            if not isinstance(compaction, dict) or compaction.get("status") != "verified" or compaction.get("tools") != "absent":
                raise ValueError("native compaction policy must be verified and require absent tools")
            summary = read_json(_file_ref(project, compaction.get("system")))
            if not isinstance(summary, list) or not summary or digest(encoded(summary)) != compaction.get("wire_system_sha256"):
                raise ValueError("native compaction system hash mismatch")
            Limits(expected_system_sha256=policy["wire_system_sha256"], expected_tools_sha256=policy["wire_tools_sha256"],
                   expected_compaction_system_sha256=compaction["wire_system_sha256"])
            audit = read_json(_file_ref(project, compaction.get("installed_audit")))
            sources = compaction.get("source_sha256")
            if (not isinstance(sources, dict) or set(sources) != set(COMPACTION_SOURCES)
                    or any(not isinstance(sha, str) or SHA256.fullmatch(sha) is None
                           or audit.get("source_sha256", {}).get(name) != sha for name, sha in sources.items())):
                raise ValueError("native compaction installed source hashes are unbound")
    except (ValueError, OSError, TypeError) as exc:
        blockers.append("tool configuration: " + str(exc))

    try:
        if plan.get("tasks") != snapshots(project):
            raise ValueError("public task package, contract or prompt hashes changed")
        package_path = Path(project) / "tasks/package-manifest.json"
        if plan.get("package_manifest_sha256") != file_hash(package_path):
            raise ValueError("task package manifest changed")
    except (ValueError, OSError, TypeError) as exc:
        blockers.append("task packages: " + str(exc))

    research_images = plan.get("research_images")
    for task in TASKS:
        try:
            image = research_images[task]
            if not isinstance(image, dict) or not isinstance(image.get("image_id"), str) or IMAGE_ID.fullmatch(image["image_id"]) is None:
                raise ValueError("missing immutable research image SHA256 ID")
            context = {name.removeprefix("environment/"): sha for name, sha in plan["tasks"][task]["package_files"].items()
                       if name.startswith("environment/")}
            context_sha = digest(canonical(context))
            inspection = read_json(_file_ref(project, image.get("inspection")))
            if image.get("build_context_sha256") != context_sha:
                raise ValueError("research image build context differs from package")
            if not isinstance(inspection, dict) or inspection.get("status") != "verified" or inspection.get("image_id") != image["image_id"] or inspection.get("build_context_sha256") != context_sha or inspection.get("task") != task:
                raise ValueError("research image inspection does not verify the declared task/image/context")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            blockers.append(f"{task} research image: {exc}")

    freezes = plan.get("freezes")
    for task in TASKS:
        try:
            if not isinstance(freezes, dict) or set(freezes) != set(TASKS):
                raise ValueError("all three task freeze references are required")
            frozen = validate_freeze_document(read_json(_file_ref(project, freezes[task])), task)
            research = frozen["research"]
            expected = {"model_id": MODEL_FIXED["model_id"], "model_version": model.get("model_version"),
                        **({"output_config": model["output_config"]} if model.get("thinking") == {"type": "enabled"} else {}),
                        "pi_version": MODEL_FIXED["pi_version"], "harbor_commit": MODEL_FIXED["harbor_commit"],
                        "temperature": model.get("temperature"), "reasoning_configuration": model.get("thinking"),
                        "output_token_limit": model.get("output_token_limit"),
                        "model_version_resolution": model.get("version_resolution"),
                        "model_parameter_enforcement": model.get("enforcement"),
                        "research_image_id": plan["research_images"][task]["image_id"],
                        "research_build_context_sha256": plan["research_images"][task]["build_context_sha256"],
                        "system_prompt_sha256": plan["system_prompt"]["sha256"],
                        "tool_config_sha256": plan["tool_config_sha256"], "run_matrix_sha256": plan["run_matrix_sha256"],
                        "prompt_hashes": plan["tasks"][task]["prompt_hashes"]}
            if any(research.get(key) != value for key, value in expected.items()):
                raise ValueError("frozen research settings differ from run plan")
            package = Path(project) / "tasks" / task
            if checked_hashes(package / "environment/public-dev") != frozen["data"]["public-dev"]["input_hashes"]:
                raise ValueError("packaged dev inputs differ from frozen data")
            evidence = plan["acceptance_evidence"][task]
            checks = (*ACCEPTANCE, "timing_profile") if task == "poisson" else ACCEPTANCE
            for check in checks:
                _file_ref(project, evidence[check])
                if evidence[check]["sha256"] != frozen["acceptance"][check]["evidence_sha256"]:
                    raise ValueError(f"{check} acceptance evidence differs from freeze")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            blockers.append(f"{task} freeze: {exc}")
    try:
        canonical(plan)
    except (ValueError, TypeError):
        blockers.append("plan contains non-finite or non-JSON values")
    return blockers


def validate_start(plan, project):
    blockers = start_blockers(plan, project)
    if blockers:
        raise RunPlanError(blockers)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft")
    draft.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    if args.command == "draft":
        if args.output.exists():
            parser.error("output exists; retain earlier drafts and use a new path")
        write_json(args.output, create_draft(project))
        print(f"Wrote 15-session draft only: {args.output}")
        return
    blockers = start_blockers(read_json(args.plan), project)
    print(canonical({"formal_ready": not blockers, "blockers": blockers}).decode())
    raise SystemExit(2 if blockers else 0)


if __name__ == "__main__":
    main()
