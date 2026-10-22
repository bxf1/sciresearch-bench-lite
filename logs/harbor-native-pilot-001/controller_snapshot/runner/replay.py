"""Trusted candidate execution, public diagnostics, and isolated numeric judging."""
from __future__ import annotations
import argparse
import importlib
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import uuid
from .artifact_gate import OUTPUT_NAMES
from .common import read_json,write_json,tree_hashes,canonical,digest
from .worker import docker,run_worker,InfrastructureError
from .phase import validate_manifest, guard_replay, PhaseError

def prepare_judge(project, destination):
    project,destination=Path(project).resolve(),Path(destination).resolve()
    sources=[*sorted((project/"judge").glob("*.py")),*[project/"public"/name for name in ("heat.py","ode.py","poisson.py")],*[project/"runner"/name for name in ("__init__.py","common.py","artifact_gate.py","phase.py")]]
    source_hashes={p.relative_to(project).as_posix():__import__("hashlib").sha256(p.read_bytes()).hexdigest() for p in sources}
    target=destination/digest(canonical(source_hashes))[:20]
    if target.exists():
        if tree_hashes(target)!=source_hashes:
            raise RuntimeError("trusted judge snapshot changed")
        return target
    target.mkdir(parents=True)
    for p in sources:
        dest=target/p.relative_to(project)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,dest)
        dest.chmod(0o444)
    return target

def run_judge(task,inputs,truth,artifacts,run_dir,image,judge_source_root,*,freeze_path=None):
    phase=guard_replay(task,inputs,truth,image,judge_source_root,freeze_path=freeze_path)
    run_dir=Path(run_dir).resolve()
    run_dir.mkdir(parents=True,exist_ok=False)
    output=run_dir/"output"
    output.mkdir(mode=0o777)
    output.chmod(0o777)
    name="sciresearch-j-"+uuid.uuid4().hex[:12]
    command=["create","--name",name,"--label","sciresearch.project=benchmark-v0.3","--network","none","--cpus","1","--memory","4g","--memory-swap","4g","--pids-limit","128","--cap-drop","ALL","--security-opt","no-new-privileges","--read-only","--user","65534:65534","--tmpfs","/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777","--env","PYTHONPATH=/trusted","--workdir","/trusted"]
    for source,target,readonly in ((inputs,"/input",True),(truth,"/truth",True),(artifacts,"/artifacts",True),(judge_source_root,"/trusted",True),(output,"/result",False)):
        command.extend(["--mount",f"type=bind,src={Path(source).resolve()},dst={target}"+(",readonly" if readonly else "")])
    command.extend([image,"python","-B","-m","judge.batch","--task",task,"--input","/input","--truth","/truth","--artifacts","/artifacts","--output","/result"])
    if phase["formal"]:
        # Insert a trusted read-only contract mount before the image/command.
        image_index=command.index(image)
        command[image_index:image_index]=["--mount",f"type=bind,src={Path(freeze_path).resolve()},dst=/freeze.json,readonly"]
        command.extend(["--freeze","/freeze.json","--image-id",image,"--judge-source","/trusted"])
    created=False
    started=time.perf_counter()
    try:
        docker(*command)
        created=True
        info=json.loads(docker("inspect",name).stdout)[0]
        write_json(run_dir/"container.json",{k:info[k] for k in ("Id","Image","HostConfig","Mounts","Config")})
        proc=docker("start","-a",name,timeout=1200,check=False)
        (run_dir/"stdout.txt").write_text(proc.stdout)
        (run_dir/"stderr.txt").write_text(proc.stderr)
        state=json.loads(docker("inspect",name).stdout)[0]["State"]
        if state["ExitCode"]!=0 or not (output/"metrics.json").is_file():
            raise InfrastructureError("J failed: "+proc.stderr[-1000:])
        result=read_json(output/"metrics.json")
    except (InfrastructureError,subprocess.TimeoutExpired,OSError,ValueError) as exc:
        result={"evaluation_status":"evaluation_invalid","reward":None,"score":None,"reason":str(exc)}
    finally:
        if created:
            docker("rm","-f",name,check=False)
    result["judge_wall_seconds"]=time.perf_counter()-started
    write_json(run_dir/"result.json",result)
    return result

def evaluate_public(task,input_root,artifacts):
    manifest=validate_manifest(task,input_root)
    if manifest["split"] not in ("public-dev","pilot-smoke"):
        raise PhaseError("research feedback may only use public-dev or explicit pilot-smoke inputs")
    module=importlib.import_module("public."+task)
    rows=[]
    for case in manifest["cases"]:
        row=module.check_case(Path(input_root)/case["path"],Path(artifacts)/"cases"/case["id"]/OUTPUT_NAMES[task])
        rows.append({"id":case["id"],**row})
    return rows

def replay_single(snapshot, *, task,input_root,truth_root,output_root,image,judge_source_root,method=None,freeze_path=None):
    # This guard deliberately runs before creating a worker or evaluating a candidate.
    phase=guard_replay(task,input_root,truth_root,image,judge_source_root,freeze_path=freeze_path)
    output_root=Path(output_root)
    output_root.mkdir(parents=True,exist_ok=False)
    worker=run_worker(task,snapshot,input_root,output_root/"worker",image,method=method)
    if worker["attempt_status"]=="infrastructure_failed":
        result={"attempt_status":"infrastructure_failed","evaluation_status":"evaluation_invalid","reward":None,"score":None,"worker":worker}
    elif worker["attempt_status"] not in ("completed","invalid_artifact") or not (output_root/"worker"/"artifacts").exists():
        result={"attempt_status":worker["attempt_status"],"evaluation_status":"valid","reward":0,"score":0.,"artifact_valid":False,"scientific_pass":False,"worker":worker}
    else:
        result=run_judge(task,input_root,truth_root,output_root/"worker"/"artifacts",output_root/"judge",image,judge_source_root,freeze_path=freeze_path)
        result.update(attempt_status=worker["attempt_status"],worker=worker)
    result["phase"]=phase
    write_json(output_root/"result.json",result)
    return result

def replay_checkpoint(snapshot,checkpoint_id,source_hash,**config):
    config=dict(config)
    profile=config.pop("profile",None)
    baseline_source=config.pop("baseline_source",None)
    phase=guard_replay(config["task"],config["input_root"],config["truth_root"],config["image"],config["judge_source_root"],freeze_path=config.get("freeze_path"),profile=profile)
    if phase["formal"]:
        profile=phase["profile"]
    if config["task"]!="poisson":
        result=replay_single(snapshot,**config)
        return {**result,"checkpoint_id":checkpoint_id,"source_hash":source_hash}
    if baseline_source is None:
        raise ValueError("T3 replay requires trusted Jacobi baseline_source")
    output=Path(config.pop("output_root"))
    output.mkdir(parents=True,exist_ok=False)
    samples={"B":[],"C":[]}
    for index,kind in enumerate("BCCBBC"):
        row=replay_single(baseline_source if kind=="B" else snapshot,output_root=output/f"{index+1}-{kind}",method="jacobi" if kind=="B" else None,**config)
        samples[kind].append(row)
    b_correct=all(x.get("scientific_pass",False) for x in samples["B"])
    c_correct=all(x.get("scientific_pass",False) for x in samples["C"])
    times={key:[x["worker"]["execution_wall_seconds"] for x in rows if "execution_wall_seconds" in x["worker"]] for key,rows in samples.items()}
    diagnostic_speedup=statistics.median(times["B"])/statistics.median(times["C"]) if b_correct and c_correct and len(times["B"])==len(times["C"])==3 else None
    # Current host timing contains Docker exec overhead. It is never promoted to formal performance.
    result={"checkpoint_id":checkpoint_id,"source_hash":source_hash,"profile":profile,"scientific_pass":c_correct,"baseline_correct":b_correct,"reward":int(c_correct) if profile=="accuracy_with_efficiency_diagnostic" else None,"score":None,"evaluation_status":"valid" if all(r["evaluation_status"]=="valid" for rows in samples.values() for r in rows) else "evaluation_invalid","performance_status":"invalid_environment","diagnostic_speedup":diagnostic_speedup,"samples":samples,"cache_state":"host page cache not cleared; B,C,C,B,B,C"}
    if result["evaluation_status"]!="valid":
        result["reward"]=None
    write_json(output/"result.json",result)
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--task",required=True,choices=("heat","ode","poisson"))
    for flag in ("source","input","truth","output"):
        parser.add_argument("--"+flag,type=Path,required=True)
    parser.add_argument("--image",default="sciresearch-numeric:0.3.0")
    parser.add_argument("--method")
    parser.add_argument("--freeze",type=Path,help="Complete frozen configuration required before final-test execution")
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    judge=prepare_judge(project,project/"build"/"judge")
    image=json.loads(docker("image","inspect",args.image).stdout)[0]["Id"]
    result=replay_single(args.source,task=args.task,input_root=args.input,truth_root=args.truth,output_root=args.output,image=image,judge_source_root=judge,method=args.method,freeze_path=args.freeze)
    print(json.dumps({k:v for k,v in result.items() if k not in ("cases","worker")},allow_nan=False))
