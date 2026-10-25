"""Run all eleven author methods on calibration only, preserving every failure."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .common import write_json,tree_hashes,digest,canonical,read_json
from .worker import docker
from .replay import prepare_judge,replay_single

METHODS={"heat":["ls","rank5","tikhonov","discrepancy","tsvd"],"ode":["raw","fixed","search"],"poisson":["cg","jacobi","lu"]}
FIXED={"heat":"tikhonov","ode":"fixed","poisson":"lu"}

def calibrate(project,data,output,image):
    project,data,output=map(lambda p:Path(p).resolve(),(project,data,output))
    output.mkdir(parents=True,exist_ok=False)
    image=json.loads(docker("image","inspect",image).stdout)[0]["Id"]
    judge=prepare_judge(project,project/"build"/"judge")
    report={"status":"local_calibration_not_formal_freeze","image":image,"judge_hash":digest(canonical(tree_hashes(judge))),"methods":[],"formal_timing":False,"final_test_scores_accessed":False}
    for task,methods in METHODS.items():
        inputs=data/"inputs"/task/"author-calibration"
        truth=data/"private"/task/"author-calibration"
        cases=read_json(inputs/"manifest.json")["cases"]
        if len(cases)!=12 or any(sum(c["level"]==level for c in cases)!=4 for level in range(3)):
            raise ValueError("calibration requires twelve cases, four per level")
        source=project/"baselines"/task
        for method in methods:
            print(f"calibration {task}/{method} started",flush=True)
            result=replay_single(source,task=task,input_root=inputs,truth_root=truth,output_root=output/task/method,image=image,judge_source_root=judge,method=method)
            row={"task":task,"method":method,"source_hash":digest(canonical(tree_hashes(source))),"input_hash":digest(canonical(tree_hashes(inputs))),"fixed_reference":method==FIXED[task],"result":result}
            report["methods"].append(row)
            write_json(output/"summary.json",report)
            print(json.dumps({"task":task,"method":method,"status":result["evaluation_status"],"passed":result.get("passed"),"total":result.get("total"),"score":result.get("score")}),flush=True)
            if result["evaluation_status"]=="evaluation_invalid":
                report["status"]="stopped_for_trusted_or_infrastructure_failure"
                write_json(output/"summary.json",report)
                return report
    report["fixed_references_passed"]=all(r["result"].get("scientific_pass",False) for r in report["methods"] if r["fixed_reference"])
    write_json(output/"summary.json",report)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--data",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--image",default="sciresearch-numeric:0.3.0")
    a=p.parse_args()
    calibrate(Path(__file__).resolve().parents[1],a.data,a.output,a.image)
