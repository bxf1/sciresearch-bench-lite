from __future__ import annotations

import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from authoring.ode import generate_case
from judge.ode import score_case
from public.ode import bounded_rollout, check_case, load_model


class OdeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.public = cls.root / "public"
        cls.private = cls.root / "private"
        cls.public.mkdir()
        cls.private.mkdir()
        rngs = {name: np.random.Generator(np.random.PCG64(np.random.SeedSequence([8123, i])))
                for i, name in enumerate(("system", "mask", "noise", "solution"))}
        cls.generated = generate_case(cls.public, cls.private, 2, rngs)
        cls.coefficients = np.load(cls.private / "coefficients.npy", allow_pickle=False)
        spec = importlib.util.spec_from_file_location("ode_baseline", Path(__file__).parents[1] / "baselines/ode/solve.py")
        cls.baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.baseline)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def artifact(self, coefficients):
        path = self.root / "model.json"
        path.write_text(json.dumps({"coefficients": np.asarray(coefficients).tolist()}, allow_nan=False))
        return path

    def test_gt_qc_and_noiseless_score(self):
        qc = self.generated["qc"]
        self.assertTrue(qc["passed"])
        self.assertEqual(qc["dictionary_rank"], 10)
        score = score_case(self.public, self.private, self.artifact(self.coefficients))
        self.assertTrue(score["artifact_valid"])
        self.assertTrue(score["scientific_pass"])
        self.assertGreater(score["score"], 99.999)
        self.assertLess(score["E_roll"], 1e-7)

    def test_zero_valid_but_scientifically_wrong(self):
        score = score_case(self.public, self.private, self.artifact(np.zeros((10, 2))))
        self.assertTrue(score["artifact_valid"])
        self.assertFalse(score["scientific_pass"])
        self.assertEqual(score["score"], 0)

    def test_controlled_perturbation_and_fixed_baseline_accepted(self):
        perturbed = self.coefficients*1.005
        score = score_case(self.public, self.private, self.artifact(perturbed))
        self.assertAlmostEqual(score["E_field"], .005, places=12)
        self.assertTrue(score["scientific_pass"])
        self.assertLess(score["score"], 100)
        estimated, _ = self.baseline.solve_case(self.public, "fixed")
        fitted = score_case(self.public, self.private, self.artifact(estimated))
        self.assertTrue(fitted["scientific_pass"])

    def test_coefficient_zeroing_strict_boundary_and_k(self):
        coefficients = np.zeros((10, 2))
        coefficients[0] = [np.nextafter(1e-6, 0), 1e-6]
        parsed = load_model(self.artifact(coefficients))
        self.assertEqual(np.count_nonzero(parsed), 1)
        score = score_case(self.public, self.private, self.artifact(np.ones((10, 2))*.01))
        self.assertTrue(score["artifact_valid"])
        self.assertEqual(score["K"], 20)
        self.assertEqual(score["score"], 0)

    def test_malformed_models_and_duplicate_keys(self):
        path = self.root / "model.json"
        for text in ('{"coefficients":[]}', '{"coefficients":[],"coefficients":[]}',
                     '{"coefficients":NaN}', '{"coefficients":Infinity}'):
            path.write_text(text)
            self.assertFalse(score_case(self.public, self.private, path)["artifact_valid"])
        coefficients = self.coefficients.tolist()
        coefficients[0][0] = True
        path.write_text(json.dumps({"coefficients": coefficients}))
        with self.assertRaises(ValueError):
            load_model(path)

    def test_large_finite_candidate_is_valid_failure(self):
        coefficients = np.zeros((10, 2))
        coefficients[6, 0] = 1e308
        score = score_case(self.public, self.private, self.artifact(coefficients))
        self.assertTrue(score["artifact_valid"])
        self.assertFalse(score["scientific_pass"])
        self.assertEqual(score["score"], 0)
        self.assertEqual(score["evaluation_status"], "valid")

    def test_blowup_is_legal_artifact_failed_integration(self):
        coefficients = np.zeros((10, 2))
        coefficients[6, 0] = 10
        score = score_case(self.public, self.private, self.artifact(coefficients))
        self.assertTrue(score["artifact_valid"])
        self.assertFalse(score["scientific_pass"])
        self.assertIsNone(score["E_roll"])
        self.assertEqual(score["score"], 0)

    def test_trajectory_may_leave_field_box(self):
        coefficients = np.zeros((10, 2))
        coefficients[0, 0] = 1
        result = bounded_rollout(coefficients, np.array([0., 0.]), np.linspace(0, 8, 401))
        self.assertEqual(result["status"], "success")
        self.assertAlmostEqual(result["values"][-1, 0], 8)

    def test_child_timeout_is_bounded(self):
        started = time.monotonic()
        result = bounded_rollout(self.coefficients, np.array([1., 0.]), np.linspace(0, 8, 401), timeout=1e-6)
        self.assertEqual(result["status"], "timeout")
        self.assertLess(time.monotonic()-started, 2)

    def test_gt_corruption_invalidates_evaluation(self):
        path = self.private / "hidden_clean.npy"
        original = path.read_bytes()
        try:
            changed = np.load(path, allow_pickle=False)
            changed[0, 1, 0] += .1
            np.save(path, changed, allow_pickle=False)
            with self.assertRaisesRegex(RuntimeError, "GT checksum mismatch"):
                score_case(self.public, self.private, self.artifact(self.coefficients))
        finally:
            path.write_bytes(original)

    def test_public_feedback_and_baseline_selection(self):
        path = self.artifact(self.coefficients)
        public = check_case(self.public, path)
        self.assertTrue(public["artifact_valid"])
        self.assertNotIn("E_field", public)
        self.assertNotIn("E_roll", public)
        self.assertEqual(len(public["validation_errors"]), 2)
        for method in ("raw", "fixed", "search"):
            coefficients, diagnostics = self.baseline.solve_case(self.public, method)
            self.assertEqual(coefficients.shape, (10, 2))
            self.assertTrue(np.isfinite(coefficients).all())
            self.assertEqual(diagnostics["method"], method)
            if method == "search" and not diagnostics["fallback"]:
                self.assertLessEqual(np.count_nonzero(coefficients), 10)


if __name__ == "__main__":
    unittest.main()
