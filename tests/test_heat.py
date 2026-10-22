"""T1 numerical and negative scorer checks on disposable synthetic instances."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


author = load("heat_author_test", "authoring/heat.py")
public = load("heat_public_test", "public/heat.py")
judge = load("heat_judge_test", "judge/heat.py")
baseline = load("heat_baseline_test", "baselines/heat/solve.py")


class HeatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.input, self.private = root / "input", root / "private"
        self.input.mkdir()
        self.private.mkdir()
        rngs = {key: np.random.default_rng(seed) for key, seed in zip(("system", "mask", "noise", "solution"), (42002, 42003, 42004, 42005))}
        self.result = author.generate_case(self.input, self.private, 2, rngs)
        self.artifact = root / "u0.npy"
        self.truth = np.load(self.private / "u0_true.npy", allow_pickle=False)

    def save(self, values):
        np.save(self.artifact, values, allow_pickle=False)

    def test_gt_qc_and_gt_score(self):
        self.assertTrue(self.result["qc"]["passed"])
        self.assertAlmostEqual(self.result["qc"]["discrete_rms"], np.sqrt(257 / 256), places=13)
        self.assertGreaterEqual(min(self.result["qc"]["observations_per_time"]), 64)
        self.save(self.truth)
        score = judge.score_case(self.input, self.private, self.artifact)
        self.assertTrue(score["scientific_pass"])
        self.assertAlmostEqual(score["score"], 100, places=10)

    def test_zero_and_scaled_output(self):
        self.save(np.zeros(256, dtype="<f8"))
        score = judge.score_case(self.input, self.private, self.artifact)
        self.assertTrue(score["artifact_valid"])
        self.assertFalse(score["scientific_pass"])
        self.assertEqual(score["score"], 0)
        self.assertAlmostEqual(score["E_init"], 1)
        self.save(self.truth * 1.02)
        score = judge.score_case(self.input, self.private, self.artifact)
        self.assertTrue(score["scientific_pass"])
        self.assertAlmostEqual(score["E_init"], .02)
        self.assertAlmostEqual(score["E_forward"], .02)
        self.save(self.truth * 1.031)
        self.assertFalse(judge.score_case(self.input, self.private, self.artifact)["scientific_pass"])

    def test_no_32_mode_truncation(self):
        grid = np.arange(1, 257) / 257
        self.save(self.truth + .4 * np.sin(np.pi * 100 * grid))
        score = judge.score_case(self.input, self.private, self.artifact)
        self.assertGreater(score["E_init"], .15)
        self.assertFalse(score["scientific_pass"])
        self.assertLess(score["E_forward"], 1e-12)

    def test_public_diagnostics_at_actual_points(self):
        self.save(self.truth)
        diagnostic = public.check_case(self.input, self.artifact)
        meta = json.loads((self.input / "metadata.json").read_text())
        noise = np.load(self.private / "noise.npy", allow_pickle=False)
        expected = float(np.sum(noise**2) / (len(noise) * meta["sigma"]**2))
        self.assertAlmostEqual(diagnostic["R"], expected, places=11)
        self.assertGreater(diagnostic["roughness"], 0)
        self.assertNotIn("E_init", diagnostic)
        self.assertNotIn("score", diagnostic)

    def test_malformed_outputs(self):
        for values in (np.zeros(255), np.zeros(256, dtype=np.float32), np.zeros(256, dtype=">f8"), np.full(256, np.nan), np.zeros(256, dtype=complex)):
            with self.subTest(dtype=str(values.dtype), shape=values.shape):
                self.save(values)
                result = judge.score_case(self.input, self.private, self.artifact)
                self.assertFalse(result["artifact_valid"])
                self.assertEqual(result["score"], 0)
                self.assertEqual(result["evaluation_status"], "valid")
                self.assertFalse(public.check_case(self.input, self.artifact)["artifact_valid"])

    def test_large_finite_output_is_candidate_failure(self):
        self.save(np.full(256, 1e308))
        result = judge.score_case(self.input, self.private, self.artifact)
        self.assertTrue(result["artifact_valid"])
        self.assertEqual(result["score"], 0)
        self.assertIn("candidate_numeric_failure", result["reason"])
        self.assertEqual(result["evaluation_status"], "valid")

    def test_corrupted_gt_invalidates_evaluation(self):
        self.save(self.truth)
        np.save(self.private / "future_true.npy", np.zeros(256), allow_pickle=False)
        with self.assertRaises(judge.EvaluationInvalid):
            judge.score_case(self.input, self.private, self.artifact)

    def test_wrong_gt_dtype_is_evaluation_invalid(self):
        self.save(self.truth)
        np.save(self.private / "u0_true.npy", self.truth.astype(complex), allow_pickle=False)
        with self.assertRaises(judge.EvaluationInvalid):
            judge.score_case(self.input, self.private, self.artifact)

    def test_five_baselines_and_independent_accepted_method(self):
        for method in ("ls", "rank5", "tikhonov", "discrepancy", "tsvd"):
            with self.subTest(method=method):
                solution, diagnostic = baseline.solve_case(self.input, method)
                self.assertEqual(solution.shape, (256,))
                self.assertTrue(np.isfinite(solution).all())
                self.save(solution)
                result = judge.score_case(self.input, self.private, self.artifact)
                self.assertTrue(result["artifact_valid"])
                if method in ("rank5", "tikhonov", "discrepancy", "tsvd"):
                    self.assertTrue(result["scientific_pass"], (method, result))

    def test_discrepancy_fallback(self):
        # An impossible public residual bound exercises the fixed rank-five fallback.
        meta_path = self.input / "metadata.json"
        meta = json.loads(meta_path.read_text())
        meta["sigma"] = 1e-100
        meta_path.write_text(json.dumps(meta))
        expected, _ = baseline.solve_case(self.input, "rank5")
        for method in ("discrepancy", "tsvd"):
            actual, diagnostic = baseline.solve_case(self.input, method)
            self.assertTrue(diagnostic["fallback"])
            np.testing.assert_array_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
