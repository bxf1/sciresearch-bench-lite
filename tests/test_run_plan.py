"""Run-plan gates use synthetic temporary freezes; real packages stay unfrozen.

Package inspection reads the generated public task directories and parses the
installed Harbor TaskConfig. No Docker build, network call or research is run.
"""
import copy
from collections import Counter
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harbor.models.task.config import TaskConfig
from authoring.package_tasks import INPUTS
from runner import phase, run_plan
from runner.common import TASKS, VERSION, canonical, digest, file_hash, read_json, write_json


class RunPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        for task in TASKS:
            for name in ("common.md", "g1.md", "g2.md", "g3.md"):
                path = self.project / "prompts" / task / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("" if name == "g3.md" else "synthetic " + task + name)
            package = self.project / "tasks" / task
            (package / "environment/public-dev").mkdir(parents=True)
            write_json(package / "environment/public-dev/manifest.json", {"synthetic": True})
            write_json(package / "contract.json", {"status": "prepared_not_frozen"})
            (package / "task.toml").write_text('# synthetic fixture, not a runnable Harbor package\n')
        write_json(self.project / "tasks/package-manifest.json", {"status": "prepared_not_frozen"})
        for name in run_plan.TOOL_FILES:
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic trusted tooling fixture\n")
        self.draft = run_plan.create_draft(self.project, order_entropy="01" * 32)

    def ref(self, path):
        return {"path": path.relative_to(self.project).as_posix(), "sha256": file_hash(path)}

    def fixture(self):
        """Only temporary synthetic fixtures may claim frozen in this test."""
        plan = copy.deepcopy(self.draft)
        plan.update(status="frozen", formal_ready=True)
        evidence = self.project / "evidence.txt"
        evidence.write_text("Synthetic unit-test evidence; never a benchmark acceptance decision.\n")
        plan["model"].update(model_version="synthetic-fixed-model-revision", thinking="off", temperature=0,
                              output_token_limit=10000,
                              version_resolution={"status": "verified", "evidence": self.ref(evidence)},
                              enforcement={key: {"status": "verified", "evidence": self.ref(evidence)}
                                           for key in run_plan.PARAMETERS})
        plan["system_prompt"] = self.ref(evidence)
        plan["tool_config"].update(runtime_tools=["read", "write", "edit", "bash"], runtime_enforcement=self.ref(evidence))
        plan["tool_config_sha256"] = digest(canonical(plan["tool_config"]))
        for task in TASKS:
            context = {name.removeprefix("environment/"): sha for name, sha in plan["tasks"][task]["package_files"].items()
                       if name.startswith("environment/")}
            context_sha = digest(canonical(context))
            inspection = self.project / "image-inspection" / (task + ".json")
            write_json(inspection, {"status": "verified", "task": task, "image_id": "sha256:" + "d" * 64,
                                    "build_context_sha256": context_sha})
            plan["research_images"][task] = {"image_id": "sha256:" + "d" * 64, "build_context_sha256": context_sha,
                                              "inspection": self.ref(inspection)}
            hashes = phase.checked_hashes(self.project / "tasks" / task / "environment/public-dev")
            data = {split: {"input_hashes": hashes, "truth_hashes": {"synthetic.txt": "a" * 64}}
                    for split in phase.FORMAL_SPLITS}
            judge = {name: "b" * 64 for name in ("judge/batch.py", f"judge/{task}.py", f"public/{task}.py",
                                                 "runner/common.py", "runner/artifact_gate.py", "runner/phase.py")}
            research = {key: plan["model"][key] for key in ("model_id", "model_version", "pi_version", "harbor_commit",
                                                            "temperature", "output_token_limit")}
            research.update(reasoning_configuration=plan["model"]["thinking"], system_prompt_sha256=file_hash(evidence),
                            tool_config_sha256=plan["tool_config_sha256"], run_matrix_sha256=plan["run_matrix_sha256"],
                            prompt_hashes=plan["tasks"][task]["prompt_hashes"],
                            model_version_resolution=plan["model"]["version_resolution"],
                            model_parameter_enforcement=plan["model"]["enforcement"],
                            research_image_id=plan["research_images"][task]["image_id"],
                            research_build_context_sha256=context_sha)
            checks = (*phase.ACCEPTANCE, "timing_profile") if task == "poisson" else phase.ACCEPTANCE
            plan["acceptance_evidence"][task] = {check: self.ref(evidence) for check in checks}
            frozen = {"schema_version": 1, "status": "frozen", "contract_version": VERSION, "task": task,
                      "thresholds": phase.THRESHOLDS[task], "resources": phase.RESOURCES, "dependencies": phase.DEPENDENCIES,
                      "profile": "accuracy_with_efficiency_diagnostic" if task == "poisson" else "accuracy",
                      "image_id": "sha256:" + "c" * 64, "data": data, "data_sha256": digest(canonical(data)),
                      "judge_source_hashes": judge, "judge_sha256": digest(canonical(judge)), "research": research,
                      "acceptance": {name: {"status": "passed", "evidence_sha256": file_hash(evidence)} for name in checks}}
            path = self.project / "freezes" / f"synthetic-{task}.json"
            write_json(path, frozen)
            plan["freezes"][task] = self.ref(path)
        return plan

    def blocked(self, plan, phrase):
        with self.assertRaisesRegex(run_plan.RunPlanError, phrase):
            run_plan.validate_start(plan, self.project)

    def test_reproducible_random_blocks_independent_sessions_and_exact_budgets(self):
        plan = self.draft
        self.assertEqual(plan["runs"], run_plan.create_draft(self.project, order_entropy="01" * 32)["runs"])
        self.assertNotEqual(plan["runs"], run_plan.create_draft(self.project, order_entropy="02" * 32)["runs"])
        rows = plan["runs"]
        self.assertEqual(len(rows), 15)
        self.assertEqual(Counter((r["task"], r["group"]) for r in rows),
                         Counter({(task, group): 3 if task == "heat" else 1 for task in TASKS for group in run_plan.GROUPS}))
        self.assertEqual({(r["task"], r["group"]) for r in rows[:9]}, {(t, g) for t in TASKS for g in run_plan.GROUPS})
        self.assertTrue(all(r["task"] == "heat" for r in rows[9:]))
        for key in ("run_id", "session_id", "workdir"):
            self.assertEqual(len({r[key] for r in rows}), 15)
        for row in rows:
            self.assertEqual((row["research_seconds"], row["max_evaluations"], row["solver_seed"], row["resume"]), (1800, 20, 0, False))
            self.assertFalse((self.project / row["workdir"]).exists())

    def test_draft_missing_status_and_status_only_cannot_start(self):
        self.blocked(self.draft, "draft cannot start")
        missing = copy.deepcopy(self.draft)
        del missing["status"]
        self.blocked(missing, "status=frozen")
        missing.update(status="frozen", formal_ready=True)
        self.blocked(missing, "unresolved")

    def test_complete_synthetic_freeze_fixture_is_accepted(self):
        fixture = self.fixture()
        self.assertIs(run_plan.validate_start(fixture, self.project), fixture)
        self.assertEqual(read_json(self.project / "tasks/package-manifest.json")["status"], "prepared_not_frozen")

    def test_null_model_parameters_and_unverified_enforcement_block(self):
        complete = self.fixture()
        for key in run_plan.PARAMETERS:
            for target in ("value", "enforcement"):
                plan = copy.deepcopy(complete)
                if target == "value":
                    plan["model"][key] = None
                else:
                    plan["model"]["enforcement"][key] = None
                with self.subTest(key=key, target=target):
                    self.blocked(plan, key)
        complete["model"]["output_token_limit"] = True
        self.blocked(complete, "output_token_limit")

    def test_verified_unsupported_temperature_and_unavailable_version(self):
        plan = self.fixture()
        plan["model"]["temperature"] = None
        plan["model"]["enforcement"]["temperature"].update(status="unsupported", reason="Synthetic endpoint does not implement this parameter.")
        plan["model"]["model_version"] = None
        plan["model"]["version_resolution"].update(status="unavailable_verified", reason="Synthetic endpoint reports only its fixed model ID.")
        for task in TASKS:
            path = self.project / plan["freezes"][task]["path"]
            value = read_json(path)
            value["research"].update(temperature=None, model_version=None,
                                      model_parameter_enforcement=plan["model"]["enforcement"],
                                      model_version_resolution=plan["model"]["version_resolution"])
            write_json(path, value)
            plan["freezes"][task] = self.ref(path)
        self.assertIs(run_plan.validate_start(plan, self.project), plan)
        draft = copy.deepcopy(plan)
        draft["status"] = "draft"
        self.blocked(draft, "draft cannot start")
        for change, phrase in ((lambda p: p["model"]["enforcement"]["temperature"].update(evidence=None), "temperature enforcement"),
                               (lambda p: p["model"]["enforcement"]["temperature"].update(reason=""), "requires a reason"),
                               (lambda p: p["model"].update(version_resolution=None), "version is unresolved"),
                               (lambda p: p["model"].pop("temperature"), "temperature is unresolved"),
                               (lambda p: p["model"].pop("model_version"), "model_version must be explicitly recorded")):
            changed = copy.deepcopy(plan)
            change(changed)
            self.blocked(changed, phrase)

    def test_research_image_id_inspection_and_context_must_match(self):
        plan = self.fixture()
        for change in (lambda p: p["research_images"].update(heat=None),
                       lambda p: p["research_images"]["heat"].update(image_id="mutable:latest"),
                       lambda p: p["research_images"]["heat"].update(image_id="sha256:" + "e" * 64),
                       lambda p: p["research_images"]["heat"].update(build_context_sha256="0" * 64),
                       lambda p: p["research_images"]["heat"]["inspection"].update(sha256="0" * 64)):
            changed = copy.deepcopy(plan)
            change(changed)
            self.blocked(changed, "heat research image")

    def test_missing_or_mismatched_acceptance_evidence_blocks(self):
        plan = self.fixture()
        plan["acceptance_evidence"]["heat"]["resources"] = None
        self.blocked(plan, "heat freeze")
        plan = self.fixture()
        another = self.project / "different-evidence.txt"
        another.write_text("Different synthetic evidence\n")
        plan["acceptance_evidence"]["poisson"]["timing_profile"] = self.ref(another)
        self.blocked(plan, "timing_profile acceptance evidence differs")

    def test_missing_draft_changed_or_mismatched_freeze_blocks(self):
        for task in TASKS:
            plan = self.fixture()
            plan["freezes"][task] = None
            self.blocked(plan, task + " freeze")
        for change in (lambda v: v.update(status="draft"), lambda v: v["research"].update(temperature=1)):
            plan = self.fixture()
            path = self.project / plan["freezes"]["heat"]["path"]
            value = read_json(path)
            change(value)
            write_json(path, value)
            plan["freezes"]["heat"] = self.ref(path)
            self.blocked(plan, "heat freeze")
        plan = self.fixture()
        (self.project / plan["freezes"]["ode"]["path"]).write_text("changed")
        self.blocked(plan, "changed evidence")

    def test_budget_seed_resume_and_identity_changes_block(self):
        original = self.fixture()
        for mutation in (lambda p: p["runs"][0].update(research_seconds=60),
                         lambda p: p["runs"][0].update(max_evaluations=1),
                         lambda p: p["runs"][0].update(solver_seed=1),
                         lambda p: p["runs"][0].update(resume=True),
                         lambda p: p["runs"][0].update(session_id=p["runs"][1]["session_id"]),
                         lambda p: p["resources"].update(research_vcpu=2),
                         lambda p: p["model"].update(model_id="another-model")):
            plan = copy.deepcopy(original)
            mutation(plan)
            with self.assertRaises(run_plan.RunPlanError):
                run_plan.validate_start(plan, self.project)

    def test_prompt_contract_tool_and_evidence_changes_block(self):
        original = self.fixture()
        for name in ("prompts/heat/g1.md", "tasks/ode/contract.json", run_plan.TOOL_FILES[0], "evidence.txt"):
            path = self.project / name
            content = path.read_bytes()
            try:
                path.write_bytes(content + b" ")
                with self.subTest(path=name), self.assertRaises(run_plan.RunPlanError):
                    run_plan.validate_start(original, self.project)
            finally:
                path.write_bytes(content)
        original["tool_config"]["runtime_tools"] = None
        original["tool_config_sha256"] = digest(canonical(original["tool_config"]))
        self.blocked(original, "tool inventory is unresolved")

    def test_public_draft_has_exact_prompt_combination_and_no_private_data(self):
        for task in TASKS:
            for group in run_plan.GROUPS:
                prompt_dir = self.project / "prompts" / task
                combined = (prompt_dir / "common.md").read_bytes() + b"\n\n" + (prompt_dir / (group + ".md")).read_bytes()
                self.assertEqual(self.draft["tasks"][task]["combined_prompt_hashes"][group], digest(combined))
        self.assertIsNone(self.draft["system_prompt"])
        self.assertEqual(self.draft["freezes"], {task: None for task in TASKS})


class PublicTaskPackageTests(unittest.TestCase):
    def test_three_packages_have_six_dev_cases_and_exact_public_allowlist(self):
        package_manifest = read_json(ROOT / "tasks/package-manifest.json")
        self.assertEqual(set(package_manifest["tasks"]), set(TASKS))
        for task in TASKS:
            with self.subTest(task=task):
                package = ROOT / "tasks" / task
                public_dev = package / "environment/public-dev"
                manifest = phase.validate_manifest(task, public_dev, expected_split="public-dev")
                self.assertEqual(len(manifest["cases"]), 6)
                self.assertEqual(Counter(row["level"] for row in manifest["cases"]), {0: 2, 1: 2, 2: 2})
                expected = {"manifest.json"}
                for row in manifest["cases"]:
                    expected.update(f"{row['path']}/{name}" for name in INPUTS[task])
                self.assertEqual(set(phase.checked_hashes(public_dev)), expected)
                actual_environment = phase.checked_hashes(package / "environment")
                helpers = {f"helpers/{name}" for name in ("file_bench.py", "bridge_io.py", "export_source.py")}
                trusted = {f"trusted/runner/{name}" for name in ("__init__.py", "artifact_gate.py", "common.py")}
                comparator = {"public/poisson_compare.py"} if task == "poisson" else set()
                self.assertEqual(set(actual_environment), {"Dockerfile", "public/bench", f"public/{task}.py"}
                                 | helpers | trusted | comparator | {"public-dev/" + path for path in expected})
                self.assertEqual(actual_environment, package_manifest["tasks"][task]["build_context_hashes"])
                self.assertEqual(phase.checked_hashes(public_dev), package_manifest["tasks"][task]["public_input_hashes"])
                package_files = set(phase.checked_hashes(package))
                self.assertEqual(package_files, {"README.md", "instruction.md", "contract.json", "task.toml", "tests/test.sh"}
                                 | {"environment/" + name for name in actual_environment})
                self.assertFalse(any(part in {"authoring", "private", "truth", "GT", "judge", "baselines"}
                                     for name in package_files for part in Path(name).parts))
                self.assertEqual((package / "instruction.md").read_bytes(), (ROOT / "prompts" / task / "common.md").read_bytes())
                copies = {f"public/{task}.py": f"public/{task}.py",
                          **{name: "public/" + Path(name).name for name in helpers},
                          **{name: "runner/" + Path(name).name for name in trusted},
                          **{name: name for name in comparator}}
                for destination, source in copies.items():
                    self.assertEqual(file_hash(package / "environment" / destination), file_hash(ROOT / source))

    def test_real_harbor_taskconfig_parses_and_declares_contract_resources(self):
        for task in TASKS:
            path = ROOT / "tasks" / task / "task.toml"
            value = tomllib.loads(path.read_text())
            config = TaskConfig.model_validate(value)
            self.assertEqual(config.task.name, "sciresearch-lite/" + task)
            self.assertEqual(value["agent"]["timeout_sec"], 1800)
            self.assertEqual(value["agent"]["network_mode"], "allowlist")
            self.assertEqual(value["agent"]["allowed_hosts"], ["api.deepseek.com"])
            self.assertEqual(value["environment"]["cpus"], 4)
            self.assertEqual(value["environment"]["memory_mb"], 4096)
            self.assertEqual(value["environment"]["mcp_servers"], [])
            self.assertEqual(value["verifier"]["environment_mode"], "separate")
            self.assertEqual(value["verifier"]["network_mode"], "no-network")
            self.assertEqual(value["artifacts"], [{"source": "/logs/artifacts", "exclude": ["*", "**/*"]}])
            contract = read_json(path.with_name("contract.json"))
            self.assertEqual((contract["research_seconds"], contract["max_registered_evaluations"]), (1800, 20))
            self.assertEqual(contract["entrypoint"], "python solve.py --input /input --output /output --seed 0")

    def test_default_verifier_intentionally_fails_and_produces_no_reward(self):
        for task in TASKS:
            with tempfile.TemporaryDirectory() as directory:
                script = ROOT / "tasks" / task / "tests/test.sh"
                result = subprocess.run(["/bin/sh", str(script)], cwd=directory, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertIn("default verification is disabled", result.stderr)
                self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
