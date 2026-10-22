"""Synthetic host admission only: these fixtures do not certify local hardware."""
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

from runner.common import canonical,digest,file_hash,write_json
from runner.phase import RESOURCES
from runner.performance import ACCURACY_PROFILE,EFFICIENCY_PROFILE,calibrate_profile,summarize_group
from runner.timing_host import TimingLease
from tests.test_performance import fixture


class TimingHostTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.image="sha256:"+"a"*64
        self.cpu=4
        self.running=""
        self.samples=fixture()["samples"]
        self.events=[row["worker"]["container_id"] for row in self.samples]
        timer=Path(__file__).resolve().parents[1]/"runner/process_timer.py"
        for row in self.samples:
            row["worker"].update(image=self.image,timer_source_sha256=file_hash(timer),source_hash=row["source_hash"],
                resource_contract_sha256=digest(canonical(RESOURCES)),resource_limits_verified=True,
                timing_complete=True,formal_timing=False,attempt_status="completed")
        resource={"status":"passed","formal_resources_accepted":True,"resources":RESOURCES,"machine_id":"test-machine"}
        exclusive={"status":"passed","machine_exclusive_verified":True,"machine_id":"test-machine",
                   "other_host_workloads":[],"cache_state":"synthetic unmodified cache",
                   "measurement_window_unix":[time.time()-60,time.time()+3600]}
        write_json(self.root/"resources.json",resource)
        write_json(self.root/"exclusive.json",exclusive)
        self.contract={"status":"frozen","resources":RESOURCES,"image_id":self.image,
            "resource_evidence":{"path":"resources.json","sha256":file_hash(self.root/"resources.json")},
            "exclusivity_evidence":{"path":"exclusive.json","sha256":file_hash(self.root/"exclusive.json")}}
        write_json(self.root/"contract.json",self.contract)

    def execute(self,*args):
        if args[0]=="info":
            output=json.dumps({"NCPU":self.cpu,"MemTotal":8*1024**3,"CgroupVersion":"2","SwapLimit":True})
        elif args[0]=="ps": output=self.running
        else: output="\n".join(json.dumps({"Actor":{"ID":identifier}}) for identifier in self.events)
        return SimpleNamespace(stdout=output)

    def lease(self):
        return TimingLease(self.root/"contract.json",execute=self.execute,lock_path=self.root/"measurement.lock")

    def test_live_qualified_records_are_new_and_raw_worker_evidence_stays_diagnostic(self):
        with self.lease() as lease:
            output=lease.qualify(self.samples)
            summary=summarize_group(output,evidence=lease.evidence,profile=EFFICIENCY_PROFILE)
        self.assertEqual(summary["reward"],1)
        self.assertTrue(summary["formal_evidence_valid"])
        self.assertTrue(all(not row["worker"]["formal_timing"] for row in self.samples))

    def test_draft_resource_shortfall_other_workload_and_changed_evidence_refused(self):
        self.contract["status"]="draft"
        write_json(self.root/"contract.json",self.contract)
        with self.assertRaises(ValueError):
            with self.lease(): pass
        self.contract["status"]="frozen"
        write_json(self.root/"contract.json",self.contract)
        for cpu,running in ((2,""),(4,"unrelated-service")):
            self.cpu,self.running=cpu,running
            with self.assertRaises(ValueError):
                with self.lease(): pass
        self.cpu,self.running=4,""
        with self.lease() as lease:
            (self.root/"resources.json").write_text("{}")
            with self.assertRaises(ValueError): lease.qualify(self.samples)

    def test_empty_events_historical_samples_or_unrelated_starts_cannot_qualify(self):
        for events in ([],self.events[:-1],self.events+["other-container"],self.events+[self.events[0]]):
            with self.subTest(events=events),self.lease() as lease:
                saved=self.events
                self.events=events
                with self.assertRaises(ValueError): lease.qualify(self.samples)
                self.events=saved

    def test_bad_identity_or_timer_hash_is_rejected(self):
        for changes in ({"machine_id":"another-boot"},{"timer_source_sha256":"bad"},{"source_hash":"changed"},{"timing_complete":False}):
            rows=copy.deepcopy(self.samples)
            rows[1]["worker"].update(changes)
            with self.lease() as lease,self.assertRaises(ValueError): lease.qualify(rows)

    def test_timeout_without_interval_remains_candidate_zero_under_valid_lease(self):
        row=self.samples[1]
        row.update(attempt_status="timeout",scientific_pass=False,artifact_valid=False)
        row["worker"].update(attempt_status="timeout",timing_complete=False,execution_wall_seconds=None)
        row["worker"].pop("started_monotonic_ns")
        row["worker"].pop("finished_monotonic_ns")
        with self.lease() as lease:
            output=lease.qualify(self.samples)
            result=summarize_group(output,evidence=lease.evidence,profile=EFFICIENCY_PROFILE)
        self.assertEqual(result["evaluation_status"],"valid")
        self.assertEqual(result["reward"],0)
        self.assertTrue(result["formal_evidence_valid"])

    def test_same_host_lease_cannot_run_concurrently_or_after_release(self):
        with self.lease() as first:
            with self.assertRaises(BlockingIOError):
                with self.lease(): pass
        with self.assertRaises(ValueError): first.qualify(self.samples)

    def test_baseline_timeout_keeps_accuracy_reward_and_calibration_fallback(self):
        row=self.samples[0]
        row.update(attempt_status="timeout",scientific_pass=False,artifact_valid=False)
        row["worker"].update(attempt_status="timeout",timing_complete=False,execution_wall_seconds=None)
        row["worker"].pop("started_monotonic_ns")
        row["worker"].pop("finished_monotonic_ns")
        with self.lease() as lease:
            output=lease.qualify(self.samples)
            self.assertEqual(summarize_group(output,evidence=lease.evidence,profile=ACCURACY_PROFILE)["reward"],1)
            self.assertIsNone(summarize_group(output,evidence=lease.evidence,profile=EFFICIENCY_PROFILE)["reward"])
            attempt={"attempt_id":"synthetic","baseline_method":"jacobi","candidate_method":"lu", "samples":output,"evidence":lease.evidence}
            calibrated=calibrate_profile([[attempt],[attempt],[attempt]])
        self.assertEqual(calibrated["profile"],ACCURACY_PROFILE)
        self.assertTrue(calibrated["formal_profile_ready"])


if __name__=="__main__": unittest.main()
