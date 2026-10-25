"""Synthetic frozen evidence only; no solver, model, or real final-test read."""
import copy
import csv
import json
from pathlib import Path
import unittest

import test_run_plan as plan_fixtures
from runner.common import canonical, digest, file_hash, read_json, write_json
from runner.study_report import export_study, group_summary, post_first_costs, total_costs, validate_research_result


class StudyReportTests(unittest.TestCase):
    def setUp(self):
        fixture = plan_fixtures.RunPlanTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.plan = fixture.project, fixture.fixture()
        self.ids = [f"fixture-{index:02d}" for index in range(12)]
        for task, ref in self.plan["freezes"].items():
            path = self.root / ref["path"]
            value = read_json(path)
            value["data"]["final-test"]["input_hashes"].update({f"cases/{identifier}/metadata.json": "1" * 64 for identifier in self.ids})
            value["data_sha256"] = digest(canonical(value["data"]))
            write_json(path, value)
            self.plan["freezes"][task] = self.ref(path)
        self.plan_path = self.root / "frozen-plan.json"
        write_json(self.plan_path, self.plan)
        self.manifest = {"schema_version": 1, "run_plan": self.ref(self.plan_path), "attempts": []}

    def ref(self, path):
        return {"path": path.relative_to(self.root).as_posix(), "sha256": file_hash(path)}

    def save(self, path, value):
        write_json(path, value)
        return self.ref(path)

    def add(self, task="heat", group="g1", repeat=1, *, first=20., final=80., status="completed",
            scored=True, no_submission=False, reuse=False, parent=None):
        run = next(row for row in self.plan["runs"] if (row["task"], row["group"], row["repeat"]) == (task, group, repeat))
        attempt_id = run["run_id"] + "-attempt-" + str(len(self.manifest["attempts"]) + 1)
        directory = self.root / "logs" / attempt_id
        first_id, final_id = (None, None) if no_submission else ("candidate-001", "candidate-001" if reuse else "candidate-002")
        evaluations = [] if no_submission else [{"id": "candidate-001", "artifact_valid": True, "source_hash": "a" * 64,
                                                "accepted_at": 10., "completed_at": 20., "result": {"cpu_seconds": 1.}}]
        if not no_submission and not reuse:
            evaluations.append({"id": "candidate-002", "artifact_valid": True, "source_hash": "b" * 64,
                                "accepted_at": 30., "completed_at": 40., "result": {"cpu_seconds": 2.}})
        registry = {"task": task, "condition": group, "closed": True, "attempt_status": status,
                    "attempt_outcome": {"status": status, "reason": "synthetic test"}, "evaluations": evaluations,
                    "first_id": first_id, "final_id": final_id, "selection_reason": "no_valid_submission" if no_submission else "explicit_finalize"}
        result = {"formal": True, "replay_split": None, "study_phase": "public-dev", "evaluation_status": "not_run",
                  "status": "research_frozen", "run_id": run["run_id"], "task": task, "group": group,
                  "attempt_status": status, "research_stop_requested_at": 50., "auxiliary_usage": {"tokens": 999999},
                  "cost_usd": 0, "relay_status": {"request_count": 0, "inflight": 0, "evidence_error": False}}
        entry = {"run_id": run["run_id"], "attempt_id": attempt_id, "parent_attempt": parent,
                 "result": self.save(directory / "result.json", result), "registry": self.save(directory / "registry/state.json", registry),
                 "replay": None, "relay_events": None}
        if scored:
            freeze_sha = self.plan["freezes"][task]["sha256"]
            def checkpoint(identifier, source, score):
                if identifier is None:
                    return {"checkpoint_id": None, "replay_count": 0, "score": 0., "reward": 0}
                batch = {"phase": {"formal": True, "split": "final-test", "freeze_sha256": freeze_sha},
                         "evaluation_status": "valid", "score": score if task != "poisson" else None,
                         "reward": int(score >= 50), "scientific_pass": score >= 50,
                         "cases": [{"id": key, "level": index // 4, "score": score if task != "poisson" else None,
                                    "artifact_valid": True, "scientific_pass": score >= 50, "E_init": 1. - score / 100}
                                   for index, key in enumerate(self.ids)]}
                if task == "poisson":
                    repeated = [{"samples": {"B": [copy.deepcopy(batch) for _ in range(3)], "C": [copy.deepcopy(batch) for _ in range(3)]},
                                 "evaluation_status": "valid", "score": score, "reward": int(score >= 50)}]
                else:
                    repeated = [copy.deepcopy(batch) for _ in range(3)]
                for item in repeated:
                    item.update(checkpoint_id=identifier, source_hash=source)
                return {"checkpoint_id": identifier, "source_hash": source, "score": score, "reward": int(score >= 50),
                        "replay_count": len(repeated), "repeats": repeated, "evaluation_status": "valid"}
            a = checkpoint(first_id, "a" * 64, first)
            b = dict(a, replay_count=0, reused_from=first_id) if reuse else checkpoint(final_id, "b" * 64, final)
            diagnostic = {"first": a, "final": b, "evaluation_status": "valid", "score": b["score"], "reward": b["reward"]}
            replay = {"formal": True, "split": "final-test", "freeze_sha256": freeze_sha,
                      "registry_sha256": entry["registry"]["sha256"], "diagnostics": diagnostic}
            entry["replay"] = self.save(directory / "replay.json", replay)
        self.manifest["attempts"].append(entry)
        return entry

    def export(self):
        path = self.root / "manifest.json"
        write_json(path, self.manifest)
        return export_study(self.root, self.plan_path, path, self.root / "report")

    def rows(self, name):
        with (self.root / "report" / (name + ".csv")).open() as stream:
            return list(csv.DictReader(stream))

    def add_t3_retry(self):
        entry = self.add(task="poisson", first=50., final=80.)
        original_path = self.root / entry["replay"]["path"]
        original = read_json(original_path)
        original.update(run_id=entry["run_id"], attempt_id=entry["attempt_id"], replay_retry_number=0)
        prior = original["diagnostics"]["final"]
        prior["score"] = original["diagnostics"]["score"] = None
        group = prior["repeats"][0]
        group.update(score=None, performance_status="baseline_unstable", retry_permitted=True)
        old_protocol = {"attempt_id": "original-group", "samples": copy.deepcopy(group["samples"])}
        group["protocol_attempt"] = old_protocol
        old_ref = self.save(original_path, original)
        retry = copy.deepcopy(original)
        retry.update(replay_retry_number=1, parent_replay=old_ref, interference_resolution="host load inspected and resolved")
        current = retry["diagnostics"]["final"]
        current.update(score=80., replay_retry=True)
        retry["diagnostics"]["score"] = 80.
        repeated = current["repeats"][0]
        new_protocol = {"attempt_id": "retry-group", "parent_attempt": "original-group",
                        "interference_resolution": retry["interference_resolution"], "samples": copy.deepcopy(repeated["samples"])}
        repeated.update(score=80., performance_status="valid", retry_permitted=False, selected_attempt=1,
                        protocol_attempt=new_protocol, attempts=[{"record": old_protocol}, {"record": new_protocol}])
        entry["replay_history"] = [old_ref]
        entry["replay"] = self.save(original_path.with_name("retry.json"), retry)
        return entry, original, retry

    def test_improvement_complete_denominator_and_cost_nulls(self):
        entry = self.add()
        original = {key: file_hash(self.root / entry[key]["path"]) for key in ("result", "registry", "replay")}
        summary = self.export()
        self.assertEqual(summary["scientific_sessions"], 1)
        self.assertEqual(summary["case_rows"], 72)
        row = self.rows("attempts")[0]
        self.assertEqual(float(row["delta_score"]), 60.)
        self.assertEqual(float(row["delta_passed"]), 12.)
        self.assertEqual(row["iteration_status"], "improved")
        self.assertEqual(row["after_first_wall_seconds"], "30.0")
        self.assertEqual(row["after_first_candidate_cpu_seconds"], "2.0")
        self.assertEqual(row["after_first_api_requests"], "null")
        self.assertEqual(row["cost_usd"], "null")
        self.assertEqual(len(self.rows("case-deltas")), 12)
        self.assertEqual(float(self.rows("case-deltas")[0]["delta_pass_rate"]), 1.)
        self.assertEqual({key: file_hash(self.root / entry[key]["path"]) for key in original}, original)

    def test_same_hash_reuse_does_not_duplicate_case_replays(self):
        self.add(first=80., reuse=True)
        summary = self.export()
        self.assertEqual(summary["case_rows"], 36)
        row = self.rows("attempts")[0]
        self.assertEqual(row["iteration_status"], "not_observed_same_source")
        self.assertEqual(row["final_replay_count"], "0")
        self.assertEqual(float(row["delta_score"]), 0.)

    def test_t3_evaluation_csv_exports_candidate_total(self):
        entry = self.add(task="poisson", scored=False)
        path = self.root / entry["registry"]["path"]
        registry = read_json(path)
        registry["evaluations"][0]["result"]["candidate_cpu_seconds_total"] = 3.
        registry["evaluations"][1]["result"]["candidate_cpu_seconds_total"] = None
        entry["registry"] = self.save(path, registry)
        self.export()
        self.assertEqual([row["cpu_seconds"] for row in self.rows("public-evaluations")], ["3.0", "null"])
        self.assertEqual(self.rows("attempts")[0]["total_candidate_cpu_seconds"], "null")

    def test_no_submission_is_scientific_zero_without_invented_checkpoint(self):
        self.add(no_submission=True)
        summary = self.export()
        row = self.rows("attempts")[0]
        self.assertEqual(summary["scientific_sessions"], 1)
        self.assertEqual(row["first_id"], "null")
        self.assertEqual(row["final_id"], "null")
        self.assertEqual(row["delta_score"], "null")
        self.assertEqual(float(row["final_score"]), 0.)
        self.assertEqual(summary["case_rows"], 12)
        self.assertTrue(all(row["repeat"] == "0" and row["observed"] == "false" for row in self.rows("cases")))

    def test_linked_api_retry_preserves_failed_attempt_but_not_scientific_denominator(self):
        failed = self.add(status="api_failed", scored=False)
        self.add(first=0., final=0., parent=failed["attempt_id"])
        summary = self.export()
        group = next(row for row in summary["groups"] if row["task"] == "heat" and row["group"] == "g1")
        self.assertEqual((summary["attempts"], summary["scientific_sessions"]), (2, 1))
        self.assertEqual(group["non_scientific_attempts"], 1)
        self.assertEqual(group["score_zero_sessions"], 1)
        self.assertEqual(self.rows("attempts")[0]["final_score"], "null")

    def test_post_registry_host_failure_keeps_registry_and_allows_linked_retry(self):
        failed = self.add(scored=False)
        registry_path = self.root / failed["registry"]["path"]
        original = registry_path.read_bytes()
        path = self.root / failed["result"]["path"]
        result = read_json(path)
        result.update(attempt_status="infrastructure_failed", status="research_invalid", post_registry_failure=True,
                      registry_attempt_status="completed", reason="relay cleanup failed after registration")
        failed["result"] = self.save(path, result)
        self.add(first=0., final=0., parent=failed["attempt_id"])
        summary = self.export()
        self.assertEqual((summary["attempts"], summary["scientific_sessions"]), (2, 1))
        row = self.rows("attempts")[0]
        self.assertEqual(row["registry_attempt_status"], "completed")
        self.assertEqual(row["post_registry_failure"], "true")
        self.assertEqual(row["research_valid"], "false")
        self.assertEqual(row["final_score"], "null")
        self.assertEqual(row["failure_reason"], result["reason"])
        self.assertEqual(registry_path.read_bytes(), original)

    def test_post_registry_failure_requires_the_exact_explicit_exception(self):
        entry = self.add(scored=False)
        path = self.root / entry["result"]["path"]
        original = read_json(path)
        valid = dict(original, attempt_status="infrastructure_failed", status="research_invalid", post_registry_failure=True,
                     registry_attempt_status="completed", reason="cleanup failed after registration")
        changes = ({"post_registry_failure": False}, {"post_registry_failure": 1},
                   {"registry_attempt_status": "research_timeout"}, {"registry_attempt_status": None},
                   {"attempt_status": "api_failed"}, {"attempt_status": "completed"},
                   {"status": "research_frozen"}, {"reason": " "}, {"reason": None})
        for change in changes:
            with self.subTest(change=change):
                entry["result"] = self.save(path, dict(valid, **change))
                with self.assertRaisesRegex(ValueError, "registry is open or differs"):
                    self.export()
        entry["result"] = self.save(path, valid)
        registry_path = self.root / entry["registry"]["path"]
        registry = read_json(registry_path)
        registry["attempt_outcome"]["status"] = "infrastructure_failed"
        entry["registry"] = self.save(registry_path, registry)
        with self.assertRaisesRegex(ValueError, "registry is open or differs"):
            self.export()

    def test_retry_cannot_replace_zero_or_omit_link(self):
        first = self.add(first=0., final=0.)
        self.add(parent=first["attempt_id"])
        with self.assertRaisesRegex(ValueError, "cannot be replaced"):
            self.export()
        self.manifest["attempts"][1]["parent_attempt"] = None
        with self.assertRaisesRegex(ValueError, "retries must link"):
            self.export()

    def test_research_only_and_trusted_scoring_failure_remain_unscored(self):
        self.add(scored=False)
        second = self.add(group="g2")
        path = self.root / second["replay"]["path"]
        replay = read_json(path)
        replay["diagnostics"] = {"evaluation_status": "invalid", "score": None, "reward": None,
                                 "first": None, "final": None, "reason": "trusted judge failed"}
        second["replay"] = self.save(path, replay)
        summary = self.export()
        self.assertEqual(summary["scientific_sessions"], 0)
        self.assertEqual(self.rows("attempts")[0]["evaluation_status"], "not_run")
        self.assertTrue(all(row["final_score"] == "null" for row in self.rows("attempts")))
        self.assertEqual(len(self.rows("checkpoints")), 2)

    def test_t3_uses_one_outer_replay_and_three_internal_candidate_batches(self):
        self.add(task="poisson", first=50., reuse=True)
        summary = self.export()
        self.assertEqual(summary["case_rows"], 36)
        self.assertEqual(self.rows("attempts")[0]["first_replay_count"], "1")

    def test_t3_linked_retry_preserves_original_and_one_session_denominator(self):
        entry, _, _ = self.add_t3_retry()
        original_path = self.root / entry["replay_history"][0]["path"]
        original_bytes = original_path.read_bytes()
        summary = self.export()
        self.assertEqual((summary["attempts"], summary["scientific_sessions"], summary["case_rows"]), (1, 1, 72))
        self.assertEqual(self.rows("attempts")[0]["final_score"], "80.0")
        self.assertEqual(json.loads(self.rows("attempts")[0]["replay_history_evidence"]), entry["replay_history"])
        self.assertEqual(original_path.read_bytes(), original_bytes)

    def test_t3_retry_history_and_eligibility_cannot_be_forged(self):
        entry, original, retry = self.add_t3_retry()
        original_path = self.root / entry["replay_history"][0]["path"]
        retry_path = self.root / entry["replay"]["path"]
        changes = (
            lambda old, new, index: new.update(replay_retry_number=2),
            lambda old, new, index: new.update(interference_resolution=" "),
            lambda old, new, index: new.update(parent_replay=None),
            lambda old, new, index: index.update(replay_history=[]),
            lambda old, new, index: index["replay_history"].append(index["replay_history"][0]),
            lambda old, new, index: old.update(freeze_sha256="f" * 64),
            lambda old, new, index: old["diagnostics"]["final"]["repeats"][0].update(retry_permitted=False),
            lambda old, new, index: new["diagnostics"]["final"].update(source_hash="f" * 64),
            lambda old, new, index: new["diagnostics"]["first"].update(score=99.),
            lambda old, new, index: new["diagnostics"]["final"]["repeats"][0]["protocol_attempt"].update(parent_attempt="foreign"),
        )
        for number, change in enumerate(changes):
            with self.subTest(change=number):
                old, new, index = copy.deepcopy((original, retry, entry))
                change(old, new, index)
                old_ref = self.save(original_path, old)
                if index["replay_history"]:
                    index["replay_history"][0] = old_ref
                if new.get("parent_replay") is not None:
                    new["parent_replay"] = old_ref
                index["replay"] = self.save(retry_path, new)
                self.manifest["attempts"] = [index]
                with self.assertRaises(ValueError):
                    self.export()

    def test_t3_retry_host_failure_retains_history_without_scientific_credit(self):
        entry, _, retry = self.add_t3_retry()
        retry["diagnostics"] = {"evaluation_status": "invalid", "score": None, "reward": None,
                                "reason": "timing admission failed before remeasurement"}
        entry["replay"] = self.save(self.root / entry["replay"]["path"], retry)
        summary = self.export()
        self.assertEqual(summary["scientific_sessions"], 0)
        self.assertEqual(self.rows("attempts")[0]["final_score"], "null")

    def test_draft_pilot_open_registry_and_phase_hash_drift_refused(self):
        entry = self.add()
        path = self.root / entry["result"]["path"]
        value = read_json(path)
        value["formal"] = False
        entry["result"] = self.save(path, value)
        with self.assertRaisesRegex(ValueError, "pilot/nonformal"):
            self.export()
        value["formal"] = True
        entry["result"] = self.save(path, value)
        registry_path = self.root / entry["registry"]["path"]
        registry = read_json(registry_path)
        registry["closed"] = False
        entry["registry"] = self.save(registry_path, registry)
        with self.assertRaisesRegex(ValueError, "registry is open"):
            self.export()
        registry["closed"] = True
        entry["registry"] = self.save(registry_path, registry)
        replay_path = self.root / entry["replay"]["path"]
        replay = read_json(replay_path)
        replay["diagnostics"]["first"]["repeats"][0]["phase"]["split"] = "pilot-smoke"
        entry["replay"] = self.save(replay_path, replay)
        with self.assertRaisesRegex(ValueError, "replay phase"):
            self.export()
        self.plan["status"] = "draft"
        write_json(self.plan_path, self.plan)
        with self.assertRaisesRegex(ValueError, "draft cannot start"):
            self.export()

    def test_missing_case_still_has_denominator_and_cannot_keep_inflated_score(self):
        entry = self.add()
        path = self.root / entry["replay"]["path"]
        value = read_json(path)
        value["diagnostics"]["final"]["repeats"][0]["cases"].pop()
        entry["replay"] = self.save(path, value)
        with self.assertRaisesRegex(ValueError, "complete case denominator"):
            self.export()

    def test_candidate_timeout_retains_all_failed_cases_and_negative_delta(self):
        entry = self.add(first=20., final=0.)
        path = self.root / entry["replay"]["path"]
        value = read_json(path)
        for repeat in value["diagnostics"]["final"]["repeats"]:
            repeat.update(attempt_status="timeout", cases=[])
        entry["replay"] = self.save(path, value)
        summary = self.export()
        self.assertEqual(summary["scientific_sessions"], 1)
        row = self.rows("attempts")[0]
        self.assertEqual(row["iteration_status"], "degraded")
        self.assertEqual(float(row["delta_score"]), -20.)
        final_cases = [row for row in self.rows("cases") if row["checkpoint_role"] == "final"]
        self.assertEqual(len(final_cases), 36)
        self.assertTrue(all(row["score"] == "0.0" and row["observed"] == "false" for row in final_cases))

    def test_host_cleanup_failure_cannot_be_rescued_by_numeric_replay(self):
        entry = self.add()
        path = self.root / entry["result"]["path"]
        value = read_json(path)
        value.update(status="research_invalid", cleanup_errors={"worker": "failed"})
        entry["result"] = self.save(path, value)
        summary = self.export()
        self.assertEqual(summary["scientific_sessions"], 0)
        row = self.rows("attempts")[0]
        self.assertEqual(row["final_score"], "null")
        self.assertEqual(row["evaluation_status"], "invalid_research_attempt")

    def test_changed_reference_bytes_and_registered_source_mismatch_rejected(self):
        entry = self.add()
        path = self.root / entry["replay"]["path"]
        value = read_json(path)
        value["diagnostics"]["first"]["source_hash"] = "c" * 64
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, "changed evidence"):
            self.export()
        entry["replay"] = self.ref(path)
        with self.assertRaisesRegex(ValueError, "registered source"):
            self.export()

    def test_groups_compare_only_within_task_and_independent_repeat(self):
        attempts = []
        for task, count in (("heat", 3), ("ode", 1), ("poisson", 1)):
            for group, score in (("g1", 80.), ("g2", 50.), ("g3", 20.)):
                for repeat in range(1, count + 1):
                    attempts.append({"task": task, "group": group, "repeat": repeat, "scientific_evaluated": True,
                                     "attempt_status": "completed", "final_score": score, "final_reward": int(score > 50)})
        groups, comparisons = group_summary(self.plan, attempts)
        self.assertEqual(len(groups), 9)
        self.assertEqual(len(comparisons), 9)
        heat = next(row for row in comparisons if row["task"] == "heat" and row["contrast"] == "g1-g3")
        ode = next(row for row in comparisons if row["task"] == "ode" and row["contrast"] == "g1-g3")
        self.assertEqual((heat["paired_score_n"], ode["paired_score_n"]), (3, 1))
        self.assertEqual(heat["median_delta_score"], 60.)
        self.assertTrue(all("n=1" in row["interpretation"] for row in groups if row["task"] != "heat"))


class IncrementalCostTests(unittest.TestCase):
    def test_candidate_cpu_total_null_and_legacy(self):
        registry = {"first_id": "candidate-001", "evaluations": [
            {"id": "candidate-001", "accepted_at": 1., "completed_at": 10.,
             "result": {"cpu_seconds": 1., "candidate_cpu_seconds_total": 3.}},
            {"id": "candidate-002", "accepted_at": 20., "completed_at": 30.,
             "result": {"cpu_seconds": 2., "candidate_cpu_seconds_total": 6.}}]}
        result = {"research_stop_requested_at": 40.}
        self.assertEqual(post_first_costs(registry, result, None)["after_first_candidate_cpu_seconds"], 6.)
        self.assertEqual(total_costs(registry, result, None)["total_candidate_cpu_seconds"], 9.)
        registry["evaluations"][1]["result"]["candidate_cpu_seconds_total"] = None
        self.assertIsNone(post_first_costs(registry, result, None)["after_first_candidate_cpu_seconds"])
        self.assertIsNone(total_costs(registry, result, None)["total_candidate_cpu_seconds"])
        for row in registry["evaluations"]:
            del row["result"]["candidate_cpu_seconds_total"]
        self.assertEqual(post_first_costs(registry, result, None)["after_first_candidate_cpu_seconds"], 2.)
        self.assertEqual(total_costs(registry, result, None)["total_candidate_cpu_seconds"], 3.)

    def test_trusted_usage_only_and_boundary_overlap_null(self):
        registry = {"first_id": "candidate-001", "evaluations": [
            {"id": "candidate-001", "accepted_at": 1., "completed_at": 10., "result": {"cpu_seconds": 1.}},
            {"id": "candidate-002", "accepted_at": 20., "completed_at": 30., "result": {"cpu_seconds": 2.}}]}
        result = {"research_stop_requested_at": 40., "relay_status": {"request_count": 1, "inflight": 0, "evidence_error": False},
                  "auxiliary_usage": {"output_tokens": 99999}}
        events = [{"event": "request_accepted", "request_id": "one", "timestamp": 11.},
                  {"event": "request_finished", "request_id": "one", "timestamp": 15., "outcome": "success",
                   "output_usage_complete": True, "input_tokens": 20, "output_tokens": 3,
                   "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "charged_output_tokens": 3}]
        costs = post_first_costs(registry, result, events)
        self.assertEqual(costs["after_first_output_tokens"], 3)
        self.assertEqual(costs["after_first_candidate_cpu_seconds"], 2.)
        self.assertEqual(costs["after_first_api_requests"], 1)
        events[0]["timestamp"] = 9.
        costs = post_first_costs(registry, result, events)
        self.assertEqual(costs["after_first_api_requests"], 0)
        self.assertIsNone(costs["after_first_output_tokens"])
        events[0]["timestamp"] = 11.
        events[1].update(outcome="upstream_timeout", output_usage_complete=False, charged_output_tokens=4096, output_tokens=None)
        costs = post_first_costs(registry, result, events)
        self.assertIsNone(costs["after_first_output_tokens"])
        self.assertEqual(costs["after_first_charged_output_tokens"], 4096)
        total = total_costs(registry, result, events)
        self.assertEqual(total["total_api_requests"], 1)
        self.assertIsNone(total["total_output_tokens"])
        registry["evaluations"][1]["result"]["cpu_seconds"] = None
        self.assertIsNone(post_first_costs(registry, result, events)["after_first_candidate_cpu_seconds"])

    def test_native_pilot_can_never_be_relabelled_by_manifest(self):
        with self.assertRaisesRegex(ValueError, "pilot/nonformal"):
            validate_research_result({"formal": False, "replay_split": "pilot-smoke", "attempt_status": "completed"},
                                     {"run_id": "formal-run", "task": "heat", "group": "g1"})


if __name__ == "__main__":
    unittest.main()
