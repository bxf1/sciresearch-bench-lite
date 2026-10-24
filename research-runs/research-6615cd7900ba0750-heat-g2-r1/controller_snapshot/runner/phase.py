"""Trusted phase/manifest guard. Final-test execution requires a complete freeze.

The draft command only records available inputs and unresolved prerequisites. It
never promotes a document to frozen and never computes hidden recovery scores.
"""
from __future__ import annotations

import argparse
import copy
import datetime
from pathlib import Path
import re

from .artifact_gate import regular_tree, safe_relative
from .common import TASKS, VERSION, canonical, digest, file_hash, read_json, write_json

SPLIT_COUNTS = {"public-dev": 2, "author-calibration": 4, "final-test": 4, "pilot-smoke": 1}
FORMAL_SPLITS = ("public-dev", "author-calibration", "final-test")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
THRESHOLDS = {
    "heat": {"E_init": .15, "E_forward": .03, "score_init_scale": .30, "score_forward_scale": .06, "score_weights": [.8, .2], "replays": 3},
    "ode": {"E_roll": .05, "E_field": .05, "K": 10, "coefficient_zero_below": 1e-6, "score_scale": .10, "score_weights": [.5, .5], "integrator": "DOP853", "rtol": 1e-9, "atol": 1e-11, "hidden_time_grid": [0, 8, 401], "rollout_timeout_seconds": 5, "replays": 3},
    "poisson": {"E_res": 1e-8, "E_sol": 1e-5, "efficiency_gate": 1.5, "score_speedup_scale": 8, "measurement_order": "BCCBBC", "jacobi_rtol": 1e-10, "jacobi_atol": 0, "jacobi_maxiter": 10000},
}
RESOURCES = {"research_vcpu": 4, "research_memory_bytes": 4 * 1024**3, "research_seconds": 1800, "max_evaluations": 20,
             "worker_vcpu": 1, "worker_memory_bytes": 4 * 1024**3, "worker_swap_bytes": 0, "worker_pids": 128,
             "worker_threads": 1, "heat_ode_worker_seconds": 120, "poisson_worker_seconds": 60,
             "judge_seconds": 1200, "source_bytes": 20 * 1024**2, "source_files": 1000,
             "filesystem_entries": 2000, "filesystem_depth": 32, "output_bytes": 256 * 1024**2, "tmp_bytes": 64 * 1024**2}
DEPENDENCIES = {"python": "3.12.12", "numpy": "2.2.6", "scipy": "1.15.3"}
ACCEPTANCE = ("gt_qc", "calibration", "scorer_tests", "isolation", "resources", "model_smoke")


class PhaseError(ValueError):
    """Trusted contract or phase prerequisites are incomplete or mismatched."""


def validate_manifest(task, input_root, *, expected_split=None):
    """Validate cardinality and all case paths before any candidate/scorer runs."""
    if task not in TASKS:
        raise PhaseError("unknown task")
    root = Path(input_root)
    if root.is_symlink() or not root.is_dir():
        raise PhaseError("input root must be a real directory")
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 1024**2:
        raise PhaseError("manifest must be an ordinary file <=1 MiB")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("task") != task or manifest.get("contract_version") != VERSION:
        raise PhaseError("manifest task/contract mismatch")
    split = manifest.get("split")
    if split not in SPLIT_COUNTS or (expected_split is not None and split != expected_split):
        raise PhaseError("manifest split mismatch or unsupported split")
    if root.name in SPLIT_COUNTS and root.name != split:
        raise PhaseError("manifest split disagrees with input directory")
    if root.parent.name in TASKS and root.parent.name != task:
        raise PhaseError("manifest task disagrees with input directory")
    cases = manifest.get("cases")
    per_level = SPLIT_COUNTS[split]
    if not isinstance(cases, list) or len(cases) != 3 * per_level:
        raise PhaseError(f"{split} requires exactly {3 * per_level} cases")
    ids, paths, levels = set(), set(), [0, 0, 0]
    anchor = root.resolve(strict=True)
    for case in cases:
        if not isinstance(case, dict):
            raise PhaseError("manifest case must be an object")
        case_id, relative, level = case.get("id"), case.get("path"), case.get("level")
        if not isinstance(case_id, str) or CASE_ID.fullmatch(case_id) is None:
            raise PhaseError("unsafe or missing case ID")
        if not isinstance(relative, str) or relative != f"cases/{case_id}":
            raise PhaseError("case path must equal cases/<id>")
        safe_relative(relative)
        if case_id in ids or relative in paths:
            raise PhaseError("duplicate case ID/path")
        if type(level) is not int or level not in (0, 1, 2):
            raise PhaseError("case level must be 0, 1 or 2")
        directory = root / relative
        if (root / "cases").is_symlink() or directory.is_symlink() or not directory.is_dir() or not directory.resolve(strict=True).is_relative_to(anchor):
            raise PhaseError("case directory is missing, linked or outside input root")
        ids.add(case_id)
        paths.add(relative)
        levels[level] += 1
    if levels != [per_level] * 3:
        raise PhaseError(f"{split} requires {per_level} cases per level")
    return manifest


def checked_hashes(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(regular_tree(root))}


def _hash_map(value, label):
    if not isinstance(value, dict) or not value:
        raise PhaseError(f"missing {label} hashes")
    for path, sha256 in value.items():
        safe_relative(path)
        if not isinstance(sha256, str) or SHA256.fullmatch(sha256) is None:
            raise PhaseError(f"invalid {label} SHA256")


def _sha(value, label):
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise PhaseError(f"missing or invalid {label} SHA256")


def validate_freeze_document(freeze, task):
    """Validate the complete declared protocol, without trusting a status alone."""
    if not isinstance(freeze, dict) or freeze.get("status") != "frozen":
        raise PhaseError("final-test requires status=frozen; a draft is not authorization")
    if freeze.get("schema_version") != 1 or freeze.get("contract_version") != VERSION or freeze.get("task") != task:
        raise PhaseError("freeze schema/task/contract mismatch")
    if freeze.get("thresholds") != THRESHOLDS[task] or freeze.get("resources") != RESOURCES or freeze.get("dependencies") != DEPENDENCIES:
        raise PhaseError("freeze thresholds/resources/dependencies differ from implemented contract")
    profiles = ("efficiency_gate_1.5", "accuracy_with_efficiency_diagnostic") if task == "poisson" else ("accuracy",)
    if freeze.get("profile") not in profiles:
        raise PhaseError("missing or unsupported frozen profile")
    if not isinstance(freeze.get("image_id"), str) or IMAGE_ID.fullmatch(freeze["image_id"]) is None:
        raise PhaseError("freeze requires an immutable image SHA256 ID")
    data = freeze.get("data")
    if not isinstance(data, dict) or set(data) != set(FORMAL_SPLITS):
        raise PhaseError("freeze must describe all three formal splits")
    for split, values in data.items():
        if not isinstance(values, dict) or set(values) != {"input_hashes", "truth_hashes"}:
            raise PhaseError("freeze split must contain input and truth hashes")
        _hash_map(values["input_hashes"], split + " input")
        _hash_map(values["truth_hashes"], split + " truth")
        if "manifest.json" not in values["input_hashes"]:
            raise PhaseError("freeze is missing an input manifest hash")
    if freeze.get("data_sha256") != digest(canonical(data)):
        raise PhaseError("freeze data digest mismatch")
    _hash_map(freeze.get("judge_source_hashes"), "judge source")
    required = {"judge/batch.py", f"judge/{task}.py", f"public/{task}.py", "runner/common.py", "runner/artifact_gate.py", "runner/phase.py"}
    if not required.issubset(freeze["judge_source_hashes"]):
        raise PhaseError("freeze is missing required trusted judge source")
    if freeze.get("judge_sha256") != digest(canonical(freeze["judge_source_hashes"])):
        raise PhaseError("freeze judge digest mismatch")
    research = freeze.get("research")
    if not isinstance(research, dict):
        raise PhaseError("freeze is missing research configuration")
    for key in ("model_id", "pi_version"):
        if not isinstance(research.get(key), str) or not research[key].strip():
            raise PhaseError(f"freeze is missing {key}")
    if not isinstance(research.get("harbor_commit"), str) or re.fullmatch(r"[0-9a-f]{40}", research["harbor_commit"]) is None:
        raise PhaseError("freeze is missing exact Harbor commit")
    for key in ("system_prompt_sha256", "tool_config_sha256", "run_matrix_sha256"):
        _sha(research.get(key), key)
    prompts = research.get("prompt_hashes")
    _hash_map(prompts, "prompt")
    if set(prompts) != {"common.md", "g1.md", "g2.md", "g3.md"}:
        raise PhaseError("freeze must contain all three guidance conditions and the common prompt")
    if type(research.get("output_token_limit")) is not int or research["output_token_limit"] <= 0:
        raise PhaseError("freeze requires a positive output token budget")
    if any(key not in research for key in ("model_version", "temperature", "reasoning_configuration")):
        raise PhaseError("freeze must explicitly record model version/sampling/reasoning (null when unavailable)")
    acceptance = freeze.get("acceptance")
    required_checks = (*ACCEPTANCE, "timing_profile") if task == "poisson" else ACCEPTANCE
    if not isinstance(acceptance, dict):
        raise PhaseError("freeze is missing acceptance evidence")
    for key in required_checks:
        check = acceptance.get(key)
        if not isinstance(check, dict) or check.get("status") != "passed":
            raise PhaseError(f"freeze prerequisite not passed: {key}")
        _sha(check.get("evidence_sha256"), key + " evidence")
    # Reject non-finite numbers even when they came from legal JSON exponent syntax.
    canonical(freeze)
    return freeze


def guard_replay(task, input_root, truth_root, image, judge_source_root, *, freeze_path=None, profile=None):
    manifest = validate_manifest(task, input_root)
    split = manifest["split"]
    if split != "final-test":
        return {"split": split, "formal": False, "freeze_sha256": None, "profile": profile}
    if freeze_path is None:
        raise PhaseError("final-test is locked until a complete frozen configuration is supplied via --freeze")
    freeze_path = Path(freeze_path)
    if freeze_path.is_symlink() or not freeze_path.is_file() or freeze_path.stat().st_size > 16 * 1024**2:
        raise PhaseError("freeze must be an ordinary file <=16 MiB")
    freeze = validate_freeze_document(read_json(freeze_path), task)
    if image != freeze["image_id"]:
        raise PhaseError("execution image differs from frozen immutable image")
    if profile is not None and profile != freeze["profile"]:
        raise PhaseError("requested profile differs from frozen profile")
    expected = freeze["data"][split]
    if checked_hashes(input_root) != expected["input_hashes"]:
        raise PhaseError("final-test input hashes differ from freeze")
    if checked_hashes(truth_root) != expected["truth_hashes"]:
        raise PhaseError("final-test truth hashes differ from freeze")
    if checked_hashes(judge_source_root) != freeze["judge_source_hashes"]:
        raise PhaseError("trusted judge source hashes differ from freeze")
    return {"split": split, "formal": True, "freeze_sha256": file_hash(freeze_path), "profile": freeze["profile"]}


def create_draft(project, data_root, task, image, judge_source_root):
    """Read/hash data and sources, leaving every unverified acceptance item pending."""
    project, data_root = Path(project), Path(data_root)
    if task not in TASKS:
        raise PhaseError("unknown task")
    data = {}
    for split in FORMAL_SPLITS:
        inputs = data_root / "inputs" / task / split
        truth = data_root / "private" / task / split
        validate_manifest(task, inputs, expected_split=split)
        data[split] = {"input_hashes": checked_hashes(inputs), "truth_hashes": checked_hashes(truth)}
    judge = checked_hashes(judge_source_root)
    prompts = {name: file_hash(project / "prompts" / task / name) for name in ("common.md", "g1.md", "g2.md", "g3.md")}
    checks = (*ACCEPTANCE, "timing_profile") if task == "poisson" else ACCEPTANCE
    return {"schema_version": 1, "status": "draft", "task": task, "contract_version": VERSION,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "data": data, "data_sha256": digest(canonical(data)), "judge_source_hashes": judge,
            "judge_sha256": digest(canonical(judge)), "image_id": image,
            "thresholds": copy.deepcopy(THRESHOLDS[task]), "profile": None if task == "poisson" else "accuracy",
            "resources": copy.deepcopy(RESOURCES), "dependencies": copy.deepcopy(DEPENDENCIES),
            "research": {"model_id": None, "model_version": None, "pi_version": None, "harbor_commit": None,
                         "prompt_hashes": prompts, "system_prompt_sha256": None, "tool_config_sha256": None,
                         "run_matrix_sha256": None, "output_token_limit": None, "temperature": None, "reasoning_configuration": None},
            "acceptance": {key: {"status": "pending", "evidence_sha256": None} for key in checks},
            "limitations": ["Draft only: resource, calibration, scoring, isolation and model evidence must be verified before freezing.",
                            "This command did not run final-test submissions or compute hidden scores."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["draft"])
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--judge-source", type=Path, required=True)
    parser.add_argument("--image", required=True, help="Prefer the inspected immutable sha256 image ID")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; drafts must not overwrite an earlier version")
    value = create_draft(Path(__file__).resolve().parents[1], args.data, args.task, args.image, args.judge_source)
    write_json(args.output, value)
    print(f"Wrote draft only: {args.output}")
