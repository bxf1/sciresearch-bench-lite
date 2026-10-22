"""Phase-lock tests use synthetic files and temporary frozen fixtures only.

No fixture is a real acceptance decision or a published benchmark freeze.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runner import phase, replay
from runner.common import VERSION, write_json
from judge import batch


class PhaseTests(unittest.TestCase):
    image = "sha256:" + "a" * 64

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data = self.base / "data"
        self.project = self.base / "project"
        for name in ("common.md", "g1.md", "g2.md", "g3.md"):
            path = self.project / "prompts/heat" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test public prompt " + name)
        self.judge = self.base / "trusted"
        for name in ("judge/batch.py", "judge/heat.py", "public/heat.py", "runner/common.py", "runner/artifact_gate.py", "runner/phase.py"):
            path = self.judge / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# test-only trusted source placeholder\n")
        for split in phase.SPLIT_COUNTS:
            self.make_split(split)
        self.inputs = self.data / "inputs/heat/final-test"
        self.truth = self.data / "private/heat/final-test"
        self.freeze_path = self.base / "temporary-unit-test-freeze.json"
        self.draft = phase.create_draft(self.project, self.data, "heat", self.image, self.judge)

    def make_split(self, split):
        inputs = self.data / "inputs/heat" / split
        truth = self.data / "private/heat" / split
        cases = []
        for level in range(3):
            for index in range(phase.SPLIT_COUNTS[split]):
                case_id = f"case-{level}-{index}"
                relative = "cases/" + case_id
                (inputs / relative).mkdir(parents=True)
                (truth / relative).mkdir(parents=True)
                (inputs / relative / "observed.txt").write_text(f"{split},{level},{index}\n")
                (truth / relative / "truth.txt").write_text("synthetic test truth\n")
                cases.append({"id": case_id, "path": relative, "level": level})
        write_json(inputs / "manifest.json", {"task": "heat", "split": split, "contract_version": VERSION, "cases": cases})
        return inputs, truth

    def fixture(self):
        value = copy.deepcopy(self.draft)
        value["status"] = "frozen"
        value["research"].update(model_id="unit-test-model", pi_version="unit-test-version", harbor_commit="a" * 40,
                                  system_prompt_sha256="b" * 64, tool_config_sha256="c" * 64,
                                  run_matrix_sha256="d" * 64, output_token_limit=100)
        for check in value["acceptance"].values():
            check.update(status="passed", evidence_sha256="e" * 64)
        write_json(self.freeze_path, value)
        return value

    def guard(self, **kwargs):
        options = {"freeze_path": self.freeze_path, **kwargs}
        return phase.guard_replay("heat", self.inputs, self.truth, self.image, self.judge, **options)

    def edit_manifest(self, change, root=None):
        root = root or self.inputs
        path = root / "manifest.json"
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_all_four_declared_split_cardinalities(self):
        for split, count in phase.SPLIT_COUNTS.items():
            inputs = self.data / "inputs/heat" / split
            manifest = phase.validate_manifest("heat", inputs, expected_split=split)
            self.assertEqual(len(manifest["cases"]), count * 3)

    def test_empty_and_missing_case_denominators_rejected(self):
        original = (self.inputs / "manifest.json").read_text()
        for change in (lambda value: value.update(cases=[]), lambda value: value["cases"].pop()):
            (self.inputs / "manifest.json").write_text(original)
            self.edit_manifest(change)
            with self.assertRaises(phase.PhaseError):
                phase.validate_manifest("heat", self.inputs)

    def test_task_contract_split_and_level_mismatches(self):
        original = (self.inputs / "manifest.json").read_text()
        changes = [lambda v: v.update(task="ode"), lambda v: v.update(contract_version="0.2"),
                   lambda v: v.update(split="author-calibration"), lambda v: v.update(split="invented"),
                   lambda v: v["cases"][0].update(level=1), lambda v: v["cases"][0].update(level=False)]
        for change in changes:
            (self.inputs / "manifest.json").write_text(original)
            self.edit_manifest(change)
            with self.assertRaises(phase.PhaseError):
                phase.validate_manifest("heat", self.inputs)

    def test_case_ids_paths_and_links_cannot_escape(self):
        original = (self.inputs / "manifest.json").read_text()
        changes = [lambda v: v["cases"][0].update(id="../outside"),
                   lambda v: v["cases"][0].update(path="../outside"),
                   lambda v: v["cases"][0].update(path="/absolute"),
                   lambda v: v["cases"][0].update(path="cases/case-0-1"),
                   lambda v: v["cases"].__setitem__(1, dict(v["cases"][0]))]
        for change in changes:
            (self.inputs / "manifest.json").write_text(original)
            self.edit_manifest(change)
            with self.assertRaises(phase.PhaseError):
                phase.validate_manifest("heat", self.inputs)
        (self.inputs / "manifest.json").write_text(original)
        directory = self.inputs / "cases/case-0-0"
        directory.rename(self.base / "outside")
        directory.symlink_to(self.base / "outside", target_is_directory=True)
        with self.assertRaises(phase.PhaseError):
            phase.validate_manifest("heat", self.inputs)

    def test_final_without_freeze_is_locked_before_worker(self):
        with patch.object(replay, "run_worker", side_effect=AssertionError("must not start W")):
            with self.assertRaisesRegex(phase.PhaseError, "locked"):
                replay.replay_single(self.base / "candidate", task="heat", input_root=self.inputs, truth_root=self.truth,
                                     output_root=self.base / "replay-output", image=self.image, judge_source_root=self.judge)
        self.assertFalse((self.base / "replay-output").exists())

    def test_draft_creator_never_freezes_or_claims_acceptance(self):
        self.assertEqual(self.draft["status"], "draft")
        self.assertTrue(all(value["status"] == "pending" for value in self.draft["acceptance"].values()))
        write_json(self.freeze_path, self.draft)
        with self.assertRaisesRegex(phase.PhaseError, "status=frozen"):
            self.guard()
        self.draft["thresholds"]["E_init"] = 99
        self.assertEqual(phase.THRESHOLDS["heat"]["E_init"], .15)

    def test_status_alone_does_not_bypass_complete_freeze_requirements(self):
        value = copy.deepcopy(self.draft)
        value["status"] = "frozen"
        write_json(self.freeze_path, value)
        with self.assertRaises(phase.PhaseError):
            self.guard()

    def test_matching_complete_fixture_admits_final(self):
        self.fixture()
        result = self.guard()
        self.assertTrue(result["formal"])
        self.assertEqual(result["split"], "final-test")
        self.assertEqual(result["profile"], "accuracy")
        self.assertEqual(len(result["freeze_sha256"]), 64)

    def test_input_truth_and_judge_tampering_rejected(self):
        self.fixture()
        for path in (self.inputs / "cases/case-0-0/observed.txt", self.truth / "cases/case-0-0/truth.txt", self.judge / "judge/heat.py"):
            original = path.read_bytes()
            path.write_bytes(original + b"tamper")
            with self.subTest(path=path), self.assertRaisesRegex(phase.PhaseError, "hashes differ"):
                self.guard()
            path.write_bytes(original)

    def test_image_profile_thresholds_and_evidence_mismatch_rejected(self):
        frozen = self.fixture()
        with self.assertRaisesRegex(phase.PhaseError, "image differs"):
            phase.guard_replay("heat", self.inputs, self.truth, "mutable:latest", self.judge, freeze_path=self.freeze_path)
        with self.assertRaisesRegex(phase.PhaseError, "profile differs"):
            self.guard(profile="efficiency_gate_1.5")
        mutations = [lambda v: v["thresholds"].update(E_init=.2),
                     lambda v: v.update(image_id="mutable:latest"),
                     lambda v: v["acceptance"]["isolation"].update(status="pending"),
                     lambda v: v["data"].pop("author-calibration"),
                     lambda v: v["research"].update(output_token_limit=None),
                     lambda v: v.update(judge_sha256="0" * 64)]
        for change in mutations:
            value = copy.deepcopy(frozen)
            change(value)
            write_json(self.freeze_path, value)
            with self.assertRaises(phase.PhaseError):
                self.guard()

    def test_nonfinal_phases_work_without_freeze(self):
        for split in ("public-dev", "author-calibration", "pilot-smoke"):
            result = phase.guard_replay("heat", self.data / "inputs/heat" / split, self.data / "private/heat" / split,
                                        self.image, self.judge)
            self.assertFalse(result["formal"])
            self.assertIsNone(result["freeze_sha256"])

    def test_judge_batch_rejects_manifest_or_unfrozen_final_before_scoring(self):
        with patch.object(batch.importlib, "import_module", side_effect=AssertionError("must not import scorer")):
            result = batch.score_batch("heat", self.inputs, self.truth, self.base / "artifacts")
            self.assertEqual(result["evaluation_status"], "evaluation_invalid")
            self.assertIsNone(result["reward"])
            self.edit_manifest(lambda v: v.update(cases=[]))
            result = batch.score_batch("heat", self.inputs, self.truth, self.base / "artifacts")
            self.assertEqual(result["evaluation_status"], "evaluation_invalid")

    def test_valid_pilot_batch_keeps_missing_outputs_in_denominator(self):
        calls = []
        def fake_score(inputs, truth, artifact):
            calls.append(str(artifact))
            return {"scientific_pass": len(calls) != 2, "score": 0 if len(calls) == 2 else 100,
                    "artifact_valid": len(calls) != 2, "evaluation_status": "valid"}
        with patch.object(batch.importlib, "import_module", return_value=SimpleNamespace(score_case=fake_score)):
            result = batch.score_batch("heat", self.data / "inputs/heat/pilot-smoke", self.data / "private/heat/pilot-smoke", self.base / "artifacts")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["passed"], 2)
        self.assertEqual(result["reward"], 0)
        self.assertAlmostEqual(result["score"], 200 / 3)

    def test_public_feedback_rejects_private_splits(self):
        with patch.object(replay.importlib, "import_module", side_effect=AssertionError("must not import scorer")):
            with self.assertRaisesRegex(phase.PhaseError, "research feedback"):
                replay.evaluate_public("heat", self.inputs, self.base / "artifacts")


if __name__ == "__main__":
    unittest.main()
