"""Synthetic aggregation tests only: no measured performance claims."""
from __future__ import annotations

import copy
import unittest

from runner.performance import (ACCURACY_PROFILE, EFFICIENCY_PROFILE, FORMAL_TIMING_SCOPE,
                                ORDER, calibrate_profile, summarize_attempts, summarize_group)


def fixture(b=(2.0, 2.0, 2.0), c=(1.0, 1.0, 1.0), attempt_id="synthetic-1"):
    times = {"B": iter(b), "C": iter(c)}
    start = 1_000_000_000
    rows = []
    for index, role in enumerate(ORDER):
        seconds = next(times[role])
        end = start + round(seconds * 1e9)
        rows.append({"role": role, "source_hash": "test-" + role, "scientific_pass": True,
                     "artifact_valid": True, "evaluation_status": "valid", "attempt_status": "completed",
                     "worker": {"formal_timing": True, "resource_qualified": True,
                                "all_processes_terminated": True, "output_initially_empty": True,
                                "timing_scope": FORMAL_TIMING_SCOPE, "execution_wall_seconds": seconds,
                                "started_monotonic_ns": start, "finished_monotonic_ns": end,
                                "input_sha256": "test-input", "resource_contract_sha256": "test-resources",
                                "container_id": f"{attempt_id}-{index}", "machine_id": "test-machine"}})
        start = end + 1_000_000
    return {"attempt_id": attempt_id, "baseline_method": "jacobi", "candidate_method": "lu",
            "samples": rows, "evidence": {"machine_exclusive_verified": True,
                "exclusive_lock_id": "synthetic-test-lock", "other_workloads": [],
                "machine_id": "test-machine", "cache_state": "synthetic fixture; no real timer ran"}}


class PerformanceTests(unittest.TestCase):
    def summary(self, attempt, profile=EFFICIENCY_PROFILE):
        return summarize_group(attempt["samples"], evidence=attempt["evidence"], profile=profile)

    def test_three_groups_required_and_efficiency_choice(self):
        result = calibrate_profile([[fixture(attempt_id=f"group-{i}")] for i in range(3)])
        self.assertEqual(result["profile"], EFFICIENCY_PROFILE)
        self.assertTrue(result["formal_profile_ready"])
        with self.assertRaises(ValueError):
            calibrate_profile([[fixture()]])

    def test_one_group_below_1_8_selects_accuracy(self):
        groups = [[fixture()], [fixture(b=(1.79, 1.79, 1.79))], [fixture()]]
        result = calibrate_profile(groups)
        self.assertEqual(result["profile"], ACCURACY_PROFILE)

    def test_reward_and_continuous_score_boundaries(self):
        for speedup, reward in ((.5, 0), (1.499, 0), (1.5, 1), (8, 1), (20, 1)):
            with self.subTest(speedup=speedup):
                result = self.summary(fixture(b=(speedup,) * 3))
                self.assertEqual(result["reward"], reward)
                self.assertEqual(result["speedup"], speedup)
                self.assertGreaterEqual(result["score"], 0)
                self.assertLessEqual(result["score"], 100)
        self.assertEqual(self.summary(fixture(b=(.5,) * 3), ACCURACY_PROFILE)["reward"], 1)

    def test_order_is_not_replaceable_by_grouped_times(self):
        attempt = fixture()
        attempt["samples"][1], attempt["samples"][3] = attempt["samples"][3], attempt["samples"][1]
        self.assertEqual(self.summary(attempt)["evaluation_status"], "evaluation_invalid")

    def test_baseline_instability_one_retry_preserves_original(self):
        first = fixture(b=(2, 2, 2.5))
        initial = summarize_attempts([first], profile=EFFICIENCY_PROFILE)
        self.assertTrue(initial["retry_permitted"])
        self.assertIsNone(initial["speedup"])
        retry = fixture(attempt_id="synthetic-2")
        retry.update(parent_attempt=first["attempt_id"], interference_resolution="synthetic interference removed")
        result = summarize_attempts([first, retry], profile=EFFICIENCY_PROFILE)
        self.assertEqual(result["reward"], 1)
        self.assertEqual(len(result["attempts"]), 2)
        self.assertFalse(result["retry_permitted"])
        self.assertEqual(result["selected_attempt"], 1)

    def test_second_unstable_group_null_performance_accuracy_kept(self):
        first = fixture(b=(2, 2, 2.5))
        second = fixture(b=(2, 2, 2.6), attempt_id="synthetic-2")
        second.update(parent_attempt=first["attempt_id"], interference_resolution="synthetic investigation")
        for profile, reward in ((EFFICIENCY_PROFILE, None), (ACCURACY_PROFILE, 1)):
            result = summarize_attempts([first, second], profile=profile)
            self.assertIsNone(result["score"])
            self.assertIsNone(result["speedup"])
            self.assertEqual(result["reward"], reward)
            self.assertEqual(result["performance_status"], "baseline_unstable_after_retry")
        with self.assertRaises(ValueError):
            summarize_attempts([first, second, copy.deepcopy(second)])

    def test_unrequested_rerun_rejected(self):
        first, second = fixture(), fixture(attempt_id="synthetic-2")
        second.update(parent_attempt=first["attempt_id"], interference_resolution="arbitrary rerun")
        with self.assertRaises(ValueError):
            summarize_attempts([first, second])

    def test_candidate_failure_zero_and_invalid_baseline_not_denominator(self):
        for key, value in (("scientific_pass", False), ("attempt_status", "timeout")):
            attempt = fixture()
            attempt["samples"][1][key] = value
            result = self.summary(attempt)
            self.assertEqual(result["reward"], 0)
            self.assertEqual(result["score"], 0)
            self.assertIsNone(result["speedup"])
        attempt = fixture()
        attempt["samples"][0]["scientific_pass"] = False
        result = self.summary(attempt)
        self.assertEqual(result["performance_status"], "invalid_baseline")
        self.assertIsNone(result["speedup"])
        self.assertIsNone(result["reward"])

    def test_diagnostic_timing_cannot_freeze_any_profile(self):
        attempt = fixture()
        attempt["samples"][1]["worker"]["formal_timing"] = False
        result = self.summary(attempt, ACCURACY_PROFILE)
        self.assertEqual(result["performance_status"], "diagnostic_only")
        self.assertIsNone(result["reward"])
        self.assertIsNone(result["score"])
        calibration = calibrate_profile([[fixture()], [attempt], [fixture()]])
        self.assertIsNone(calibration["profile"])
        self.assertFalse(calibration["formal_profile_ready"])
        attempt["samples"][1]["scientific_pass"] = False
        self.assertEqual(self.summary(attempt)["reward"], 0)
        self.assertIsNone(calibrate_profile([[fixture()], [attempt], [fixture()]])["profile"])

    def test_formally_measured_lu_scientific_failure_selects_accuracy(self):
        attempt = fixture()
        attempt["samples"][1]["scientific_pass"] = False
        result = calibrate_profile([[fixture()], [attempt], [fixture()]])
        self.assertEqual(result["profile"], ACCURACY_PROFILE)
        self.assertFalse(result["reference_correct_all_groups"])

    def test_shared_machine_changed_contract_and_overlapping_runs_refused(self):
        modifications = [
            lambda a: a["evidence"].update(machine_exclusive_verified=False),
            lambda a: a["evidence"].update(other_workloads=["unrelated-service"]),
            lambda a: a["samples"][1]["worker"].update(machine_id="other-machine"),
            lambda a: a["samples"][1]["worker"].update(input_sha256="different-input"),
            lambda a: a["samples"][1]["worker"].update(resource_contract_sha256="different-limit"),
            lambda a: a["samples"][1]["worker"].update(container_id=a["samples"][0]["worker"]["container_id"]),
            lambda a: a["samples"][1]["worker"].update(started_monotonic_ns=1),
            lambda a: a["samples"][1]["worker"].update(execution_wall_seconds=float("nan")),
        ]
        for modify in modifications:
            attempt = fixture()
            modify(attempt)
            result = self.summary(attempt)
            self.assertEqual(result["performance_status"], "diagnostic_only")
            self.assertIsNone(result["speedup"])

    def test_trusted_judge_failure_is_null_not_candidate_zero(self):
        attempt = fixture()
        attempt["samples"][1].update(evaluation_status="evaluation_invalid", scientific_pass=False)
        result = self.summary(attempt)
        self.assertEqual(result["evaluation_status"], "evaluation_invalid")
        self.assertIsNone(result["reward"])

    def test_candidate_variability_reported_without_inventing_a_threshold(self):
        result = self.summary(fixture(c=(.1, 1, 1.5)))
        self.assertEqual(result["candidate_time_ratio"], 15)
        self.assertEqual(result["speedup"], 2)
        self.assertEqual(result["reward"], 1)


if __name__ == "__main__":
    unittest.main()
