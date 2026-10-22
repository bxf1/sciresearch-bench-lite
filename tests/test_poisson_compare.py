"""Public comparator tests use a small analytic SPD problem, no private data."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.sparse import diags, save_npz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public import poisson_compare


class PoissonCompareTests(unittest.TestCase):
    def setUp(self):
        self.matrix = diags([-np.ones(7), np.full(8, 4.0), -np.ones(7)], [-1, 0, 1], format="csr")
        self.answer = np.arange(32, dtype=float).reshape(8, 4) / 32
        self.rhs = self.matrix @ self.answer

    def test_four_rhs_solution_and_fixed_settings_match_author_jacobi(self):
        path = ROOT / "baselines/poisson/solve.py"
        spec = importlib.util.spec_from_file_location("test_only_author_baseline", path)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        solution = poisson_compare.solve(self.matrix, self.rhs)
        np.testing.assert_allclose(solution, self.answer, rtol=1e-10, atol=1e-12)
        np.testing.assert_array_equal(solution, baseline.solve(self.matrix, self.rhs, "jacobi"))
        self.assertEqual(solution.dtype.str, "<f8")
        self.assertEqual(poisson_compare.CG_SETTINGS, {"rtol": 1e-10, "atol": 0.0, "maxiter": 10000})

    def test_convergence_failure_is_not_reported_as_success(self):
        with patch.object(poisson_compare, "cg", return_value=(np.zeros(8), 10000)):
            with self.assertRaisesRegex(RuntimeError, "did not converge"):
                poisson_compare.solve(self.matrix, self.rhs)

    def test_bad_shape_diagonal_and_nonfinite_inputs_rejected(self):
        bad_diagonal = diags(np.full(8, -1.0), format="csr")
        for matrix, rhs in ((self.matrix, self.rhs[:, :3]), (bad_diagonal, self.rhs),
                            (self.matrix, np.full((8, 4), np.nan)), (self.matrix, self.rhs.astype(complex))):
            with self.subTest(shape=rhs.shape), self.assertRaises(ValueError):
                poisson_compare.solve(matrix, rhs)

    def test_standalone_cli_outputs_only_solutions_and_public_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input/cases/analytic"
            source.mkdir(parents=True)
            save_npz(source / "A.npz", self.matrix)
            np.save(source / "rhs.npy", self.rhs, allow_pickle=False)
            (root / "input/manifest.json").write_text(json.dumps({"task": "poisson", "cases": [{"id": "analytic", "path": "cases/analytic", "level": 0}]}))
            script = root / "poisson_compare.py"
            script.write_bytes((ROOT / "public/poisson_compare.py").read_bytes())
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            environment.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1")
            result = subprocess.run([sys.executable, str(script), "--input", str(root / "input"), "--output", str(root / "output"), "--seed", "0"],
                                    cwd=root, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            diagnostics = json.loads(result.stdout)
            self.assertFalse(diagnostics["formal"])
            self.assertEqual(diagnostics["timing_status"], "diagnostic_in_process_only")
            self.assertTrue(diagnostics["cases"][0]["residual_pass"])
            self.assertNotIn("E_sol", diagnostics["cases"][0])
            self.assertNotIn("reward", diagnostics)
            self.assertNotIn("score", diagnostics)
            self.assertEqual([p.relative_to(root / "output").as_posix() for p in (root / "output").rglob("*") if p.is_file()],
                             ["cases/analytic/solution.npy"])
            np.testing.assert_allclose(np.load(root / "output/cases/analytic/solution.npy", allow_pickle=False), self.answer, atol=1e-12)
            manifest = json.loads((root / "input/manifest.json").read_text())
            manifest["cases"][0]["path"] = "../outside"
            (root / "input/manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "unsafe case path"):
                poisson_compare.solve_batch(root / "input", root / "output-unsafe")
            self.assertFalse((root / "output-unsafe").exists())


if __name__ == "__main__":
    unittest.main()
