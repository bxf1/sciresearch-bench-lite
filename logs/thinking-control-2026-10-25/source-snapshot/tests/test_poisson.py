from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.sparse import load_npz

from authoring.poisson import (assemble, coefficient_field, generate_case,
                              independent_dense_stencil, independent_flux, roundoff_bound)
from judge.poisson import TruthError, score_case
from public.poisson import check_case


class PoissonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.public = cls.root / "public"
        cls.private = cls.root / "private"
        cls.public.mkdir()
        cls.private.mkdir()
        cls.record = generate_case(cls.public, cls.private, 0, cls.rngs(3210))
        with np.load(cls.private / "truth.npz", allow_pickle=False) as data:
            cls.truth = data["solution"].copy()
        baseline_path = Path(__file__).resolve().parents[1] / "baselines" / "poisson" / "solve.py"
        spec = importlib.util.spec_from_file_location("poisson_baseline_test", baseline_path)
        cls.baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.baseline)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def rngs(seed):
        return {name: np.random.Generator(np.random.PCG64(child)) for name, child in
                zip(("system", "mask", "noise", "solution"), np.random.SeedSequence(seed).spawn(4))}

    def output(self, value):
        path = self.root / "solution.npy"
        np.save(path, value, allow_pickle=False)
        return path

    def test_gt_and_all_three_algorithms(self):
        matrix = load_npz(self.public / "A.npz")
        rhs = np.load(self.public / "rhs.npy", allow_pickle=False)
        for name, value in [("gt", self.truth)] + [(name, self.baseline.solve(matrix, rhs, name))
                                                   for name in ("cg", "jacobi", "lu")]:
            with self.subTest(method=name):
                result = score_case(self.public, self.private, self.output(value))
                self.assertTrue(result["scientific_pass"])
                self.assertTrue(result["artifact_valid"])
                self.assertIsNone(result["score"])
                self.assertTrue(check_case(self.public, self.root / "solution.npy")["residual_pass"])

    def test_zero_and_controlled_perturbations(self):
        for factor, passes in ((0.0, False), (1 + 1e-9, True), (1 + 1e-7, False)):
            with self.subTest(factor=factor):
                result = score_case(self.public, self.private, self.output(self.truth * factor))
                self.assertTrue(result["artifact_valid"])
                self.assertEqual(result["scientific_pass"], passes)
                self.assertAlmostEqual(result["E_sol"][0], abs(1 - factor), delta=1e-12)

    def test_bad_shape_dtype_and_nan(self):
        for value in (self.truth[:, 0], self.truth.astype("<f4"), self.truth.astype(">f8"),
                      np.full_like(self.truth, np.nan), self.truth.astype(complex)):
            with self.subTest(shape=value.shape, dtype=str(value.dtype)):
                result = score_case(self.public, self.private, self.output(value))
                self.assertFalse(result["artifact_valid"])
                self.assertEqual(result["score"], 0)

    def test_large_finite_candidate_is_scientific_failure(self):
        path = self.output(np.full_like(self.truth, 1e308))
        result = score_case(self.public, self.private, path)
        self.assertTrue(result["artifact_valid"])
        self.assertFalse(result["scientific_pass"])
        self.assertEqual(result["evaluation_status"], "valid")
        self.assertIn("candidate_numerical_failure", result["reason"])

    def test_trusted_corruption_is_not_candidate_failure(self):
        private = self.root / "corrupt"
        private.mkdir(exist_ok=True)
        (private / "qc.json").write_bytes((self.private / "qc.json").read_bytes())
        np.savez(private / "truth.npz", solution=np.zeros_like(self.truth),
                 independent_rhs=np.load(self.public / "rhs.npy", allow_pickle=False))
        with self.assertRaises(TruthError):
            score_case(self.public, private, self.output(self.truth))

    def test_same_easy_operator_and_independent_rhs(self):
        public, private = self.root / "other-public", self.root / "other-private"
        public.mkdir(exist_ok=True)
        private.mkdir(exist_ok=True)
        other = generate_case(public, private, 0, self.rngs(3211))
        self.assertEqual(other["operator_fingerprint"], self.record["operator_fingerprint"])
        self.assertNotEqual(other["latent_fingerprint"], self.record["latent_fingerprint"])
        self.assertNotEqual(other["system_fingerprint"], self.record["system_fingerprint"])

    def test_overlap_is_union_and_boundary_rule(self):
        disks = np.array([[.5, .5, .18]] * 3)
        coefficient = coefficient_field(8, 300, disks)
        self.assertEqual(set(np.unique(coefficient)), {1.0, 300.0})
        matrix, interior, boundary = assemble(coefficient)
        dense = independent_dense_stencil(coefficient)
        np.testing.assert_allclose(matrix.toarray(), dense, rtol=1e-14, atol=1e-12)
        self.assertTrue(np.all(interior > 0) and np.all(boundary > 0))
        self.assertGreater(np.linalg.eigvalsh(dense).min(), 0)
        values = self.rngs(5000)["solution"].standard_normal((64, 4))
        np.testing.assert_allclose(matrix @ values, independent_flux(coefficient, values), rtol=1e-12, atol=1e-9)
        self.assertLess(roundoff_bound(matrix, coefficient)["relative_solution_error_upper_bound"], 1e-7)

    def test_all_levels_qc_and_private_separation(self):
        for level in (1, 2):
            public, private = self.root / f"l{level}-public", self.root / f"l{level}-private"
            public.mkdir(exist_ok=True)
            private.mkdir(exist_ok=True)
            result = generate_case(public, private, level, self.rngs(4000 + level))
            self.assertTrue(result["qc"]["passed"])
            self.assertLess(result["qc"]["roundoff"]["relative_solution_error_upper_bound"], 1e-7)
            self.assertEqual({p.name for p in public.iterdir()}, {"A.npz", "rhs.npy", "metadata.json"})
            self.assertNotIn("disks", json.loads((public / "metadata.json").read_text()))


if __name__ == "__main__":
    unittest.main()
