"""Host registry boundary tests use only self-created temporary sentinels."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runner.registry import Registry
from runner.artifact_gate import ArtifactError, MAX_SOURCE
from runner.common import read_json


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.source = self.workspace / "candidate"
        self.source.mkdir()
        (self.source / "solve.py").write_text("pass\n")
        self.outside = self.base / "outside"
        self.outside.mkdir()
        (self.outside / "probe.py").write_text("PRIVATE_SENTINEL\n")
        self.registry = Registry.create(self.base / "registry", self.workspace, "heat", "g3")

    @staticmethod
    def valid(*args):
        return {"artifact_valid": True, "score": 0}

    def test_valid_first_fallback_and_hash(self):
        first = self.registry.evaluate("candidate", self.valid)
        self.assertTrue(first["artifact_valid"])
        (self.source / "solve.py").write_text("print('changed')\n")
        second = self.registry.evaluate("candidate", self.valid)
        state = self.registry.close()
        self.assertEqual(state["first_id"], first["id"])
        self.assertEqual(state["final_id"], second["id"])
        self.assertEqual(state["selection_reason"], "deadline_fallback")
        self.assertNotEqual(first["source_hash"], second["source_hash"])
        self.assertEqual((self.registry.verified_snapshot(first["id"]) / "solve.py").read_text(), "pass\n")
        events = [json.loads(line) for line in (self.registry.root / "events.jsonl").read_text().splitlines()]
        for previous, current in zip(events, events[1:]):
            self.assertEqual(previous["event_hash"], current["previous_hash"])

    def test_static_ancestor_symlink_rejected(self):
        (self.workspace / "alias").symlink_to(self.outside, target_is_directory=True)
        result = self.registry.evaluate("alias", self.valid)
        self.assertFalse(result["artifact_valid"])
        self.assertIsNone(result["source_hash"])

    def test_parent_replacement_before_directory_open(self):
        nested = self.source / "nested"
        nested.mkdir()
        (nested / "probe.py").write_text("safe\n")
        original_open = os.open
        swapped = False
        def raced_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == "nested" and not swapped:
                swapped = True
                nested.rename(self.source / "original_nested")
                nested.symlink_to(self.outside, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)
        with patch("runner.artifact_gate.os.open", side_effect=raced_open):
            result = self.registry.evaluate("candidate", self.valid)
        self.assertTrue(swapped)
        self.assertFalse(result["artifact_valid"])

    def test_parent_replacement_after_directory_open_cannot_escape(self):
        nested = self.source / "nested"
        nested.mkdir()
        (nested / "probe.py").write_text("safe\n")
        original_open = os.open
        swapped = False
        def raced_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == "probe.py" and not swapped:
                swapped = True
                nested.rename(self.source / "original_nested")
                nested.symlink_to(self.outside, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)
        def inspect(snapshot, *args):
            return {"artifact_valid": True, "copied": (snapshot / "nested/probe.py").read_text()}
        with patch("runner.artifact_gate.os.open", side_effect=raced_open):
            result = self.registry.evaluate("candidate", inspect)
        self.assertTrue(swapped)
        # A concurrent directory mutation may be rejected; if accepted it must be safe.
        if result["artifact_valid"]:
            self.assertEqual(result["result"]["copied"], "safe\n")
        snapshot = self.registry.root / "snapshots" / result["id"]
        for path in snapshot.rglob("*"):
            if path.is_file():
                self.assertNotIn("PRIVATE_SENTINEL", path.read_text())

    def test_fifo_replacement_does_not_block(self):
        original_open = os.open
        changed = False
        def raced_open(path, flags, *args, **kwargs):
            nonlocal changed
            if path == "solve.py" and not changed:
                changed = True
                (self.source / "solve.py").unlink()
                os.mkfifo(self.source / "solve.py")
                self.assertTrue(flags & os.O_NONBLOCK)
            return original_open(path, flags, *args, **kwargs)
        with patch("runner.artifact_gate.os.open", side_effect=raced_open):
            result = self.registry.evaluate("candidate", self.valid)
        self.assertTrue(changed)
        self.assertFalse(result["artifact_valid"])

    def test_growing_source_copy_is_bounded(self):
        original_read = os.read
        changed = False
        def raced_read(fd, count):
            nonlocal changed
            if not changed:
                changed = True
                with (self.source / "solve.py").open("ab") as stream:
                    stream.truncate(MAX_SOURCE + 1)
            return original_read(fd, count)
        with patch("runner.artifact_gate.os.read", side_effect=raced_read):
            result = self.registry.evaluate("candidate", self.valid)
        self.assertFalse(result["artifact_valid"])
        snapshot = self.registry.root / "snapshots" / result["id"]
        self.assertLessEqual(sum(p.stat().st_size for p in snapshot.rglob("*") if p.is_file()), MAX_SOURCE)

    def test_invalid_finalize_is_not_replaced_by_fallback(self):
        valid = self.registry.evaluate("candidate", self.valid)
        with self.assertRaises(ValueError):
            self.registry.finalize("candidate-999")
        self.registry.finalize(valid["id"])
        state = self.registry.close()
        self.assertIsNone(state["final_id"])
        self.assertEqual(state["selection_reason"], "invalid_finalize")

    def test_invalid_source_does_not_create_finalizable_snapshot(self):
        result = self.registry.evaluate("missing", self.valid)
        with self.assertRaises(ValueError):
            self.registry.finalize(result["id"])

    def test_attempt_limit_and_deadline(self):
        state = read_json(self.registry.root / "state.json")
        state["max_evaluations"] = 2
        (self.registry.root / "state.json").write_text(json.dumps(state))
        self.registry.evaluate("../outside", self.valid)
        self.registry.evaluate("missing", self.valid)
        with self.assertRaisesRegex(ValueError, "budget"):
            self.registry.evaluate("candidate", self.valid)
        other = Registry.create(self.base / "expired", self.workspace, "heat", "g1", budget_seconds=-1)
        with self.assertRaisesRegex(ValueError, "deadline"):
            other.evaluate("candidate", self.valid)

    def test_hash_tampering_detected(self):
        row = self.registry.evaluate("candidate", self.valid)
        path = self.registry.verified_snapshot(row["id"]) / "solve.py"
        path.chmod(0o644)
        path.write_text("tampered\n")
        with self.assertRaisesRegex(RuntimeError, "modified"):
            self.registry.verified_snapshot(row["id"])

    def test_callback_failure_is_logged_as_infrastructure_failure(self):
        def broken(*args):
            raise RuntimeError("test infrastructure fault")
        row = self.registry.evaluate("candidate", broken)
        self.assertEqual(row["result"]["attempt_status"], "infrastructure_error")
        self.assertIsNone(row["result"]["score"])
        self.assertIn("completed_at", row)
        self.assertEqual(len(read_json(self.registry.root / "state.json")["evaluations"]), 1)

    def test_source_preparation_runs_after_acceptance_and_failure_consumes_slot(self):
        def prepare(relative_source, candidate_id, remaining):
            self.assertEqual(relative_source, "candidate")
            self.assertGreater(remaining, 0)
            state = read_json(self.registry.root / "state.json")
            self.assertEqual(state["evaluations"][-1]["id"], candidate_id)
            self.assertIn("evaluate_accepted", (self.registry.root / "events.jsonl").read_text())
            raise RuntimeError("simulated exporter failure")
        row = self.registry.evaluate("candidate", self.valid, prepare_source=prepare)
        self.assertIsNone(row["source_hash"])
        self.assertEqual(row["result"]["attempt_status"], "submission_failed")
        self.assertIn("exporter failure", row["result"]["reason"])
        self.assertIn("completed_at", row)
        self.assertEqual(len(read_json(self.registry.root / "state.json")["evaluations"]), 1)

    def test_source_preparation_deadline_consumes_slot_and_never_executes(self):
        state = read_json(self.registry.root / "state.json")
        now = [state["started_at"] + 1799]
        def slow_prepare(relative_source, candidate_id, remaining):
            self.assertEqual(remaining, 1)
            now[0] += 2
            return relative_source
        def forbidden(*args):
            self.fail("expired source must never execute")
        with patch("runner.registry.time.time", side_effect=lambda: now[0]):
            row = self.registry.evaluate("candidate", forbidden, prepare_source=slow_prepare)
        self.assertIsNone(row["source_hash"])
        self.assertIn("deadline", row["result"]["reason"])
        self.assertIn("completed_at", row)
        self.assertEqual(len(read_json(self.registry.root / "state.json")["evaluations"]), 1)

    def test_trusted_close_outcome_is_recorded_and_immutable(self):
        evidence="a"*64
        state=self.registry.close(attempt_status="api_failed",reason="synthetic trusted provider error",evidence_sha256=evidence)
        self.assertEqual(state["attempt_status"],"api_failed")
        self.assertEqual(state["attempt_outcome"]["evidence_sha256"],evidence)
        self.assertEqual(self.registry.close(),state)
        self.assertEqual(self.registry.close(attempt_status="api_failed",reason="synthetic trusted provider error",evidence_sha256=evidence),state)
        with self.assertRaisesRegex(ValueError,"immutable"):
            self.registry.close(attempt_status="completed")
        events=[json.loads(line) for line in (self.registry.root/"events.jsonl").read_text().splitlines()]
        self.assertEqual(events[-1]["payload"]["attempt_outcome"],state["attempt_outcome"])

    def test_close_rejects_unknown_or_malformed_outcome_metadata(self):
        for kwargs in ({"attempt_status":"invented"},{"attempt_status":"completed","evidence_sha256":"bad"},
                       {"reason":"missing status"},{"attempt_status":"completed","reason":"x"*2049}):
            with self.assertRaises(ValueError):
                self.registry.close(**kwargs)
        self.assertFalse(read_json(self.registry.root/"state.json")["closed"])


if __name__ == "__main__":
    unittest.main()
