"""Synthetic baseline ledger tests; never run a solver or read real final data."""
import copy
import unittest

from runner.calibrate import FIXED, METHODS
from runner.common import canonical, digest, file_hash, read_json
import test_study_report as report_fixtures


class BaselineReportTests(unittest.TestCase):
    setUp = report_fixtures.StudyReportTests.setUp
    ref = report_fixtures.StudyReportTests.ref
    save = report_fixtures.StudyReportTests.save
    add = report_fixtures.StudyReportTests.add
    export = report_fixtures.StudyReportTests.export
    rows = report_fixtures.StudyReportTests.rows

    def close_task(self, task):
        existing = {row["run_id"] for row in self.manifest["attempts"]}
        for run in self.plan["runs"]:
            if run["task"] == task and run["run_id"] not in existing:
                self.add(task=task, group=run["group"], repeat=run["repeat"], scored=False)

    def baseline(self, task="heat", method=None, score=60., invalid=False, parent=None):
        method = method or FIXED[task]
        entries = self.manifest.setdefault("baselines", [])
        number = 1 + sum(row["task"] == task and row["method"] == method for row in entries)
        identifier = f"baseline-{task}-{method}-a{number:03d}"
        checkpoint = f"baseline-{task}-{method}"
        frozen = read_json(self.root / self.plan["freezes"][task]["path"])
        prefix = f"baselines/{task}/"
        files = {name.removeprefix(prefix): sha for name, sha in self.plan["tool_config"]["files"].items() if name.startswith(prefix)}
        source = digest(canonical(files))
        batch = {"phase": {"formal": True, "split": "final-test", "freeze_sha256": self.plan["freezes"][task]["sha256"], "profile": frozen["profile"]},
                 "task": task, "worker": {"image": frozen["image_id"], "source_hash": source},
                 "evaluation_status": "valid", "score": score if task != "poisson" else None, "reward": int(score >= 50),
                 "cases": [{"id": key, "score": score if task != "poisson" else None, "artifact_valid": True,
                            "scientific_pass": score >= 50, "E_init": 1 - score / 100} for key in self.ids]}
        if task == "poisson":
            samples = [dict(copy.deepcopy(batch), role=role) for role in "BCCBBC"]
            protocol = {"attempt_id": identifier + "-group", "candidate_method": method, "baseline_method": "jacobi", "samples": samples}
            repeats = [{"samples": {role: [row for row in samples if row["role"] == role] for role in ("B", "C")},
                        "protocol_attempt": protocol, "evaluation_status": "valid", "score": score, "reward": int(score >= 50)}]
        else:
            repeats = [copy.deepcopy(batch) for _ in range(3)]
        for repeated in repeats:
            repeated.update(checkpoint_id=checkpoint, source_hash=source)
        diagnostic = {"checkpoint_id": checkpoint, "source_hash": source, "repeats": [] if invalid else repeats,
                      "replay_count": 0 if invalid else len(repeats), "score": None if invalid else score,
                      "reward": None if invalid else int(score >= 50), "evaluation_status": "invalid" if invalid else "valid"}
        wrapper = {"schema_version": 1, "formal": True, "split": "final-test", "task": task, "method": method,
                   "attempt_id": identifier, "parent_attempt": parent, "retry_kind": "infrastructure" if parent else None,
                   "retry_reason": "trusted worker repaired" if parent else None, "interference_resolution": None,
                   "source_hash": source, "source_files": files, "freeze_sha256": self.plan["freezes"][task]["sha256"],
                   "run_plan_sha256": file_hash(self.plan_path), "image_id": frozen["image_id"], "profile": frozen["profile"],
                   "status": "baseline_invalid" if invalid else "baseline_completed", "diagnostics": diagnostic}
        entry = {"task": task, "method": method, "attempt_id": identifier, "parent_attempt": parent,
                 "result": self.save(self.root / "baseline-records" / (identifier + ".json"), wrapper)}
        entries.append(entry)
        return entry

    def edit(self, entry, change):
        path = self.root / entry["result"]["path"]
        value = read_json(path)
        change(value)
        entry["result"] = self.save(path, value)

    def test_all_eleven_methods_and_fixed_comparisons_do_not_add_sessions(self):
        self.add(first=20., final=80.)
        for task, methods in METHODS.items():
            self.close_task(task)
            for method in methods:
                self.baseline(task, method)
        summary = self.export()
        self.assertEqual((summary["scientific_sessions"], summary["scientific_guidance_cells"]), (1, 1))
        self.assertEqual((summary["attempts"], summary["baseline_attempts"]), (15, 11))
        self.assertEqual(len(self.rows("baseline-cases")), 11 * 36)
        self.assertEqual(len(summary["pending_baselines"]), 0)
        self.assertEqual({task: sum(row["task"] == task for row in self.rows("baselines")) for task in METHODS}, {"heat": 5, "ode": 3, "poisson": 3})
        row = next(row for row in self.rows("fixed-reference-runs") if row["comparison_status"] == "available")
        self.assertEqual((row["reference_method"], float(row["delta_score"]), float(row["delta_passed"])), ("tikhonov", 20., 0.))
        self.assertEqual(len(self.rows("fixed-reference-cases")), 12)
        self.assertEqual(float(self.rows("fixed-reference-cases")[0]["delta_score"]), 20.)
        group = next(row for row in summary["fixed_reference_groups"] if row["task"] == "heat" and row["group"] == "g1")
        self.assertEqual((group["planned_sessions"], group["compared_scientific_sessions"], group["score_n"]), (3, 1, 1))

    def test_missing_or_invalid_fixed_reference_keeps_null_comparisons(self):
        self.add()
        self.close_task("heat")
        self.baseline(invalid=True)
        self.baseline(method="ls")
        summary = self.export()
        self.assertEqual(len(summary["pending_baselines"]), 10)
        self.assertEqual(summary["scientific_sessions"], 1)
        self.assertTrue(all(row["delta_score"] == "null" for row in self.rows("fixed-reference-runs")))
        self.assertEqual(self.rows("fixed-reference-cases"), [])

    def test_reused_source_and_missing_submission_preserve_case_denominator(self):
        self.add(first=80., reuse=True)
        self.add(group="g2", no_submission=True)
        self.close_task("heat")
        self.baseline(score=0.)
        summary = self.export()
        self.assertEqual(summary["scientific_sessions"], 2)
        self.assertEqual(len(self.rows("fixed-reference-cases")), 24)
        g1 = next(row for row in self.rows("fixed-reference-runs") if row["group"] == "g1" and row["comparison_status"] == "available")
        self.assertEqual((float(g1["delta_score"]), float(g1["delta_passed"])), (80., 12.))

    def test_all_baseline_identity_drift_and_pilot_calibration_are_rejected(self):
        self.close_task("heat")
        entry = self.baseline()
        path = self.root / entry["result"]["path"]
        original = read_json(path)
        changes = ({"formal": False}, {"split": "author-calibration"}, {"split": "pilot-smoke"}, {"task": "ode"},
                   {"method": "ls"}, {"freeze_sha256": "f" * 64}, {"run_plan_sha256": "f" * 64},
                   {"image_id": "sha256:" + "f" * 64}, {"profile": "other"}, {"source_files": {}}, {"source_hash": "f" * 64})
        for change in changes:
            with self.subTest(change=change):
                entry["result"] = self.save(path, dict(original, **change))
                with self.assertRaisesRegex(ValueError, "baseline replay differs"):
                    self.export()

    def test_nested_batch_image_source_profile_and_t3_method_are_checked(self):
        self.close_task("poisson")
        entry = self.baseline("poisson")
        path = self.root / entry["result"]["path"]
        original = read_json(path)
        for key in ("image", "source_hash", "profile", "task", "method"):
            value = copy.deepcopy(original)
            repeated = value["diagnostics"]["repeats"][0]
            batch = repeated["samples"]["C"][0]
            if key in ("image", "source_hash"):
                batch["worker"][key] = "wrong"
            elif key == "profile":
                batch["phase"][key] = "wrong"
            elif key == "task":
                batch[key] = "heat"
            else:
                repeated["protocol_attempt"]["candidate_method"] = "cg"
            entry["result"] = self.save(path, value)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "baseline (batch|T3 protocol)"):
                self.export()

    def test_baseline_requires_all_task_research_closed(self):
        self.add()
        self.baseline()
        with self.assertRaisesRegex(ValueError, "all task research"):
            self.export()

    def test_infrastructure_retry_is_linked_and_retains_null_parent(self):
        self.close_task("heat")
        first = self.baseline(invalid=True)
        original = (self.root / first["result"]["path"]).read_bytes()
        self.baseline(score=0., parent=first["attempt_id"])
        summary = self.export()
        rows = self.rows("baseline-attempts")
        self.assertEqual((len(rows), rows[0]["score"], float(rows[1]["score"])), (2, "null", 0.))
        self.assertEqual(summary["scientific_sessions"], 0)
        self.assertEqual((self.root / first["result"]["path"]).read_bytes(), original)

    def test_valid_zero_cannot_be_replaced_or_unlinked(self):
        self.close_task("heat")
        first = self.baseline(score=0.)
        second = self.baseline(parent=first["attempt_id"])
        with self.assertRaisesRegex(ValueError, "including scientific zero"):
            self.export()
        second["parent_attempt"] = None
        self.edit(second, lambda row: row.update(parent_attempt=None))
        with self.assertRaisesRegex(ValueError, "latest attempt"):
            self.export()

    def test_hash_mismatch_duplicate_identity_and_invalid_numeric_verdict_rejected(self):
        self.close_task("heat")
        entry = self.baseline(invalid=True)
        reference = copy.deepcopy(entry["result"])
        entry["result"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.export()
        entry["result"] = reference
        self.edit(entry, lambda row: row["diagnostics"].update(score=0.))
        with self.assertRaisesRegex(ValueError, "null verdicts"):
            self.export()
        self.edit(entry, lambda row: row["diagnostics"].update(score=None))
        self.manifest["baselines"].append(copy.deepcopy(entry))
        with self.assertRaisesRegex(ValueError, "duplicate attempt"):
            self.export()

    def unstable_retry(self):
        self.close_task("poisson")
        original = self.baseline("poisson")
        def unstable(wrapper):
            wrapper["diagnostics"]["score"] = None
            wrapper["diagnostics"]["repeats"][0].update(score=None, performance_status="baseline_unstable", retry_permitted=True)
        self.edit(original, unstable)
        prior = read_json(self.root / original["result"]["path"])
        current = self.baseline("poisson", parent=original["attempt_id"], score=80.)
        def investigated(wrapper):
            reason = "Synthetic interference investigated and removed"
            wrapper.update(retry_kind="baseline_instability", retry_reason=reason, interference_resolution=reason)
            repeated = wrapper["diagnostics"]["repeats"][0]
            old = prior["diagnostics"]["repeats"][0]["protocol_attempt"]
            new = repeated["protocol_attempt"]
            new.update(parent_attempt=old["attempt_id"], interference_resolution=reason)
            repeated.update(attempts=[{"record": old}, {"record": new}], selected_attempt=1, retry_permitted=False)
        self.edit(current, investigated)
        return original, current

    def test_t3_investigated_retry_retains_both_attempts_without_research_credit(self):
        original, current = self.unstable_retry()
        before = (self.root / original["result"]["path"]).read_bytes()
        summary = self.export()
        self.assertEqual((summary["baseline_attempts"], summary["scientific_sessions"]), (2, 0))
        rows = self.rows("baseline-attempts")
        self.assertEqual((rows[0]["score"], float(rows[1]["score"])), ("null", 80.))
        selected = next(row for row in summary["baseline_methods"] if row["task"] == "poisson" and row["method"] == "lu")
        self.assertEqual(selected["attempt_id"], current["attempt_id"])
        self.assertEqual((self.root / original["result"]["path"]).read_bytes(), before)

    def test_t3_retry_requires_original_measurements_and_only_one_investigation(self):
        _, current = self.unstable_retry()
        path = self.root / current["result"]["path"]
        original = read_json(path)
        self.edit(current, lambda row: row["diagnostics"]["repeats"][0]["attempts"][0].update(record={"attempt_id": "foreign"}))
        with self.assertRaisesRegex(ValueError, "both linked"):
            self.export()
        current["result"] = self.save(path, original)
        def unstable(wrapper):
            wrapper["diagnostics"]["score"] = None
            wrapper["diagnostics"]["repeats"][0].update(score=None, performance_status="baseline_unstable")
        self.edit(current, unstable)
        third = self.baseline("poisson", parent=current["attempt_id"])
        self.edit(third, lambda row: row.update(retry_kind="baseline_instability", retry_reason="again", interference_resolution="again"))
        with self.assertRaisesRegex(ValueError, "only one investigated"):
            self.export()

    def test_running_attempt_is_preserved_unscored_and_cannot_be_retried(self):
        self.close_task("heat")
        first = self.baseline(invalid=True)
        self.edit(first, lambda row: row.update(status="baseline_running"))
        summary = self.export()
        row = next(row for row in summary["baseline_methods"] if row["task"] == "heat" and row["method"] == "tikhonov")
        self.assertEqual((row["status"], row["evaluation_status"], row["score"]), ("baseline_running", "not_run", None))
        self.baseline(parent=first["attempt_id"])
        with self.assertRaisesRegex(ValueError, "cannot be replaced"):
            self.export()

    def test_invalid_parent_cannot_be_relabelled_as_timing_instability(self):
        prior, _ = self.unstable_retry()
        def invalidate(wrapper):
            wrapper["status"] = "baseline_invalid"
            wrapper["diagnostics"].update(evaluation_status="invalid", score=None, reward=None)
        self.edit(prior, invalidate)
        with self.assertRaisesRegex(ValueError, "only one investigated"):
            self.export()


if __name__ == "__main__":
    unittest.main()
