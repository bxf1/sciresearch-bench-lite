"""Numerical-only J entrypoint. Candidate code is absent from this environment."""
from __future__ import annotations
import argparse
import importlib
from pathlib import Path
from runner.common import read_json,write_json
from runner.artifact_gate import OUTPUT_NAMES
from runner.phase import validate_manifest, guard_replay

def score_batch(task, inputs, truth, artifacts, *, freeze_path=None, image=None, judge_source_root=None):
    try:
        manifest=validate_manifest(task, inputs)
        phase=guard_replay(task,inputs,truth,image,judge_source_root,freeze_path=freeze_path)
    except Exception as exc:
        return {"evaluation_status":"evaluation_invalid","score":None,"reward":None,"reason":f"{type(exc).__name__}: {exc}","cases":[]}
    module=importlib.import_module(f"judge.{task}")
    rows=[]
    for entry in manifest["cases"]:
        try:
            row=module.score_case(Path(inputs)/entry["path"],Path(truth)/entry["path"],Path(artifacts)/"cases"/entry["id"]/OUTPUT_NAMES[task])
        except Exception as exc:
            return {"evaluation_status":"evaluation_invalid","score":None,"reward":None,"reason":f"{type(exc).__name__}: {exc}","cases":rows}
        rows.append({"id":entry["id"],"level":entry["level"],**row})
    passed=sum(bool(row["scientific_pass"]) for row in rows)
    score=sum(row["score"] for row in rows)/len(rows) if task!="poisson" else None
    return {"evaluation_status":"valid","score":score,"reward":int(passed==len(rows)) if task!="poisson" else None,"scientific_pass":passed==len(rows),"passed":passed,"total":len(rows),"artifact_valid":all(row["artifact_valid"] for row in rows),"cases":rows,"phase":phase,"performance_status":"not_measured" if task=="poisson" else "not_applicable"}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for flag in ("task","input","truth","artifacts","output"):
        parser.add_argument("--"+flag,required=True)
    parser.add_argument("--freeze",type=Path)
    parser.add_argument("--image-id")
    parser.add_argument("--judge-source",type=Path)
    args=parser.parse_args()
    result=score_batch(args.task,args.input,args.truth,args.artifacts,freeze_path=args.freeze,image=args.image_id,judge_source_root=args.judge_source)
    write_json(Path(args.output)/"metrics.json",result)
    if result["reward"] is not None:
        write_json(Path(args.output)/"reward.json",{"reward":result["reward"]})
