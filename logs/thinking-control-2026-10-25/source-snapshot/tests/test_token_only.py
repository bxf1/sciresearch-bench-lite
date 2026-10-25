"""Budget boundaries for the separately authorized token-only supplement."""
import tempfile
from pathlib import Path
import unittest

from harbor.models.task.config import TaskConfig
from runner.common import read_json
from runner.model_relay import EventLog, Ledger, Limits, Rejected
from runner.registry import Registry


class TokenOnlyTests(unittest.TestCase):
    def test_long_elapsed_time_and_request_count_do_not_stop_token_only_session(self):
        with tempfile.TemporaryDirectory() as folder:
            events = EventLog(Path(folder) / "events.jsonl")
            self.addCleanup(events.close)
            now = [0.0]
            ledger = Ledger(Limits(session_output_limit=500000, session_seconds=None,
                                   max_requests=None), events, clock=lambda: now[0])
            now[0] = 1e12
            ledger.request_count = 10000
            ledger.charged = 499999
            self.assertEqual(ledger.status()["state"], "ready")
            last = ledger.reserve(4096, 0)
            self.assertEqual(last.effective, 1)
            with self.assertRaises(Rejected):
                ledger.reserve(4096, 0)
            self.assertFalse(ledger.status()["expired"])

    def test_registry_without_total_limits_can_evaluate_and_finalize(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            work = root / "workspace"
            (work / "candidate").mkdir(parents=True)
            (work / "candidate/solve.py").write_text("pass\n")
            registry = Registry.create(root / "registry", work, "heat", "g1", None, None)
            row = registry.evaluate("candidate", lambda *_: {"artifact_valid": True})
            registry.finalize(row["id"])
            state = read_json(registry.root / "state.json")
            self.assertEqual(state["final_id"], row["id"])
            self.assertIsNone(state["budget_seconds"])
            self.assertIsNone(state["max_evaluations"])

    def test_harbor_omitted_agent_timeout_means_no_wall_deadline(self):
        config = TaskConfig.model_validate({"version": "1.0", "agent": {}})
        self.assertIsNone(config.agent.timeout_sec)
