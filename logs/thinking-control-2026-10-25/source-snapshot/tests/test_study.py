"""Formal controls tested with synthetic freezes, without Docker or API calls."""
import asyncio
import copy
from contextlib import contextmanager
import os
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from runner import study
from runner import study_report
from runner.common import canonical, digest, read_json, tree_hashes, write_json
from runner.registry import Registry
from runner.phase import checked_hashes
from runner.performance import ACCURACY_PROFILE, summarize_attempts
import test_run_plan
import test_performance


class StudyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = test_run_plan.RunPlanTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.plan = self.fixture.fixture()
        self.plan_path = self.project / "plan.json"
        write_json(self.plan_path, self.plan)
        self.launches = []

    def manifest(self):
        return read_json(self.project / "research-runs" / self.plan["plan_id"] / "manifest.json")

    async def launch(self, spec):
        self.launches.append(spec)
        settings = spec["settings"]
        output = Path(spec["output_root"])
        workspace = output / "workspace"
        workspace.mkdir(parents=True)
        registry = Registry.create(output / "registry", workspace, settings["task"], settings["group"])
        if settings["task"] in getattr(self, "candidate_tasks", set()):
            source = workspace / "candidate"
            source.mkdir()
            (source / "solve.py").write_text("print('synthetic candidate')\n")
            registry.evaluate("candidate", lambda *args: {"artifact_valid": True})
        registry.close(attempt_status="completed", reason="synthetic completion")
        return {"formal": True, **{key: settings[key] for key in ("run_id", "attempt_id", "parent_attempt", "task", "group", "repeat")},
                "attempt_status": "completed", "status": "research_frozen", "evaluation_status": "not_run", "score": None,
                "reward": None, "replay_split": None, "cleanup_errors": {}, "bridge_errors": []}

    async def test_draft_denied_before_ledger_launch_or_subprocess(self):
        write_json(self.plan_path, self.fixture.draft)
        launch = AsyncMock()
        with patch("subprocess.run", side_effect=AssertionError("no command permitted")):
            with self.assertRaisesRegex(ValueError, "draft cannot start"):
                await study.start(self.project, self.plan_path, self.plan["runs"][0]["run_id"], launch=launch)
        launch.assert_not_awaited()
        self.assertFalse((self.project / "research-runs").exists())

    async def test_session_exact_budgets_wire_binding_and_freshness(self):
        row = self.plan["runs"][0]
        spec = study.session_spec(self.project, self.plan_path, row["run_id"], row["run_id"] + "-a001")
        settings = spec["settings"]
        self.assertEqual((settings["research_seconds"], settings["max_evaluations"], settings["max_turns"]), (1800, 20, None))
        self.assertEqual((settings["research_vcpu"], settings["research_memory_bytes"]), (4, 4 * 1024**3))
        self.assertEqual(settings["session_id"], row["session_id"])
        self.assertEqual(Path(spec["output_root"]) / "workspace", self.project.resolve() / row["workdir"])
        policy = read_json(self.project / "policy.json")
        self.assertEqual(settings["expected_system_sha256"], policy["wire_system_sha256"])
        self.assertEqual(settings["expected_tools_sha256"], policy["wire_tools_sha256"])
        self.assertIs(study.validate_session(spec), spec)
        changed = copy.deepcopy(spec)
        changed["settings"]["max_turns"] = 12
        with self.assertRaisesRegex(ValueError, "differs"):
            study.validate_session(changed)

    async def test_order_closed_registry_and_normal_zero_cannot_retry(self):
        first, second = self.plan["runs"][:2]
        with self.assertRaisesRegex(ValueError, "order"):
            await study.start(self.project, self.plan_path, second["run_id"], launch=self.launch)
        result = await study.start(self.project, self.plan_path, first["run_id"], launch=self.launch)
        self.assertIsNone(result["score"])
        entry = self.manifest()["attempts"][0]
        self.assertTrue(read_json(self.project / entry["registry"]["path"])["closed"])
        for parent in (None, entry["attempt_id"]):
            with self.assertRaisesRegex(ValueError, "explicit linked retry"):
                await study.start(self.project, self.plan_path, first["run_id"], retry_of=parent, launch=self.launch)
        await study.start(self.project, self.plan_path, second["run_id"], launch=self.launch)
        self.assertEqual(len(self.manifest()["attempts"]), 2)

    async def test_thinking_control_is_frozen_through_native_session(self):
        model = self.plan['model']
        evidence = model['enforcement']['thinking']['evidence']
        model.update(thinking={'type': 'enabled'}, output_config={'effort': 'max'}, temperature=None,
                     output_token_limit=200000)
        model['enforcement']['temperature'] = {'status': 'unsupported', 'reason': 'Synthetic provider ignores temperature.',
                                               'evidence': evidence}
        model['enforcement']['output_config'] = {'status': 'verified', 'evidence': evidence}
        for task, ref in self.plan['freezes'].items():
            path = self.project / ref['path']
            frozen = read_json(path)
            frozen['research'].update(reasoning_configuration=model['thinking'], output_config=model['output_config'],
                                      temperature=None, output_token_limit=200000,
                                      model_parameter_enforcement=model['enforcement'])
            write_json(path, frozen)
            self.plan['freezes'][task] = self.fixture.ref(path)
        write_json(self.plan_path, self.plan)
        row = self.plan['runs'][0]
        spec = study.session_spec(self.project, self.plan_path, row['run_id'], row['run_id'] + '-a001')
        self.assertEqual(spec['settings']['thinking_effort'], 'max')
        self.assertEqual(spec['settings']['session_output_limit'], 200000)
        self.assertEqual(spec['settings']['request_output_limit'], 4096)
        self.assertIs(study.validate_session(spec), spec)
        model['output_config'] = {'effort': 'high'}
        write_json(self.plan_path, self.plan)
        launch = AsyncMock()
        with self.assertRaisesRegex(ValueError, 'thinking effort'):
            await study.start(self.project, self.plan_path, row['run_id'], launch=launch)
        launch.assert_not_awaited()

    async def test_failure_retained_explicit_linked_retry_is_fresh(self):
        row = self.plan["runs"][0]
        launch = AsyncMock(side_effect=RuntimeError("daemon capacity below formal contract"))
        failed = await study.start(self.project, self.plan_path, row["run_id"], launch=launch)
        self.assertEqual(failed["attempt_status"], "infrastructure_failed")
        first = self.manifest()["attempts"][0]
        with self.assertRaisesRegex(ValueError, "explicit linked"):
            await study.start(self.project, self.plan_path, row["run_id"], launch=self.launch)
        await study.start(self.project, self.plan_path, row["run_id"], retry_of=first["attempt_id"], launch=self.launch)
        entries = self.manifest()["attempts"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]["parent_attempt"], entries[0]["attempt_id"])
        self.assertEqual(read_json(self.project / entries[0]["result"]["path"])["attempt_status"], "infrastructure_failed")
        self.assertNotEqual(self.launches[0]["settings"]["session_id"], row["session_id"])
        self.assertIn("retries", self.launches[0]["output_root"])

    async def test_research_manifest_exports_without_hidden_scores(self):
        row = self.plan["runs"][0]
        await study.start(self.project, self.plan_path, row["run_id"], launch=AsyncMock(side_effect=RuntimeError("capacity")))
        first = self.manifest()["attempts"][0]
        await study.start(self.project, self.plan_path, row["run_id"], retry_of=first["attempt_id"], launch=self.launch)
        manifest_path = self.project / "research-runs" / self.plan["plan_id"] / "manifest.json"
        with patch("runner.replay.replay_checkpoint", side_effect=AssertionError("report cannot replay")):
            summary = study_report.export_study(self.project, self.plan_path, manifest_path, self.project / "report")
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(summary["scientific_sessions"], 0)
        self.assertEqual(summary["case_rows"], 0)

    async def test_post_registry_cleanup_failure_retains_state_and_allows_linked_retry(self):
        row = self.plan["runs"][0]
        before = {}
        async def failed_cleanup(spec):
            result = await self.launch(spec)
            registry = Path(spec["output_root"]) / "registry"
            before.update({name: (registry / name).read_bytes() for name in ("state.json", "events.jsonl")})
            return dict(result, status="research_invalid", cleanup_errors={"relay_cleanup": "synthetic failure"})
        result = await study.start(self.project, self.plan_path, row["run_id"], launch=failed_cleanup)
        self.assertEqual(result["attempt_status"], "infrastructure_failed")
        self.assertEqual(result["registry_attempt_status"], "completed")
        self.assertTrue(result["post_registry_failure"])
        entry = self.manifest()["attempts"][0]
        registry = (self.project / entry["registry"]["path"]).parent
        self.assertEqual(before, {name: (registry / name).read_bytes() for name in before})
        await study.start(self.project, self.plan_path, row["run_id"], retry_of=entry["attempt_id"], launch=self.launch)
        manifest_path = self.project / "research-runs" / self.plan["plan_id"] / "manifest.json"
        summary = study_report.export_study(self.project, self.plan_path, manifest_path, self.project / "post-close-report")
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(summary["scientific_sessions"], 0)

    async def test_t3_linked_replay_retry_retains_original_and_is_single_use(self):
        self.candidate_tasks = {"poisson"}
        freeze_path = self.project / self.plan["freezes"]["poisson"]["path"]
        frozen = read_json(freeze_path)
        case_ids = [f"c{index:02d}" for index in range(12)]
        frozen["data"]["final-test"]["input_hashes"].update({f"cases/{identifier}/grid.npy": "f" * 64 for identifier in case_ids})
        frozen["data_sha256"] = digest(canonical(frozen["data"]))
        write_json(freeze_path, frozen)
        self.plan["freezes"]["poisson"] = study.reference(self.project, freeze_path)
        write_json(self.plan_path, self.plan)
        for row in self.plan["runs"]:
            await study.start(self.project, self.plan_path, row["run_id"], launch=self.launch)
        row = next(row for row in self.plan["runs"] if row["task"] == "poisson")
        manifest_path = self.project / "research-runs" / self.plan["plan_id"] / "manifest.json"
        freeze = read_json(self.project / self.plan["freezes"][row["task"]]["path"])
        freeze_sha = self.plan["freezes"][row["task"]]["sha256"]
        def include_phase(record):
            for sample in record["samples"]:
                sample.update(phase={"formal": True, "split": "final-test", "freeze_sha256": freeze_sha},
                              score=100, reward=1, cases=[{"id": identifier, "score": 100, "scientific_pass": True, "artifact_valid": True} for identifier in case_ids])
            return record
        def original_replay(snapshot, identifier, selected_hash, **kwargs):
            record = include_phase(test_performance.fixture(b=(2, 2, 2.5)))
            result = summarize_attempts([record], profile=ACCURACY_PROFILE)
            return dict(result, protocol_attempt=record, samples={role: [item for item in record["samples"] if item["role"] == role] for role in ("B", "C")},
                        checkpoint_id=identifier, source_hash=selected_hash)
        def retry_group(snapshot, *, parent_attempt, interference_resolution, **kwargs):
            record = include_phase(test_performance.fixture(attempt_id="synthetic-retry"))
            record.update(parent_attempt=parent_attempt, interference_resolution=interference_resolution)
            return {"protocol_attempt": record, "samples": {role: [item for item in record["samples"] if item["role"] == role] for role in ("B", "C")}}
        patches = (patch("runner.replay.prepare_judge", return_value=self.project / "judge"),
                   patch.object(study, "checked_hashes", return_value=freeze["judge_source_hashes"]),
                   patch.object(study, "guard_replay", return_value={"formal": True, "split": "final-test"}))
        with patches[0], patches[1], patches[2]:
            original = study.final(self.project, self.plan_path, row["run_id"], self.project / "data",
                                   timing_contract=self.project / "timing.json", execute=original_replay)
            current = next(entry for entry in self.manifest()["attempts"] if entry["run_id"] == row["run_id"])
            old_ref = copy.deepcopy(current["replay"])
            old_path = self.project / old_ref["path"]
            old_bytes = old_path.read_bytes()
            with patch("runner.replay.run_t3_attempt", side_effect=retry_group) as execute:
                retry = study.final(self.project, self.plan_path, row["run_id"], self.project / "data",
                                    timing_contract=self.project / "timing.json", retry_replay=old_path,
                                    interference_resolution="synthetic unrelated workload removed")
            self.assertEqual(execute.call_count, 1)  # Same-source final reuses first.
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertEqual(retry["parent_replay"], old_ref)
            self.assertEqual(retry["replay_retry_number"], 1)
            self.assertEqual(retry["diagnostics"]["first"]["repeats"][0]["selected_attempt"], 1)
            self.assertEqual(len(retry["diagnostics"]["first"]["repeats"][0]["attempts"]), 2)
            self.assertEqual(retry["diagnostics"]["final"]["replay_count"], 0)
            self.assertEqual(retry["diagnostics"]["reward"], 1)
            current = next(entry for entry in self.manifest()["attempts"] if entry["run_id"] == row["run_id"])
            self.assertEqual(current["replay_history"], [old_ref])
            summary = study_report.export_study(self.project, self.plan_path, manifest_path, self.project / "retry-report")
            self.assertEqual(summary["scientific_sessions"], 1)
            self.assertEqual(summary["attempts"], 15)
            self.assertEqual(summary["case_rows"], 36)
            with self.assertRaisesRegex(ValueError, "only one"):
                study.final(self.project, self.plan_path, row["run_id"], self.project / "data",
                            timing_contract=self.project / "timing.json", retry_replay=self.project / current["replay"]["path"],
                            interference_resolution="cannot try again")

    async def test_final_barrier_precedes_any_hidden_data_or_replay_access(self):
        row = self.plan["runs"][0]
        await study.start(self.project, self.plan_path, row["run_id"], launch=self.launch)
        with patch("runner.replay.prepare_judge", side_effect=AssertionError("barrier must precede judge")), patch.object(study, "guard_replay", side_effect=AssertionError("must not read final")):
            with self.assertRaisesRegex(ValueError, "all related research"):
                study.final(self.project, self.plan_path, row["run_id"], self.project / "forbidden-final")

    async def test_final_single_use_zero_and_task_research_lock(self):
        for row in self.plan["runs"]:
            await study.start(self.project, self.plan_path, row["run_id"], launch=self.launch)
        row = self.plan["runs"][0]
        freeze = read_json(self.project / self.plan["freezes"][row["task"]]["path"])
        execute = Mock(side_effect=AssertionError("no candidate means no replay"))
        def guarded(*args, **kwargs):
            self.assertIn(row["task"], self.manifest()["finalized_tasks"])
            return {"formal": True, "split": "final-test"}
        with patch("runner.replay.prepare_judge", return_value=self.project / "judge"), patch.object(study, "checked_hashes", return_value=freeze["judge_source_hashes"]), patch.object(study, "guard_replay", side_effect=guarded):
            result = study.final(self.project, self.plan_path, row["run_id"], self.project / "data", execute=execute)
        self.assertEqual(result["diagnostics"]["score"], 0)
        self.assertEqual(result["diagnostics"]["reward"], 0)
        self.assertTrue(result["formal"])
        self.assertEqual(result["split"], "final-test")
        execute.assert_not_called()
        with self.assertRaisesRegex(ValueError, "already attempted"):
            study.final(self.project, self.plan_path, row["run_id"], self.project / "data")
        with self.assertRaisesRegex(ValueError, "permanently closed"):
            await study.start(self.project, self.plan_path, row["run_id"], launch=self.launch)

    async def test_failed_related_session_never_becomes_scientific_completion(self):
        for row in self.plan["runs"]:
            callback = AsyncMock(side_effect=RuntimeError("API unavailable")) if row["sequence"] == 2 else self.launch
            await study.start(self.project, self.plan_path, row["run_id"], launch=callback)
        with patch.object(study, "guard_replay", side_effect=AssertionError("no hidden reads")):
            with self.assertRaisesRegex(ValueError, "all related research"):
                study.final(self.project, self.plan_path, self.plan["runs"][0]["run_id"], self.project / "data")

    async def test_registration_verifier_has_no_replay_or_numeric_reward(self):
        row = self.plan["runs"][0]
        await study.start(self.project, self.plan_path, row["run_id"], launch=self.launch)
        entry = self.manifest()["attempts"][0]
        root = (self.project / entry["registry"]["path"]).parent
        paths = SimpleNamespace(verifier_dir=self.project / "verifier", artifacts_dir=self.project / "artifacts")
        task = SimpleNamespace(config=SimpleNamespace(verifier=SimpleNamespace(environment_mode="separate")))
        env = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(return_code=0, stdout="")))
        verifier = study.RegistrationVerifier(registry_root=str(root), task_name=row["task"],
                                              task=task, trial_paths=paths, environment=env)
        with patch("runner.replay.replay_checkpoint", side_effect=AssertionError("registration cannot replay")):
            result = await verifier.verify()
        self.assertIsNone(result.rewards)
        record = read_json(paths.verifier_dir / "research-registration.json")
        self.assertEqual(record["registration_status"], "registered")
        self.assertEqual(record["evaluation_status"], "not_run")
        self.assertIsNone(record["score"])
        paths.artifacts_dir.mkdir()
        (paths.artifacts_dir / "unexpected.npy").write_bytes(b"untrusted")
        await verifier.verify()
        self.assertEqual(read_json(paths.verifier_dir / "research-registration.json")["registration_status"], "invalid")


class BaselineTests(unittest.IsolatedAsyncioTestCase):
    setUp = StudyTests.setUp
    launch = StudyTests.launch
    manifest = StudyTests.manifest

    async def ready(self):
        for task in study.METHODS:
            path = self.project / self.plan["freezes"][task]["path"]
            frozen = read_json(path)
            frozen["data"]["final-test"]["input_hashes"].update({f"cases/c{index:02d}/input.dat": "e" * 64 for index in range(12)})
            frozen["data_sha256"] = digest(canonical(frozen["data"]))
            write_json(path, frozen)
            self.plan["freezes"][task] = study.reference(self.project, path)
        write_json(self.plan_path, self.plan)
        for row in self.plan["runs"]:
            await study.start(self.project, self.plan_path, row["run_id"], launch=self.launch)

    @contextmanager
    def replay_environment(self, task):
        frozen = read_json(self.project / self.plan["freezes"][task]["path"])
        judge = self.project / "trusted-judge" / task
        def hashes(path):
            return frozen["judge_source_hashes"] if Path(path) == judge else checked_hashes(path)
        def guard(*args, **kwargs):
            self.assertIn(task, self.manifest()["finalized_tasks"])
            self.assertEqual(Path(args[1]).name, "final-test")
            self.assertEqual(Path(args[2]).name, "final-test")
        with patch("runner.replay.prepare_judge", return_value=judge), patch.object(study, "checked_hashes", side_effect=hashes), patch.object(study, "guard_replay", side_effect=guard):
            yield

    def phase(self, task):
        frozen = read_json(self.project / self.plan["freezes"][task]["path"])
        return {"formal": True, "split": "final-test", "freeze_sha256": self.plan["freezes"][task]["sha256"], "profile": frozen["profile"]}

    def group(self, task, method, source_hash, *, unstable=False, attempt_id="synthetic-original"):
        frozen = read_json(self.project / self.plan["freezes"][task]["path"])
        record = test_performance.fixture(b=(2, 2, 2.5) if unstable else (2, 2, 2), attempt_id=attempt_id)
        record["candidate_method"] = method
        for sample in record["samples"]:
            sample.update(phase=self.phase(task), source_hash=source_hash, score=100, reward=1,
                          cases=[{"id": f"c{index:02d}", "score": 100, "scientific_pass": True, "artifact_valid": True} for index in range(12)])
            sample["worker"].update(image=frozen["image_id"], source_hash=source_hash)
        return record

    def execute(self, source, identifier, source_hash, **config):
        task = config["task"]
        self.assertEqual(checked_hashes(source), {"solve.py": self.plan["tool_config"]["files"][f"baselines/{task}/solve.py"]})
        self.assertEqual((source / "solve.py").stat().st_mode & 0o222, 0)
        self.assertEqual(config["image"], read_json(self.project / self.plan["freezes"][task]["path"])["image_id"])
        if task == "poisson":
            self.assertNotIn("method", config)
            self.assertEqual(config["baseline_source"], source)
            record = self.group(task, config["candidate_method"], source_hash)
            result = summarize_attempts([record], profile=config["profile"])
            return dict(result, checkpoint_id=identifier, source_hash=source_hash, protocol_attempt=record,
                        samples={role: [sample for sample in record["samples"] if sample["role"] == role] for role in ("B", "C")})
        self.assertNotIn("candidate_method", config)
        self.assertIn(config["method"], study.METHODS[task])
        return {"checkpoint_id": identifier, "source_hash": source_hash, "phase": self.phase(task),
                "worker": {"image": config["image"], "source_hash": source_hash}, "evaluation_status": "valid", "score": 100, "reward": 1,
                "scientific_pass": True, "artifact_valid": True,
                "cases": [{"id": f"c{index:02d}", "score": 100, "scientific_pass": True, "artifact_valid": True} for index in range(12)]}

    async def test_baseline_draft_method_and_research_barriers_precede_work(self):
        execute = Mock(side_effect=AssertionError("no solver execution"))
        write_json(self.plan_path, self.fixture.draft)
        with self.assertRaisesRegex(ValueError, "draft cannot start"):
            study.baseline(self.project, self.plan_path, "heat", "ls", self.project / "data", execute=execute)
        self.assertFalse((self.project / "research-runs").exists())
        write_json(self.plan_path, self.plan)
        with self.assertRaisesRegex(ValueError, "predeclared"):
            study.baseline(self.project, self.plan_path, "heat", "foreign-method", self.project / "data", execute=execute)
        with patch("runner.replay.prepare_judge", side_effect=AssertionError("no setup before research barrier")):
            with self.assertRaisesRegex(ValueError, "all related research"):
                study.baseline(self.project, self.plan_path, "heat", "ls", self.project / "data", execute=execute)
        execute.assert_not_called()

    async def test_all_eleven_methods_use_frozen_sources_protocols_and_separate_denominator(self):
        await self.ready()
        calls = Mock(side_effect=self.execute)
        for task, methods in study.METHODS.items():
            cache = self.project / "baselines" / task / "__pycache__"
            cache.mkdir()
            (cache / "solve.cpython-312.pyc").write_bytes(b"ordinary cache is not solver source")
            for method in methods:
                with self.replay_environment(task):
                    result = study.baseline(self.project, self.plan_path, task, method, self.project / "data",
                                            timing_contract=self.project / "timing.json", execute=calls)
                self.assertEqual(calls.call_args.kwargs["candidate_method" if task == "poisson" else "method"], method)
                self.assertEqual(result["status"], "baseline_completed")
                self.assertEqual(result["diagnostics"]["replay_count"], 1 if task == "poisson" else 3)
                self.assertEqual(result["fixed_reference"], method == study.FIXED[task])
                self.assertEqual(set(result["source_files"]), {"solve.py"})
                self.assertEqual(result["source_hash"], digest(canonical(result["source_files"])))
                entry = self.manifest()["baselines"][-1]
                self.assertFalse((self.project / entry["result"]["path"]).parent.joinpath("source/__pycache__").exists())
        self.assertEqual(calls.call_count, 27)
        self.assertEqual(len(self.manifest()["baselines"]), 11)
        self.assertEqual(len(self.manifest()["attempts"]), 15)
        manifest_path = self.project / "research-runs" / self.plan["plan_id"] / "manifest.json"
        summary = study_report.export_study(self.project, self.plan_path, manifest_path, self.project / "all-baselines-report")
        self.assertEqual(summary["attempts"], 15)
        self.assertEqual(summary["scientific_sessions"], 0)
        self.assertEqual(summary["baseline_attempts"], 11)
        self.assertEqual(len(summary["baseline_methods"]), 11)
        self.assertEqual(summary["pending_baselines"], [])

    async def test_setup_failure_is_retained_and_linked_retry_cannot_replace_scientific_zero(self):
        await self.ready()
        with self.replay_environment("heat"):
            with patch("runner.replay.prepare_judge", side_effect=RuntimeError("synthetic trusted setup failure")):
                failed = study.baseline(self.project, self.plan_path, "heat", "ls", self.project / "data", execute=Mock())
            self.assertEqual(failed["status"], "baseline_invalid")
            first = self.manifest()["baselines"][0]
            before = (self.project / first["result"]["path"]).read_bytes()
            for parent, reason in ((None, "investigated"), (first["attempt_id"], None)):
                with self.assertRaises(ValueError):
                    study.baseline(self.project, self.plan_path, "heat", "ls", self.project / "data", retry_of=parent, retry_reason=reason)
            zero = Mock(return_value={"evaluation_status": "valid", "score": 0, "reward": 0})
            retry = study.baseline(self.project, self.plan_path, "heat", "ls", self.project / "data", execute=zero,
                                   retry_of=first["attempt_id"], retry_reason="trusted setup repaired")
            self.assertEqual(retry["parent_attempt"], first["attempt_id"])
            self.assertEqual(retry["retry_kind"], "infrastructure")
            self.assertEqual(retry["diagnostics"]["score"], 0)
            self.assertEqual((self.project / first["result"]["path"]).read_bytes(), before)
            with self.assertRaisesRegex(ValueError, "scientific zero"):
                study.baseline(self.project, self.plan_path, "heat", "ls", self.project / "data",
                               retry_of=retry["attempt_id"], retry_reason="cannot replace zero")

    async def test_t3_baseline_investigated_retry_preserves_protocol_and_report_denominator(self):
        await self.ready()
        def unstable(source, identifier, source_hash, **config):
            record = self.group("poisson", config["candidate_method"], source_hash, unstable=True)
            return dict(summarize_attempts([record], profile=config["profile"]), checkpoint_id=identifier, source_hash=source_hash,
                        protocol_attempt=record, samples={role: [item for item in record["samples"] if item["role"] == role] for role in ("B", "C")})
        def retry_group(source, *, parent_attempt, interference_resolution, **config):
            self.assertEqual(config["candidate_method"], "lu")
            self.assertNotIn("method", config)
            record = self.group("poisson", "lu", digest(canonical(checked_hashes(source))), attempt_id="synthetic-retry")
            record.update(parent_attempt=parent_attempt, interference_resolution=interference_resolution)
            return {"protocol_attempt": record, "samples": {role: [item for item in record["samples"] if item["role"] == role] for role in ("B", "C")}}
        with self.replay_environment("poisson"):
            first = study.baseline(self.project, self.plan_path, "poisson", "lu", self.project / "data",
                                   timing_contract=self.project / "timing.json", execute=unstable)
            original_ref = self.manifest()["baselines"][0]["result"]
            original_bytes = (self.project / original_ref["path"]).read_bytes()
            with self.assertRaisesRegex(ValueError, "investigated"):
                study.baseline(self.project, self.plan_path, "poisson", "lu", self.project / "data",
                               timing_contract=self.project / "timing.json", retry_of=first["attempt_id"])
            with patch("runner.replay.run_t3_attempt", side_effect=retry_group) as execute:
                retried = study.baseline(self.project, self.plan_path, "poisson", "lu", self.project / "data",
                                         timing_contract=self.project / "timing.json", retry_of=first["attempt_id"],
                                         interference_resolution="synthetic noisy workload removed")
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(retried["retry_kind"], "baseline_instability")
            self.assertEqual(retried["retry_reason"], retried["interference_resolution"])
            self.assertEqual(retried["parent_attempt"], first["attempt_id"])
            group = retried["diagnostics"]["repeats"][0]
            self.assertEqual(group["selected_attempt"], 1)
            self.assertEqual(len(group["attempts"]), 2)
            self.assertFalse(group["retry_permitted"])
            self.assertEqual((self.project / original_ref["path"]).read_bytes(), original_bytes)
            self.assertEqual(len(self.manifest()["baselines"]), 2)
            with self.assertRaisesRegex(ValueError, "completed baseline"):
                study.baseline(self.project, self.plan_path, "poisson", "lu", self.project / "data",
                               timing_contract=self.project / "timing.json", retry_of=retried["attempt_id"],
                               interference_resolution="cannot repeat a completed group")
        manifest_path = self.project / "research-runs" / self.plan["plan_id"] / "manifest.json"
        report = study_report.export_study(self.project, self.plan_path, manifest_path, self.project / "t3-baseline-retry-report")
        self.assertEqual(report["attempts"], 15)
        self.assertEqual(report["scientific_sessions"], 0)
        self.assertEqual(report["baseline_attempts"], 2)
        selected = next(row for row in report["baseline_methods"] if row["task"] == "poisson" and row["method"] == "lu")
        self.assertEqual(selected["attempt_id"], retried["attempt_id"])

    def test_unknown_files_and_linked_cache_cannot_enter_author_source(self):
        source = self.project / "baselines/heat"
        unexpected = source / "extra.dat"
        unexpected.write_bytes(b"unknown data")
        with self.assertRaisesRegex(ValueError, "source differs"):
            study.baseline_source(self.project, self.plan, "heat")
        unexpected.unlink()
        cache = source / "__pycache__"
        cache.mkdir()
        (cache / "solve.cpython-312.pyc").symlink_to(source / "solve.py")
        with self.assertRaisesRegex(ValueError, "links"):
            study.baseline_source(self.project, self.plan, "heat")


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        workspace = self.root / "workspace"
        source = workspace / "candidate"
        source.mkdir(parents=True)
        (source / "solve.py").write_text("print('synthetic candidate')\n")
        self.registry = Registry.create(self.root / "registry", workspace, "heat", "g1")
        self.registry.evaluate("candidate", lambda *args: {"artifact_valid": True})
        self.state = self.registry.close(attempt_status="completed")

    def replay(self, snapshot, identifier, source_hash, **kwargs):
        return {"checkpoint_id": identifier, "source_hash": source_hash, "evaluation_status": "valid", "score": 0, "reward": 0}

    def test_three_replays_same_hash_final_reused_and_zero_is_valid(self):
        execute = Mock(side_effect=self.replay)
        result = study.score_checkpoints(self.registry, self.state, {"output_root": self.root / "replay"}, execute=execute)
        self.assertEqual(execute.call_count, 3)
        self.assertEqual(result["first"]["replay_count"], 3)
        self.assertEqual(result["final"]["replay_count"], 0)
        self.assertEqual(result["final"]["reused_from"], "candidate-001")
        self.assertEqual((result["score"], result["reward"], result["evaluation_status"]), (0, 0, "valid"))

    def test_poisson_runs_existing_complete_protocol_once(self):
        self.state["task"] = "poisson"
        execute = Mock(side_effect=self.replay)
        study.score_checkpoints(self.registry, self.state, {"output_root": self.root / "replay"}, execute=execute)
        self.assertEqual(execute.call_count, 1)

    def test_stable_t3_checkpoint_or_missing_investigation_cannot_retry(self):
        self.state["task"] = "poisson"
        original = study.score_checkpoints(self.registry, self.state, {"output_root": self.root / "replay"}, execute=self.replay)
        execute = Mock(side_effect=AssertionError("stable group cannot run again"))
        with self.assertRaisesRegex(ValueError, "no original baseline instability"):
            study.retry_checkpoints(self.registry, self.state, {"output_root": self.root / "retry"}, original,
                                    interference_resolution="arbitrary request", execute=execute)
        with self.assertRaisesRegex(ValueError, "investigation"):
            study.retry_checkpoints(self.registry, self.state, {"output_root": self.root / "retry"}, original,
                                    interference_resolution="", execute=execute)
        execute.assert_not_called()

    def test_changed_snapshot_fails_before_replay(self):
        path = self.registry.root / "snapshots/candidate-001/solve.py"
        path.chmod(0o644)
        path.write_text("modified")
        execute = Mock()
        with self.assertRaisesRegex(RuntimeError, "modified"):
            study.score_checkpoints(self.registry, self.state, {"output_root": self.root}, execute=execute)
        execute.assert_not_called()

    def test_public_infrastructure_failure_cannot_become_scientific_zero(self):
        self.state["evaluations"][0].update(artifact_valid=False, result={"attempt_status": "infrastructure_failed"})
        with self.assertRaisesRegex(ValueError, "no scientific zero"):
            study.score_checkpoints(self.registry, self.state, {"output_root": self.root}, execute=Mock())

    def test_invalid_replay_keeps_null_scores(self):
        execute = Mock(return_value={"evaluation_status": "evaluation_invalid", "score": None, "reward": None})
        result = study.score_checkpoints(self.registry, self.state, {"output_root": self.root}, execute=execute)
        self.assertEqual(result["evaluation_status"], "invalid")
        self.assertIsNone(result["score"])
        self.assertIsNone(result["reward"])


if __name__ == "__main__":
    unittest.main()
