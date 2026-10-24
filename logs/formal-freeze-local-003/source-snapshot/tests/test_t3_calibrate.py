"""Mock execution verifies complete batches and retry accounting; no perf claim."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runner.common import VERSION,write_json
from runner.replay import retry_t3_attempt,run_t3_attempt
from runner.t3_calibrate import calibrate_t3
from tests.test_performance import fixture


class T3CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.project=self.root/"project"
        self.source=self.project/"baselines/poisson"
        self.source.mkdir(parents=True)
        (self.source/"solve.py").write_text("# never executed\n")
        self.data=self.root/"data"
        inputs=self.data/"inputs/poisson/author-calibration"
        cases=[]
        for level in range(3):
            for i in range(4):
                identifier=f"case-{level}-{i}"
                (inputs/"cases"/identifier).mkdir(parents=True)
                cases.append({"id":identifier,"path":"cases/"+identifier,"level":level})
        write_json(inputs/"manifest.json",{"task":"poisson","split":"author-calibration","contract_version":VERSION,"cases":cases})
        (self.data/"private/poisson/author-calibration").mkdir(parents=True)
        self.calls=[]

    def execute(self,source,**kwargs):
        self.calls.append((source,kwargs))
        index=(len(self.calls)-1)%6
        row=fixture()["samples"][index]
        row["worker"].update(formal_timing=False)
        return row

    def test_three_full_groups_are_eighteen_fresh_batches_without_profile_promotion(self):
        result=calibrate_t3(self.project,self.data,self.root/"result","synthetic-image",execute=self.execute,judge_source_root=self.root)
        self.assertEqual(len(self.calls),18)
        self.assertEqual([kwargs["method"] for _,kwargs in self.calls], ["jacobi","lu","lu","jacobi","jacobi","lu"]*3)
        self.assertEqual(len({kwargs["output_root"] for _,kwargs in self.calls}),18)
        self.assertIsNone(result["profile"])
        self.assertFalse(result["formal_profile_ready"])
        self.assertFalse(result["final_test_scores_accessed"])

    def test_trusted_judge_failure_stays_invalid(self):
        def invalid(*args,**kwargs):
            row=self.execute(*args,**kwargs)
            row.update(evaluation_status="evaluation_invalid",scientific_pass=False)
            return row
        result=run_t3_attempt(self.source,baseline_source=self.source,output_root=self.root/"invalid",task="poisson",execute=invalid)
        self.assertEqual(result["evaluation_status"],"evaluation_invalid")
        self.assertIsNone(result["reward"])

    def test_candidate_timeout_and_bad_host_qualification_remain_distinct(self):
        class Lease:
            def __init__(self,bad): self.bad=bad; self.evidence=fixture()["evidence"]
            def __enter__(self): return self
            def __exit__(self,*unused): pass
            def qualify(self,rows):
                if self.bad: raise ValueError("synthetic host contract drift")
                for row in rows:
                    row["worker"]["formal_timing"]=True
                    if row.get("attempt_status")=="timeout":
                        row["worker"].update(formal_timing=False,failure_in_qualified_environment=True)
                return rows
        def execute(*args,**kwargs):
            row=self.execute(*args,**kwargs)
            if (len(self.calls)-1)%6==1:
                row.update(attempt_status="timeout",scientific_pass=False,artifact_valid=False)
                row["worker"].update(attempt_status="timeout",execution_wall_seconds=None)
            return row
        for bad in (False,True):
            with patch("runner.replay.TimingLease",return_value=Lease(bad)):
                result=run_t3_attempt(self.source,baseline_source=self.source,output_root=self.root/str(bad),
                                      task="poisson",execute=execute,timing_contract="synthetic")
            self.assertEqual(result["evaluation_status"],"evaluation_invalid" if bad else "valid")
            self.assertEqual(result["reward"],None if bad else 0)

    def test_retry_requires_observed_instability_and_one_linked_new_complete_group(self):
        first=fixture(b=(2,2,2.5))
        original={"retry_permitted":True,"performance_status":"baseline_unstable","protocol_attempt":first}
        second=fixture(attempt_id="synthetic-2")
        second.update(parent_attempt=first["attempt_id"],interference_resolution="recorded investigation")
        def next_group(*args,**kwargs):
            self.assertEqual(kwargs["parent_attempt"],first["attempt_id"])
            return {"protocol_attempt":second}
        output=self.root/"retry"
        output.mkdir()
        with patch("runner.replay.run_t3_attempt",side_effect=next_group):
            result=retry_t3_attempt(original,self.source,interference_resolution="recorded investigation",output_root=output)
        self.assertEqual(len(result["attempts"]),2)
        self.assertFalse(result["retry_permitted"])
        with self.assertRaises(ValueError):
            retry_t3_attempt(result,self.source,interference_resolution="third attempt",output_root=self.root/"third")
        with self.assertRaises(ValueError):
            retry_t3_attempt(original,self.source,interference_resolution="",output_root=self.root/"blank")


if __name__=="__main__": unittest.main()
