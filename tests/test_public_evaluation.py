"""Public diagnostic deadlines and fixed comparisons; no real Docker/model runs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runner import public_evaluation as evaluation, worker
from runner.common import VERSION, file_hash, read_json, write_json


class PublicEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "candidate"
        self.source.mkdir()
        (self.source / "solve.py").write_text("synthetic source; never execute\n")
        self.calls = []
        self.checks = []

    def inputs(self, task="heat", split="pilot-smoke"):
        root = self.base / "inputs" / task / split
        count = 1 if split == "pilot-smoke" else 2 if split == "public-dev" else 4
        cases = []
        for level in range(3):
            for index in range(count):
                identifier = f"case-{level}-{index}"
                (root / "cases" / identifier).mkdir(parents=True)
                cases.append({"id": identifier, "path": "cases/" + identifier, "level": level})
        write_json(root / "manifest.json", {"task": task, "split": split, "contract_version": VERSION, "cases": cases})
        return root

    def execute(self, task, snapshot, inputs, run, image, timeout):
        self.calls.append((task, snapshot, inputs, run, image, timeout))
        (run / "artifacts").mkdir(parents=True)
        factor = len(self.calls)
        return {"artifact_valid": True, "attempt_status": "completed", "execution_wall_seconds": .5 * factor,
                "total_wall_seconds": factor, "cpu_seconds": .25 * factor, "memory_peak_bytes": 512 * factor,
                "processes_quiesced_at_seconds": .6 * factor, "timing_scope": "diagnostic synthetic W",
                "scientific_pass": False, "hidden_gt_sentinel": "must not be included"}

    def check(self, task, inputs, artifacts):
        self.checks.append((task, inputs, artifacts))
        return [{"id": row["id"], "artifact_valid": True, "residual_pass": True, "E_res": [1e-12] * 4}
                for row in read_json(inputs / "manifest.json")["cases"]]

    def run_evaluation(self, task="heat", inputs=None, timeout=100, **kwargs):
        return evaluation.run_public_evaluation(task, self.source, inputs or self.inputs(task), self.base / "run",
                                                "fixed-image", timeout, execute=self.execute, check=kwargs.pop("check", self.check), **kwargs)

    def test_only_public_feedback_and_diagnostics_are_returned(self):
        result = self.run_evaluation()
        self.assertTrue(result["artifact_valid"])
        self.assertEqual(result["public_check_status"], "completed")
        self.assertEqual(len(result["cases"]), 3)
        self.assertFalse(result["formal_timing"])
        self.assertEqual(result["worker_diagnostics"]["total_wall_seconds"], 1)
        self.assertNotIn("scientific_pass", json.dumps(result))
        self.assertNotIn("hidden_gt_sentinel", json.dumps(result))
        self.assertEqual(read_json(self.base / "run/public_feedback.json"), result)

    def test_poisson_comparator_is_fixed_second_worker_on_same_six_dev_cases(self):
        inputs = self.inputs("poisson", "public-dev")
        result = self.run_evaluation("poisson", inputs=inputs)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(row[2] == inputs for row in self.calls))
        source = self.base / "run/comparison-source/solve.py"
        self.assertEqual(source.read_bytes(), (ROOT / "public/poisson_compare.py").read_bytes())
        comparator = result["comparison"]
        self.assertEqual(comparator["source_sha256"], file_hash(source))
        self.assertEqual(len(comparator["cases"]), 6)
        self.assertEqual(comparator["worker_diagnostics"]["total_wall_seconds"], 2)
        self.assertEqual(comparator["diagnostic_wall_ratio"], 2)
        self.assertEqual(comparator["diagnostic_cpu_ratio"], 2)
        self.assertEqual(comparator["diagnostic_memory_ratio"], 2)
        self.assertFalse(comparator["formal_timing"])

    def test_checker_timeout_preserves_structural_validity(self):
        def slow(*args):
            raise TimeoutError("synthetic integration timeout")
        result = self.run_evaluation("ode", check=slow)
        self.assertTrue(result["artifact_valid"])
        self.assertEqual(result["attempt_status"], "completed")
        self.assertEqual(result["public_check_status"], "timeout")
        self.assertNotIn("cases", result)

    def test_checker_malformed_case_set_is_diagnostic_failure_only(self):
        result = self.run_evaluation(check=lambda *args: [{"id": "missing"}])
        self.assertTrue(result["artifact_valid"])
        self.assertEqual(result["public_check_status"], "failed")

    def test_invalid_artifact_skips_checker(self):
        def invalid(*args, **kwargs):
            result = self.execute(*args, **kwargs)
            result.update(artifact_valid=False, attempt_status="invalid_artifact")
            return result
        with patch.object(evaluation, "run_worker", side_effect=invalid):
            result = evaluation.run_public_evaluation("heat", self.source, self.inputs(), self.base / "run", "image", 100, check=self.check)
        self.assertFalse(result["artifact_valid"])
        self.assertEqual(self.checks, [])

    def test_worker_preparation_consumes_same_checker_and_comparison_budget(self):
        now = [0.0]
        original = self.execute
        def slow(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] += 9
            return result
        def checking(*args):
            result = self.check(*args)
            now[0] += 2
            return result
        inputs = self.inputs("poisson")
        with patch.object(evaluation.time, "monotonic", side_effect=lambda: now[0]):
            result = evaluation.run_public_evaluation("poisson", self.source, inputs, self.base / "run", "image", 10,
                                                      execute=slow, check=checking)
        self.assertEqual(self.calls[0][-1], 10)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(result["artifact_valid"])
        self.assertEqual(result["public_check_status"], "timeout")
        self.assertEqual(result["comparison"]["status"], "budget_timeout")
        self.assertTrue(result["research_budget_exhausted"])

    def test_failed_residual_does_not_get_a_diagnostic_speed_ratio(self):
        def wrong(*args):
            result = self.check(*args)
            result[0]["residual_pass"] = False
            return result
        result = self.run_evaluation("poisson", check=wrong)
        self.assertIsNone(result["comparison"]["diagnostic_wall_ratio"])

    def test_private_split_rejected_before_any_worker(self):
        with self.assertRaises(ValueError):
            self.run_evaluation(inputs=self.inputs("heat", "author-calibration"))
        self.assertEqual(self.calls, [])

    def test_checker_subprocess_is_fixed_isolated_and_group_killed_on_timeout(self):
        process = SimpleNamespace(pid=12345, returncode=-9)
        communicates = [subprocess.TimeoutExpired("trusted-checker", .1), (b"", b"")]
        def communicate(**kwargs):
            result = communicates.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        process.communicate = communicate
        process.poll = lambda: -9
        with patch.object(evaluation.subprocess, "Popen", return_value=process) as launch, \
                patch.object(evaluation.os, "killpg") as kill:
            with self.assertRaises(TimeoutError):
                evaluation._check("ode", self.base / "inputs", self.base / "artifacts", time.monotonic() + 10)
        command = launch.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, "-I", str(Path(evaluation.__file__).resolve())])
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        self.assertNotIn("shell", launch.call_args.kwargs)
        kill.assert_called_once_with(12345, evaluation.signal.SIGKILL)

    def test_actual_isolated_checker_reads_only_synthetic_public_inputs(self):
        inputs = self.inputs()
        for case in read_json(inputs / "manifest.json")["cases"]:
            folder = inputs / case["path"]
            write_json(folder / "metadata.json", {"kappa": 1, "sigma": 1})
            (folder / "observations.csv").write_text("x,t,y\n0.5,0.1,0\n")
        artifacts = self.base / "artifacts"
        artifacts.mkdir()
        rows = evaluation._check("heat", inputs, artifacts, time.monotonic() + 10)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["artifact_valid"] is False for row in rows))
        self.assertTrue(all(row["status"] == "invalid_artifact" for row in rows))


class WorkerDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "solve.py").write_text("pass\n")
        self.inputs = self.base / "inputs"
        self.inputs.mkdir()
        self.now = [0.0]
        self.calls = []
        self.info = {"Id": "fake", "Image": "image", "HostConfig": {"NetworkMode": "none", "NanoCpus": 10**9,
                      "Memory": 4 * 1024**3, "MemorySwap": 4 * 1024**3, "ReadonlyRootfs": True}, "Mounts": [],
                     "Config": {}, "State": {"OOMKilled": False, "Running": False}}
        self.cgroup = {"cpu.max": "100000 100000", "cpu.stat": "usage_usec 100", "memory.max": str(4 * 1024**3),
                       "memory.swap.max": "0", "memory.peak": "12345", "memory.events": "oom_kill 0", "pids.max": "128"}

    def control(self, *args, timeout=30, check=True):
        self.calls.append((args, timeout))
        if args[0] == "inspect":
            stdout = json.dumps([self.info])
        elif args[0] == "exec":
            stdout = json.dumps(self.cgroup)
        else:
            stdout = ""
        self.now[0] += 1
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    def test_preparation_reduces_execution_budget_and_default_task_caps_stay(self):
        for index, (task, timeout, expected) in enumerate((("heat", 10, 6), ("heat", 1000, 120), ("poisson", 1000, 60))):
            self.now[0] = 0
            with patch.object(worker.time, "monotonic", side_effect=lambda: self.now[0]), \
                    patch.object(worker, "docker", side_effect=self.control), \
                    patch.object(worker, "bounded_execution", return_value=("candidate_failed", 1, 0)) as execute:
                result = worker.run_worker(task, self.source, self.inputs, self.base / ("run-" + str(index)), "image", timeout=timeout)
            self.assertEqual(execute.call_args.args[2], expected)
            self.assertFalse(result["formal_timing"])
            self.assertFalse(result["budget_timeout"])

    def test_create_timeout_still_cleans_own_preselected_container(self):
        def timed_out(*args, timeout=30, check=True):
            self.calls.append((args, timeout))
            if args[0] == "create":
                self.now[0] += timeout
                raise subprocess.TimeoutExpired("docker create", timeout)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(worker.time, "monotonic", side_effect=lambda: self.now[0]), \
                patch.object(worker, "docker", side_effect=timed_out), \
                patch.object(worker, "bounded_execution", side_effect=AssertionError("must not execute")):
            result = worker.run_worker("heat", self.source, self.inputs, self.base / "run", "image", timeout=2)
        self.assertTrue(result["budget_timeout"])
        self.assertEqual(result["attempt_status"], "budget_timeout")
        self.assertEqual(self.calls[0][1], 2)
        name = self.calls[0][0][self.calls[0][0].index("--name") + 1]
        self.assertEqual(self.calls[-1], (("rm", "-f", name), 5))
        self.assertEqual(result["cleanup_status"], "completed")

    def test_deadline_before_execution_skips_solver_and_persists_budget_status(self):
        with patch.object(worker.time, "monotonic", side_effect=lambda: self.now[0]), \
                patch.object(worker, "docker", side_effect=self.control), \
                patch.object(worker, "bounded_execution", side_effect=AssertionError("must not execute")):
            result = worker.run_worker("heat", self.source, self.inputs, self.base / "run", "image", timeout=3)
        self.assertTrue(result["budget_timeout"])
        self.assertEqual(result["attempt_status"], "budget_timeout")
        self.assertEqual(read_json(self.base / "run/worker.json"), result)

    def test_known_candidate_failure_survives_research_deadline_exhaustion(self):
        for index, status in enumerate(("timeout", "log_limit", "candidate_failed")):
            self.now[0] = 0
            def expired(*args):
                self.now[0] = 11
                return status, 1, 0
            with patch.object(worker.time, "monotonic", side_effect=lambda: self.now[0]), \
                    patch.object(worker, "docker", side_effect=self.control), \
                    patch.object(worker, "bounded_execution", side_effect=expired):
                result = worker.run_worker("heat", self.source, self.inputs, self.base / ("expired-" + str(index)), "image", timeout=10)
            self.assertEqual(result["attempt_status"], status)
            self.assertTrue(result["budget_timeout"])
            self.assertEqual(result["budget_timeout_stage"], "post_execution")

    def test_solver_pipe_deadline_kills_local_client_with_bounded_cleanup(self):
        run = self.base / "solver-pipe"
        run.mkdir()
        began = time.monotonic()
        with patch.object(worker, "docker", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            status, code, total = worker.bounded_execution([sys.executable, "-I", "-c", "import time; time.sleep(10)"], run, .05, "fake-container")
        self.assertEqual(status, "timeout")
        self.assertNotEqual(code, 0)
        self.assertLess(time.monotonic() - began, 2)

    def test_artifact_pipe_deadline_kills_copy_client_and_records_budget_timeout(self):
        self.info["State"].update(Running=True, Pid=111)
        processes = []
        original_popen = subprocess.Popen
        def trusted_sleep_pipe(*args, **kwargs):
            process = original_popen([sys.executable, "-I", "-c", "import time; time.sleep(10)"], **kwargs)
            processes.append(process)
            return process
        def control(*args, **kwargs):
            if args[0] == "inspect":
                output = json.dumps([self.info])
            elif args[0] == "top":
                output = "PID STAT COMMAND\n111 S sleep\n"
            elif args[0] == "exec" and "read_text" in args[-1]:
                output = json.dumps(self.cgroup)
            else:
                output = ""
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        began = time.monotonic()
        with patch.object(worker, "docker", side_effect=control), \
                patch.object(worker, "bounded_execution", return_value=("completed", 0, 0)), \
                patch.object(worker.subprocess, "Popen", side_effect=trusted_sleep_pipe):
            result = worker.run_worker("heat", self.source, self.inputs, self.base / "run", "image", timeout=.1)
        self.assertLess(time.monotonic() - began, 2)
        self.assertTrue(result["budget_timeout"])
        self.assertEqual(result["attempt_status"], "completed")
        self.assertEqual(result["budget_timeout_stage"], "artifact_transfer")
        self.assertFalse(result["artifact_valid"])
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)


if __name__ == "__main__":
    unittest.main()
