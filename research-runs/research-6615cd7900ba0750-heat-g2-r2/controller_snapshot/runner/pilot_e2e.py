"""Replay a real model's pilot source through the trusted registry and W/J.

This deliberately uses pilot data and is not a formal research condition.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
from .common import read_json,write_json,canonical,digest,tree_hashes,file_hash
from .registry import Registry
from .replay import prepare_judge,evaluate_public,replay_checkpoint
from .worker import run_worker,docker

def run(model_attempt,data,output):
    model_attempt,data,output=map(lambda p:Path(p).resolve(),(model_attempt,data,output))
    model=read_json(model_attempt/"result.json")
    source=model_attempt/"snapshot"
    source_hash=digest(canonical(tree_hashes(source)))
    project=Path(__file__).resolve().parents[1]
    output.mkdir(parents=True,exist_ok=False)
    workspace=output/"workspace"
    shutil.copytree(source,workspace/"candidate")
    registry=Registry.create(output/"registry",workspace,"heat","pilot-smoke",budget_seconds=600)
    image=json.loads(docker("image","inspect","sciresearch-numeric:0.3.0").stdout)[0]["Id"]
    inputs=data/"inputs/heat/pilot-smoke"
    truth=data/"private/heat/pilot-smoke"
    judge=prepare_judge(project,project/"build/judge")
    def evaluate(snapshot,candidate_id,remaining):
        work=output/"dev"/candidate_id
        result=run_worker("heat",snapshot,inputs,work,image,timeout=remaining)
        if result["artifact_valid"]:
            result["public_feedback"]=evaluate_public("heat",inputs,work/"artifacts")
        return result
    candidate=registry.evaluate("candidate",evaluate)
    if candidate["source_hash"]!=source_hash:
        raise RuntimeError("model source changed on registration")
    registry.finalize(candidate["id"])
    state=registry.close()
    repeated=[]
    for repeat in range(3):
        row=replay_checkpoint(registry.verified_snapshot(candidate["id"]),candidate["id"],source_hash,task="heat",input_root=inputs,truth_root=truth,output_root=output/f"replay-{repeat+1}",image=image,judge_source_root=judge,profile=None)
        repeated.append(row)
    valid=all(row["evaluation_status"]=="valid" for row in repeated)
    result={"status":"pilot_model_to_independent_scoring_completed" if valid else "pilot_evaluation_invalid","formal":False,"research_condition":None,"data_split":"pilot-smoke","model_attempt":str(model_attempt),"model_result_sha256":file_hash(model_attempt/"result.json"),"model_source_hash":source_hash,"controller_sha256":file_hash(__file__),"image":image,"first_id":state["first_id"],"final_id":state["final_id"],"same_source_reused_for_first_final":state["first_id"]==state["final_id"],"repeats":repeated,"reward":int(all(row.get("reward")==1 for row in repeated)) if valid else None,"score":sum(row["score"] for row in repeated)/3 if valid else None,"iteration_conclusion":"No research iteration tested: model was explicitly asked to emit a zero solution.","cost_usd":None,"formal_acceptance":"not_satisfied"}
    write_json(output/"result.json",result)
    shutil.copyfile(__file__,output/"controller.py")
    print(json.dumps({k:v for k,v in result.items() if k!="repeats"},allow_nan=False))
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--model-attempt",required=True,type=Path)
    p.add_argument("--data",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    run(args.model_attempt,args.data,args.output)
