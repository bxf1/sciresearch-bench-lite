"""Three complete Jacobi/LU groups on author-calibration, never final-test.

Without a frozen TimingLease resource contract every measurement is diagnostic
and profile remains null. An explicit trusted investigator callback may request
one linked rerun after observing baseline instability; failures are retained.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .common import canonical, digest, tree_hashes, write_json
from .performance import calibrate_profile
from .phase import validate_manifest
from .replay import prepare_judge, run_t3_attempt, retry_t3_attempt
from .worker import docker
import json


def calibrate_t3(project, data, output, image, *, timing_contract=None, investigate=None,
                 execute=None, judge_source_root=None):
    project, data, output = map(lambda path: Path(path).resolve(), (project, data, output))
    inputs = data / "inputs/poisson/author-calibration"
    truth = data / "private/poisson/author-calibration"
    validate_manifest("poisson", inputs, expected_split="author-calibration")
    if not truth.is_dir():
        raise ValueError("author-calibration truth directory is missing")
    output.mkdir(parents=True, exist_ok=False)
    judge = judge_source_root or prepare_judge(project, project / "build/judge")
    source = project / "baselines/poisson"
    groups, records = [], []
    provenance = {"source_sha256": digest(canonical(tree_hashes(source))),
                  "input_sha256": digest(canonical(tree_hashes(inputs))), "image": image,
                  "final_test_scores_accessed": False, "group_count_required": 3,
                  "timing_contract": str(timing_contract) if timing_contract is not None else None}
    for index in range(3):
        options = {"task": "poisson", "input_root": inputs, "truth_root": truth, "image": image,
                   "judge_source_root": judge, "baseline_source": source, "candidate_method": "lu",
                   "timing_contract": timing_contract, "execute": execute}
        result = run_t3_attempt(source, output_root=output / f"group-{index+1}-attempt-1", **options)
        attempts = [result["protocol_attempt"]]
        if result.get("retry_permitted") and investigate is not None:
            explanation = investigate(index + 1, result)
            if explanation:
                result = retry_t3_attempt(result, source, interference_resolution=explanation,
                    output_root=output / f"group-{index+1}-attempt-2", **options)
                attempts.append(result["protocol_attempt"])
        groups.append(attempts)
        records.append(result)
        write_json(output / "progress.json", {**provenance, "completed_groups": len(groups), "groups": records})
    result = {**provenance, **calibrate_profile(groups), "group_results": records}
    write_json(output / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="sciresearch-numeric:0.3.0")
    parser.add_argument("--timing-contract", type=Path)
    args = parser.parse_args()
    image = json.loads(docker("image", "inspect", args.image).stdout)[0]["Id"]
    result = calibrate_t3(Path(__file__).resolve().parents[1], args.data, args.output, image,
                          timing_contract=args.timing_contract)
    print(json.dumps({"status": result["status"], "profile": result["profile"], "formal_profile_ready": result["formal_profile_ready"]}))


if __name__ == "__main__":
    main()
