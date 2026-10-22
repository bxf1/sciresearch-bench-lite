"""Reporting guards use synthetic host records, never hidden data or a model."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runner.common import file_hash, read_json, write_json
from runner.report import delivery_evidence, export_report, native_pilot_evidence, relay_probe_evidence, write_results_document


def pilot(root, name="harbor-native-pilot-001", **changes):
    directory = root / "logs" / name
    result = {"formal": False, "replay_split": "pilot-smoke", "status": "pilot_completed",
              "attempt_status": "completed", "evaluation_status": "valid", "task": "heat",
              "model_run_started": True, "score": 88.0, "reward": 1, "cost_usd": 0,
              "registry": {"closed": True, "first_id": "candidate-001", "final_id": "candidate-001",
                           "selection_reason": "explicit_finalize",
                           "evaluations": [{"id": "candidate-001", "source_hash": "a" * 64}]},
              "relay_status": {"request_count": 2, "successful_requests": 1, "failed_requests": 1,
                               "charged_output_tokens": 4106, "token": "must-not-be-exported"},
              "relay_cleanup": {"all_removed": True}, "worker_cleanup": {"all_removed": True},
              "cleanup_errors": {}, "bridge_errors": []}
    result.update(changes)
    write_json(directory / "result.json", result)
    return directory


def diagnostics(directory, *, split="pilot-smoke", formal=False, identifier="candidate-001"):
    first = {"checkpoint_id": identifier, "source_hash": "a" * 64, "replay_count": 3,
             "score": 88.0, "reward": 1,
             "repeats": [{"phase": {"split": split, "formal": formal}} for _ in range(3)]}
    final = {**first, "replay_count": 0, "reused_from": "candidate-001"}
    write_json(directory / "harbor/trial/verifier/research-replay.json", {"first": first, "final": final})


def events(directory, rows):
    path = directory / "relay-evidence/evidence/events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


class NativePilotReportTests(unittest.TestCase):
    def test_success_and_failed_attempts_preserve_reuse_usage_nulls_and_originals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = pilot(root)
            diagnostics(good)
            bad = pilot(root, "harbor-native-pilot-002", status="pilot_invalid", attempt_status="api_failed")
            first, second = "b" * 32, "c" * 32
            event_path = events(good, [
                {"event": "request_accepted", "request_id": first, "requested_max_tokens": 16384,
                 "effective_max_tokens": 4096, "system_sha256": "d" * 64, "tools_sha256": "e" * 64},
                {"event": "request_finished", "request_id": first, "outcome": "success", "upstream_status": 200,
                 "output_usage_complete": True, "input_tokens": 100, "output_tokens": 10,
                 "cache_read_input_tokens": 80, "cache_creation_input_tokens": 0, "charged_output_tokens": 10},
                {"event": "request_accepted", "request_id": second, "effective_max_tokens": 4096},
                {"event": "request_finished", "request_id": second, "outcome": "upstream_http_error",
                 "upstream_status": 429, "output_usage_complete": False, "charged_output_tokens": 4096}])
            hook = good / "host-events.jsonl"
            hook.write_text(json.dumps({"kind": "verification_start", "time": 1, "event_hash": "f" * 64}) + "\n")
            originals = {path: file_hash(path) for path in root.rglob("*") if path.is_file()}
            result = native_pilot_evidence(root)
            one, two = result["attempts"]
            self.assertEqual(result["request_rows"], 2)
            self.assertEqual(one["first_replay_count"], 3)
            self.assertEqual(one["final_replay_count"], 0)
            self.assertEqual(one["final_reused_from"], "candidate-001")
            self.assertEqual(one["successful_input_tokens"], 100)
            self.assertEqual(one["successful_output_tokens"], 10)
            self.assertEqual(one["relay_status"]["charged_output_tokens"], 4106)
            self.assertEqual(one["relay_events_sha256"], file_hash(event_path))
            self.assertEqual(one["native_hooks"][0]["kind"], "verification_start")
            self.assertNotIn("must-not-be-exported", json.dumps(result))
            self.assertIsNone(one["cost_usd"])
            self.assertIsNone(two["score"])
            self.assertIsNone(two["reward"])
            self.assertIsNone(two["successful_input_tokens"])
            self.assertEqual(result["formal_research_sessions_completed"], 0)
            with (root / "results/runs/harbor-native-pilot-requests.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[1]["output_tokens"], "null")
            self.assertEqual(rows[1]["upstream_status"], "429")
            self.assertEqual({path: file_hash(path) for path in originals}, originals)
            self.assertFalse((root / "docs").exists())

    def test_early_failure_is_retained_without_fabricated_candidate_or_usage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "logs/harbor-native-pilot-000"
            write_json(directory / "result.json", {"formal": False, "replay_split": "pilot-smoke",
                       "status": "pilot_invalid", "error": "setup failed", "model_run_started": False})
            row = native_pilot_evidence(root)["attempts"][0]
            self.assertEqual(row["error"], "setup failed")
            self.assertEqual(row["registered_evaluations"], 0)
            self.assertIsNone(row["first_id"])
            self.assertIsNone(row["relay_status"])
            self.assertIsNone(row["score"])

    def test_nonpilot_or_unmarked_result_rejected_before_nested_evidence(self):
        for changes in ({"formal": True}, {"formal": None}, {"replay_split": "final-test"}, {"replay_split": None}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = pilot(root, **changes)
                nested = directory / "harbor/trial/verifier/research-replay.json"
                nested.parent.mkdir(parents=True)
                nested.write_text("invalid JSON must never be read")
                with self.assertRaisesRegex(ValueError, "requires formal=false"):
                    native_pilot_evidence(root)
                self.assertFalse((root / "results").exists())

    def test_nested_replay_phase_and_checkpoint_identity_are_guarded(self):
        for changes in ({"split": "final-test"}, {"formal": True}, {"identifier": "candidate-999"}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = pilot(root)
                diagnostics(directory, **changes)
                with self.assertRaisesRegex(ValueError, "non-pilot|checkpoint differs"):
                    native_pilot_evidence(root)
                self.assertFalse((root / "results").exists())

    def test_linked_host_evidence_and_duplicate_request_events_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = pilot(root)
            external = root / "must-not-read.json"
            external.write_text("not public evidence")
            (directory / "host-events.jsonl").symlink_to(external)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                native_pilot_evidence(root)
            (directory / "host-events.jsonl").unlink()
            record = {"event": "request_accepted", "request_id": "b" * 32}
            events(directory, [record, record])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                native_pilot_evidence(root)

    def test_export_stage_adds_evidence_without_increasing_formal_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pilot(root)
            calibration = root / "logs/calibration/summary.json"
            write_json(calibration, {"status": "local_calibration_not_formal_freeze",
                                     "final_test_scores_accessed": False, "methods": []})
            (root / "runner").mkdir()
            (root / "runner/worker.py").write_text("# fixture")
            with patch("runner.report.generation_evidence", return_value={}), patch("runner.report.write_results_document"):
                result = export_report(root, calibration, root / "fixture-data")
            stage = read_json(root / "results/stage-status.json")
            self.assertEqual(result["native_pilot_attempts"], 1)
            self.assertEqual(len(stage["harbor_native_pilots"]["attempts"]), 1)
            self.assertEqual(stage["formal_guidance_cells_completed"], 0)
            self.assertEqual(stage["formal_research_sessions_completed"], 0)
            self.assertIs(stage["final_test_scored"], False)


class RelayProbeReportTests(unittest.TestCase):
    def test_probe_failure_retained_without_scores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for number, state in enumerate(("passed", "failed"), 1):
                write_json(root / f"logs/relay-transport-probe-{number:03d}/result.json",
                           {"formal": False, "model_calls": 0, "status": state, "score": 99,
                            "network": {"passed": state == "passed"}, "relay_cleanup": {"all_removed": True}})
            rows = relay_probe_evidence(root)
            self.assertEqual([row["status"] for row in rows], ["passed", "failed"])
            self.assertTrue(all(row["score"] is None and row["cost_usd"] is None for row in rows))

    def test_probe_requires_explicit_nonformal_zero_model_calls(self):
        for formal, calls in ((True, 0), (False, 1), (False, None), (False, False)):
            with self.subTest(formal=formal, calls=calls), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_json(root / "logs/relay-transport-probe-001/result.json", {"formal": formal, "model_calls": calls})
                with self.assertRaisesRegex(ValueError, "zero model calls"):
                    relay_probe_evidence(root)


class ResultsDocumentTests(unittest.TestCase):
    def test_native_completion_and_dependency_install_keep_separate_acceptance_statuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "logs/dependency-rebuild-local-001/result.json"
            write_json(path, {"formal": False, "status": "fresh_dependency_environment_installed",
                             "reuse_old_site_packages": False, "new_environment_replay_status": "pending"})
            delivery = delivery_evidence(root)
            self.assertEqual(delivery["dependency_environment"]["new_environment_replay_status"], "pending")
            stage = {"generated_at": "fixture", "calibration_source": "fixture.json", "calibration_case_rows": 0,
                     "calibration_methods": 0, "generation": {"case_count": 90, "qc_passed": 90},
                     "pilot_model_wj": None, "localhost_bridge": None, "runtime_probes": [],
                     "engineering_probes": {"research_network": [], "file_bridge": []},
                     "research_pilots": [], "research_pilot_replays": [], "clean_replay": {"attempts": []},
                     "delivery": delivery, "harbor_native_pilots": {"attempts": [{"status": "pilot_completed",
                         "selection_reason": "explicit_finalize", "run_id": "harbor-native-pilot-001",
                         "evidence": "logs/harbor-native-pilot-001/result.json"}]}}
            (root / "docs").mkdir()
            write_results_document(root, [], stage)
            rendered = (root / "docs/results.md").read_text()
            self.assertIn("显式finalize和完整Harbor SingleStepTrial生命周期已", rendered)
            self.assertIn("logs/harbor-native-pilot-001/result.json", rendered)
            self.assertIn("新环境重放状态为 `pending`", rendered)
            self.assertIn("安装完成不等于重放已完成", rendered)
            self.assertNotIn("独立主机", rendered)
            self.assertNotIn("第二台", rendered)
            changed = read_json(path)
            changed["formal"] = True
            write_json(path, changed)
            with self.assertRaisesRegex(ValueError, "nonformal evidence"):
                delivery_evidence(root)


if __name__ == "__main__":
    unittest.main()
