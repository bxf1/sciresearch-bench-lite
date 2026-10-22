"""Generation protocol tests use mock physics, never formal hidden recovery scores."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from authoring import generate as generation
from runner.common import read_json, tree_hashes


class GenerateTests(unittest.TestCase):
    entropy = "e4" * 32

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.calls = []

    def mock_generator(self, public_dir, private_dir, level, rngs):
        self.calls.append((str(public_dir), level))
        system = rngs["system"].bytes(32)
        fingerprint = hashlib.sha256(system).hexdigest()
        # Fake public observations and independent private latent data are enough
        # to test split mechanics without generating scientific benchmark cases.
        (public_dir / "observations.json").write_text(json.dumps({"level": level, "observed": rngs["noise"].normal(size=4).tolist()}))
        np.save(public_dir / "target_grid.npy", np.arange(4, dtype=float), allow_pickle=False)
        (private_dir / "latent.bin").write_bytes(system)
        return {"qc": {"passed": True}, "latent_fingerprint": fingerprint,
                "operator_fingerprint": "fixed-easy-operator" if level == 0 else hashlib.sha256(rngs["mask"].bytes(32)).hexdigest()}

    def run_mock(self, path, tasks=("heat", "ode", "poisson"), **kwargs):
        module = SimpleNamespace(generate_case=self.mock_generator)
        with patch.object(generation.secrets, "token_hex", return_value=self.entropy), patch.object(generation.importlib, "import_module", return_value=module):
            return generation.generate(path, tasks, **kwargs)

    def test_namespace_stability_and_separation_across_process_hash_seeds(self):
        key = ("heat", "final-test", 2, 3, "noise")
        first = generation.namespace_rng(self.entropy, *key).normal(size=16)
        second = generation.namespace_rng(self.entropy, *key).normal(size=16)
        np.testing.assert_array_equal(first, second)
        variants = [(*key[:-1], c) for c in generation.COMPONENTS]
        digests = {generation.namespace_rng(self.entropy, *parts).bytes(64) for parts in variants}
        self.assertEqual(len(digests), len(variants))
        code = "from authoring.generate import namespace_rng; import hashlib; print(hashlib.sha256(namespace_rng('" + self.entropy + "','heat','final-test',2,3,'noise').normal(size=16).tobytes()).hexdigest())"
        observed = []
        for seed in ("1", "7654321"):
            env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)}
            observed.append(subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip())
        self.assertEqual(observed, [hashlib.sha256(first.tobytes()).hexdigest()] * 2)

    def test_formal_counts_public_privacy_and_source_hash_scope(self):
        root = self.base / "formal-mocked"
        result = self.run_mock(root)
        self.assertEqual(result["cases"], 90)
        self.assertEqual(len(self.calls), 90)
        for task in ("heat", "ode", "poisson"):
            task_count = 0
            for split, per_level in generation.SPLITS.items():
                manifest = read_json(root / "inputs" / task / split / "manifest.json")
                self.assertEqual(len(manifest["cases"]), per_level * 3)
                task_count += len(manifest["cases"])
                for level in range(3):
                    self.assertEqual(sum(c["level"] == level for c in manifest["cases"]), per_level)
                self.assertTrue(all(len(c["id"]) == 20 for c in manifest["cases"]))
            self.assertEqual(task_count, 30)
            audit = read_json(root / "private" / task / "split_audit.json")
            self.assertEqual(audit["latent_unique"], 30)
        private = read_json(root / "private/generation.json")
        self.assertEqual(private["root_entropy"], self.entropy)
        self.assertTrue(private["source_hashes"])
        self.assertTrue(all(key.endswith(".py") and "__pycache__" not in key and "data" not in Path(key).parts for key in private["source_hashes"]))
        self.assertIn("runner/common.py", private["source_hashes"])
        for key, expected in private["source_hashes"].items():
            self.assertEqual(hashlib.sha256((root / "private/generator-code" / key).read_bytes()).hexdigest(), expected)
        audit = read_json(root / "private/heat/split_audit.json")
        grids = [group for group in audit["shared_files"] if all(row["path"] == "target_grid.npy" for row in group["occurrences"])]
        self.assertEqual(len(grids), 1)
        self.assertTrue(grids[0]["cross_split"])
        self.assertTrue(grids[0]["all_occurrences_expected_shared"])
        self.assertEqual(len(grids[0]["occurrences"]), 30)
        for path in (root / "inputs").rglob("*"):
            if path.is_file():
                self.assertNotIn(self.entropy.encode(), path.read_bytes())
                self.assertNotIn(b"root_entropy", path.read_bytes())

    def test_saved_entropy_reproduces_inputs_and_private_cases(self):
        first, second = self.base / "first", self.base / "second"
        self.run_mock(first, tasks=("heat",), smoke=True)
        self.run_mock(second, tasks=("heat",), smoke=True)
        self.assertEqual(tree_hashes(first / "inputs"), tree_hashes(second / "inputs"))
        self.assertEqual(tree_hashes(first / "private/heat"), tree_hashes(second / "private/heat"))

    def test_explicit_entropy_api_and_invalid_entropy(self):
        with patch.object(generation.importlib, "import_module", return_value=SimpleNamespace(generate_case=self.mock_generator)), patch.object(generation.secrets, "token_hex", side_effect=AssertionError("do not resample entropy")):
            root = self.base / "explicit"
            generation.generate(root, ("heat",), smoke=True, entropy=self.entropy)
        self.assertEqual(read_json(root / "private/generation.json")["root_entropy"], self.entropy)
        for index, entropy in enumerate(("bad", "z" * 64, 100, " " * 64)):
            root = self.base / f"invalid-{index}"
            with self.assertRaises(ValueError):
                generation.generate(root, ("heat",), smoke=True, entropy=entropy)
            self.assertFalse(root.exists())

    def test_generation_failure_preserves_partial_case_and_never_retries(self):
        calls = []
        def fail(public_dir, private_dir, level, rngs):
            calls.append(level)
            (private_dir / "partial.txt").write_text("retain this failed attempt")
            raise ValueError("deliberate QC failure")
        root = self.base / "failed"
        with patch.object(generation.importlib, "import_module", return_value=SimpleNamespace(generate_case=fail)):
            with self.assertRaisesRegex(ValueError, "deliberate QC failure"):
                generation.generate(root, ("heat",), smoke=True)
        self.assertEqual(calls, [0])
        self.assertEqual(read_json(root / "private/generation.json")["status"], "generation_failed")
        evidence = list(root.rglob("generation_failure.json"))
        self.assertEqual(len(evidence), 1)
        self.assertTrue(read_json(evidence[0])["replacement_forbidden"])
        self.assertEqual(len(list(root.rglob("partial.txt"))), 1)

    def test_duplicate_latent_is_recorded_as_failed_generation(self):
        original = self.mock_generator
        def duplicate(*args):
            evidence = original(*args)
            evidence["latent_fingerprint"] = "repeated-system"
            return evidence
        root = self.base / "duplicate"
        with patch.object(generation.importlib, "import_module", return_value=SimpleNamespace(generate_case=duplicate)):
            with self.assertRaises(Exception):
                generation.generate(root, ("heat",), smoke=True)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(read_json(root / "private/generation.json")["status"], "generation_failed")
        self.assertTrue(list(root.rglob("generation_failure.json")))

    def test_false_qc_cannot_be_declared_passed(self):
        original = self.mock_generator
        def failed_qc(*args):
            evidence = original(*args)
            evidence["qc"]["passed"] = False
            return evidence
        root = self.base / "false-qc"
        with patch.object(generation.importlib, "import_module", return_value=SimpleNamespace(generate_case=failed_qc)):
            with self.assertRaises(Exception):
                generation.generate(root, ("heat",), smoke=True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(read_json(root / "private/generation.json")["status"], "generation_failed")

    def test_byte_identical_whole_case_is_rejected_despite_unique_latent(self):
        original = self.mock_generator
        def duplicate_inputs(*args):
            evidence = original(*args)
            (args[0] / "observations.json").write_text('{"same":true}')
            return evidence
        root = self.base / "duplicate-inputs"
        with patch.object(generation.importlib, "import_module", return_value=SimpleNamespace(generate_case=duplicate_inputs)):
            with self.assertRaisesRegex(RuntimeError, "byte-identical"):
                generation.generate(root, ("heat",), smoke=True)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(read_json(root / "private/generation.json")["status"], "generation_failed")
        self.assertTrue(list(root.rglob("generation_failure.json")))


if __name__ == "__main__":
    unittest.main()
