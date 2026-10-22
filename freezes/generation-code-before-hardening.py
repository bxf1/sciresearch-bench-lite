"""Generate all splits without consulting any inverse solver or score."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import importlib
import platform
import secrets
import sys
from pathlib import Path
import numpy as np
import scipy
from runner.common import VERSION, TASKS, canonical, digest, tree_hashes, write_json, read_json

SPLITS = {"public-dev":2,"author-calibration":4,"final-test":4}
COMPONENTS = ("system","mask","noise","solution")

def namespace_rng(entropy, *parts):
    namespace = hashlib.sha256(canonical(["sciresearch-v0.3", *parts])).digest()
    words = np.frombuffer(bytes.fromhex(entropy) + namespace,dtype="<u4").tolist()
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(words)))

def generate(root, task_names=TASKS, smoke=False):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=False)
    entropy=secrets.token_hex(32)
    provenance={"version":VERSION,"python":sys.version,"numpy":np.__version__,"scipy":scipy.__version__,"platform":platform.platform(),"bit_generator":"PCG64","namespace":"SHA256 JSON tuple -> little-endian u32 SeedSequence","root_entropy":entropy,"generated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"status":"generating","smoke_only":smoke,"source_hashes":{p.name:digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))}}
    write_json(root/"private"/"generation.json",provenance)
    audit=[]
    for task in task_names:
        module=importlib.import_module(f"authoring.{task}")
        fingerprints={}
        operators={}
        splits={"pilot-smoke":1} if smoke else SPLITS
        for split,count in splits.items():
            public=root/"inputs"/task/split
            private=root/"private"/task/split
            manifest={"contract_version":VERSION,"task":task,"split":split,"cases":[]}
            for level in range(3):
                for case in range(count):
                    key=(task,split,level,case)
                    case_id=digest(canonical([entropy,"opaque-case-id",*key]))[:20]
                    pub=public/"cases"/case_id
                    priv=private/"cases"/case_id
                    pub.mkdir(parents=True)
                    priv.mkdir(parents=True)
                    rngs={c:namespace_rng(entropy,*key,c) for c in COMPONENTS}
                    try:
                        evidence=module.generate_case(pub,priv,level,rngs)
                    except Exception as exc:
                        write_json(priv/"generation_failure.json",{"exception":type(exc).__name__,"reason":str(exc),"namespace":key,"replacement_forbidden":True})
                        provenance["status"]="generation_failed"
                        write_json(root/"private"/"generation.json",provenance)
                        raise
                    latent=evidence["latent_fingerprint"]
                    if latent in fingerprints:
                        raise RuntimeError(f"duplicate latent system: {key} and {fingerprints[latent]}")
                    fingerprints[latent]=key
                    if "operator_fingerprint" in evidence:
                        operator=evidence["operator_fingerprint"]
                        if level>0 and operator in operators:
                            raise RuntimeError("repeated medium/hard operator")
                        operators.setdefault(operator,[]).append(key)
                    row={"id":case_id,"namespace":key,"evidence":evidence,"input_hashes":tree_hashes(pub),"private_hashes":tree_hashes(priv)}
                    write_json(priv/"manifest.json",row)
                    audit.append(row)
                    manifest["cases"].append({"id":case_id,"path":f"cases/{case_id}","level":level})
            write_json(public/"manifest.json",manifest)
        write_json(root/"private"/task/"split_audit.json",{"latent_unique":len(fingerprints),"operator_unique":len(operators) if operators else None,"operator_repetitions":[v for v in operators.values() if len(v)>1],"easy_same_operator_distinct_rhs":task=="poisson","cases":len(fingerprints)})
    provenance["status"]="generated_qc_passed_not_frozen"
    provenance["cases"]=len(audit)
    write_json(root/"private"/"generation.json",provenance)
    write_json(root/"private"/"input_manifest.json",tree_hashes(root/"inputs"))
    return {"status":provenance["status"],"cases":len(audit),"root":str(root)}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--task",choices=TASKS,action="append")
    parser.add_argument("--smoke",action="store_true")
    args=parser.parse_args()
    print(generate(args.output,args.task or TASKS,args.smoke))
