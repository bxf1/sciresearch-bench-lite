from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from harbor.models.trial.paths import TrialPaths
from runner.harbor_verifier import ResearchReplayVerifier
from runner.registry import Registry


class EmptyJudgeEnvironment:
    async def exec(self, **kwargs):
        return types.SimpleNamespace(return_code=0, stdout="", stderr="")


class HarborVerifierTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / "workspace"
        self.source = self.work / "candidate"
        self.source.mkdir(parents=True)
        (self.source / "solve.py").write_text("print('numeric worker entry')\n")
        self.registry = Registry.create(self.root / "registry", self.work, "heat", "g3")
        self.paths = TrialPaths(self.root / "trial")
        self.paths.mkdir()
        task = types.SimpleNamespace(config=types.SimpleNamespace(
            verifier=types.SimpleNamespace(environment_mode="separate")))
        self.verifier = ResearchReplayVerifier(
            registry_root=str(self.registry.root), replay_config={
                "task": "heat", "output_root": self.root / "replays", "profile": None},
            task=task, trial_paths=self.paths, environment=EmptyJudgeEnvironment())

    def register(self):
        return self.registry.evaluate("candidate", lambda *args: {"artifact_valid": True})["id"]

    async def run_mocked(self, outputs):
        calls = []
        def replay(*args, **kwargs):
            calls.append((args, kwargs))
            return outputs[len(calls) - 1]
        module = types.ModuleType("runner.replay")
        module.replay_checkpoint = replay
        with patch.dict(sys.modules, {"runner.replay": module}):
            result = await self.verifier.verify()
        diagnostics = json.loads((self.paths.verifier_dir / "research-replay.json").read_text())
        return result, diagnostics, calls

    async def test_three_replays_and_identical_hash_reuse(self):
        first, final = self.register(), self.register()
        self.registry.finalize(final)
        self.registry.close()
        result, diagnostics, calls = await self.run_mocked([
            {"evaluation_status": "valid", "reward": 1, "score": value} for value in (90, 93, 96)])
        self.assertEqual(result.rewards, {"reward": 1})
        self.assertEqual(len(calls), 3)
        self.assertEqual(diagnostics["final"]["reused_from"], first)
        self.assertEqual(diagnostics["final"]["checkpoint_id"], final)
        self.assertEqual(diagnostics["final"]["replay_count"], 0)
        self.assertEqual(diagnostics["score"], 93)
        self.assertEqual(len({str(kwargs["output_root"]) for _, kwargs in calls}), 3)

    async def test_one_failed_replay_is_zero_reward(self):
        self.register()
        self.registry.close()
        result, diagnostics, calls = await self.run_mocked([
            {"evaluation_status": "valid", "reward": reward, "score": 70.0}
            for reward in (1, 0, 1)])
        self.assertEqual(result.rewards, {"reward": 0})
        self.assertEqual(diagnostics["evaluation_status"], "valid")
        self.assertEqual(len(calls), 3)

    async def test_invalid_replay_preserves_null(self):
        self.register()
        self.registry.close()
        result, diagnostics, _ = await self.run_mocked([
            {"evaluation_status": "invalid", "reward": None, "score": None}] * 3)
        self.assertIsNone(result.rewards)
        self.assertIsNone(diagnostics["reward"])
        self.assertFalse(self.paths.reward_json_path.exists())

    async def test_open_registry_is_refused_before_replay(self):
        self.register()
        result, diagnostics, calls = await self.run_mocked([])
        self.assertIsNone(result.rewards)
        self.assertIn("close research", diagnostics["reason"])
        self.assertFalse(calls)

    async def test_automatic_artifact_is_refused_before_gt(self):
        self.register()
        self.registry.close()
        (self.paths.artifacts_dir / "forged-reward.json").write_text('{"reward":1}')
        result, diagnostics, calls = await self.run_mocked([])
        self.assertIsNone(result.rewards)
        self.assertIn("automatic verifier transfer", diagnostics["reason"])
        self.assertFalse(calls)

    async def test_no_submission_is_zero_with_no_replay(self):
        self.registry.close()
        result, diagnostics, calls = await self.run_mocked([])
        self.assertEqual(result.rewards, {"reward": 0})
        self.assertEqual(diagnostics["final"]["replay_count"], 0)
        self.assertFalse(calls)

    async def test_tampered_snapshot_is_invalid(self):
        candidate = self.register()
        self.registry.close()
        file = self.registry.root / "snapshots" / candidate / "solve.py"
        file.chmod(0o644)
        file.write_text("print('tampered')\n")
        result, diagnostics, calls = await self.run_mocked([])
        self.assertIsNone(result.rewards)
        self.assertIn("snapshot was modified", diagnostics["reason"])
        self.assertFalse(calls)

    async def test_trusted_api_failure_is_invalid_instead_of_scientific_zero(self):
        self.registry.close(attempt_status="api_failed",reason="synthetic host-observed provider failure")
        result,diagnostics,calls=await self.run_mocked([])
        self.assertIsNone(result.rewards)
        self.assertEqual(diagnostics["research_attempt_status"],"api_failed")
        self.assertEqual(diagnostics["evaluation_status"],"invalid")
        self.assertFalse(calls)
        self.assertFalse(self.paths.reward_json_path.exists())

    async def test_trusted_infrastructure_failure_invalidates_existing_candidate(self):
        self.register()
        self.registry.close(attempt_status="infrastructure_failed")
        result,diagnostics,calls=await self.run_mocked([])
        self.assertIsNone(result.rewards)
        self.assertIn("infrastructure_failed",diagnostics["reason"])
        self.assertFalse(calls)

    async def test_trusted_cancellation_is_invalid(self):
        self.registry.close(attempt_status="cancelled")
        result,diagnostics,calls=await self.run_mocked([])
        self.assertIsNone(result.rewards)
        self.assertEqual(diagnostics["research_attempt_status"],"cancelled")
        self.assertFalse(calls)

    async def test_normal_research_timeout_without_submission_remains_zero(self):
        self.registry.close(attempt_status="research_timeout")
        result,diagnostics,calls=await self.run_mocked([])
        self.assertEqual(result.rewards,{"reward":0})
        self.assertEqual(diagnostics["evaluation_status"],"valid")
        self.assertFalse(calls)

    async def test_normal_research_timeout_replays_fallback_candidate(self):
        candidate=self.register()
        self.registry.close(attempt_status="research_timeout")
        result,diagnostics,calls=await self.run_mocked([{"evaluation_status":"valid","reward":1,"score":90}]*3)
        self.assertEqual(result.rewards,{"reward":1})
        self.assertEqual(diagnostics["final"]["checkpoint_id"],candidate)
        self.assertEqual(len(calls),3)

    async def test_formal_replay_requires_explicit_host_outcome(self):
        self.registry.close()
        self.verifier.replay_config["freeze_path"]=self.root/"synthetic-freeze.json"
        result,diagnostics,calls=await self.run_mocked([])
        self.assertIsNone(result.rewards)
        self.assertIn("explicit closed host",diagnostics["reason"])
        self.assertFalse(calls)


if __name__ == "__main__":
    unittest.main()
