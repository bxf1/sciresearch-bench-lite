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

def _snapshot_code(root):
    """Archive exact generator sources without arrays, caches or author secrets."""
    project = Path(__file__).resolve().parents[1]
    paths = sorted((project / "authoring").glob("*.py")) + [project / "runner/common.py"]
    hashes = {}
    for path in paths:
        relative = path.relative_to(project)
        payload = path.read_bytes()
        destination = root / "private/generator-code" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        hashes[relative.as_posix()] = digest(payload)
    return hashes


def _shared_file_expected(task, path, level, visibility):
    constants = {
        "heat": {"target_grid.npy"},
        "ode": {"t.npy", "train_initial.npy", "validation_initial.npy", "hidden_t.npy", "hidden_initial.npy", "field_grid.npy"},
        "poisson": set(),
    }
    return path in constants[task] or (task == "poisson" and level == 0 and visibility == "input" and path == "A.npz")


def generate(root, task_names=TASKS, smoke=False, entropy=None, *, diagnostics=False):
    if smoke and diagnostics:
        raise ValueError("diagnostics require the complete main dataset")
    task_names = tuple(task_names)
    if not task_names or len(set(task_names)) != len(task_names) or any(task not in TASKS for task in task_names):
        raise ValueError("task_names must be a nonempty unique subset of the three tasks")
    entropy = secrets.token_hex(32) if entropy is None else entropy
    if not isinstance(entropy, str) or len(entropy) != 64:
        raise ValueError("root entropy must contain exactly 64 hexadecimal characters")
    try:
        entropy = bytes.fromhex(entropy).hex()
    except ValueError as exc:
        raise ValueError("invalid root entropy") from exc
    if len(entropy) != 64:
        raise ValueError("root entropy must encode 32 bytes")
    root=Path(root)
    root.mkdir(parents=True,exist_ok=False)
    provenance={"version":VERSION,"python":sys.version,"numpy":np.__version__,"scipy":scipy.__version__,"platform":platform.platform(),"bit_generator":"PCG64","namespace":"SHA256 JSON tuple -> little-endian u32 SeedSequence","root_entropy":entropy,"generated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"status":"generating","smoke_only":smoke,"source_hashes":_snapshot_code(root),"source_snapshot":"private/generator-code"}
    write_json(root/"private"/"generation.json",provenance)
    audit=[]
    for task in task_names:
        module=importlib.import_module(f"authoring.{task}")
        fingerprints={}
        operators={}
        input_cases={}
        file_occurrences={}
        splits={"pilot-smoke":1} if smoke else dict(SPLITS)
        if diagnostics:
            from .diagnostics import SPLITS as DIAGNOSTIC_SPLITS, specifications
            splits.update({name: None for name in DIAGNOSTIC_SPLITS})
        for split,count in splits.items():
            public=root/"inputs"/task/split
            private=root/"private"/task/split
            manifest={"contract_version":VERSION,"task":task,"split":split,"cases":[]}
            groups = [(level, [(i, None) for i in range(count)]) for level in range(3)] if count else [
                (level, [(r["profile_index"], r) for r in specifications(task) if r["level"] == level])
                for level in (1, 2)]
            for level, entries in groups:
                for case, diagnostic in entries:
                    key=(task,split,diagnostic["profile_id"],case) if diagnostic else (task,split,level,case)
                    case_id=digest(canonical([entropy,"opaque-case-id",*key]))[:20]
                    pub=public/"cases"/case_id
                    priv=private/"cases"/case_id
                    pub.mkdir(parents=True)
                    priv.mkdir(parents=True)
                    rngs={c:namespace_rng(entropy,*key,c) for c in COMPONENTS}
                    cache_pair = bool(diagnostic and task == "poisson" and diagnostic["profile_id"] == "cache_order")
                    if cache_pair:
                        rngs["system"] = namespace_rng(entropy,task,split,"cache_order",case % 2,"system")
                    try:
                        evidence=module.generate_case(pub,priv,level,rngs, **({"diagnostic":diagnostic["options"]} if diagnostic else {}))
                        if evidence.get("qc", {}).get("passed") is not True:
                            raise RuntimeError("generator returned non-passing QC")
                        latent=evidence["latent_fingerprint"]
                        if not isinstance(latent, str) or not latent:
                            raise RuntimeError("missing latent fingerprint")
                        if latent in fingerprints:
                            raise RuntimeError(f"duplicate latent system: {key} and {fingerprints[latent]}")
                        input_hashes, private_hashes = tree_hashes(pub), tree_hashes(priv)
                        if not input_hashes:
                            raise RuntimeError("generator produced no public input files")
                        case_fingerprint = digest(canonical(input_hashes))
                        if case_fingerprint in input_cases:
                            raise RuntimeError(f"byte-identical public case: {key} and {input_cases[case_fingerprint]}")
                        if "operator_fingerprint" in evidence:
                            operator=evidence["operator_fingerprint"]
                            if not isinstance(operator, str) or not operator:
                                raise RuntimeError("missing operator fingerprint")
                            allowed_pair = cache_pair and operator in operators and len(operators[operator]) == 1 and operators[operator][0] == (task,split,"cache_order",case - 2)
                            if level>0 and operator in operators and not allowed_pair:
                                raise RuntimeError("repeated medium/hard operator")
                            operators.setdefault(operator,[]).append(key)
                        fingerprints[latent]=key
                        input_cases[case_fingerprint]=key
                        for visibility, hashes in (("input", input_hashes), ("private", private_hashes)):
                            for path, sha256 in hashes.items():
                                file_occurrences.setdefault(sha256, []).append({"case_id":case_id,"split":split,"level":level,"path":path,"visibility":visibility,"expected_shared":_shared_file_expected(task,path,level,visibility) or bool(cache_pair and path == "A.npz" and visibility == "input")})
                    except Exception as exc:
                        write_json(priv/"generation_failure.json",{"exception":type(exc).__name__,"reason":str(exc),"namespace":key,"replacement_forbidden":True})
                        provenance["status"]="generation_failed"
                        write_json(root/"private"/"generation.json",provenance)
                        raise
                    row={"id":case_id,"namespace":key,"evidence":evidence,"input_hashes":input_hashes,"private_hashes":private_hashes,"input_case_fingerprint":case_fingerprint}
                    if diagnostic:
                        row["diagnostic"] = diagnostic
                    write_json(priv/"manifest.json",row)
                    audit.append(row)
                    manifest["cases"].append({"id":case_id,"path":f"cases/{case_id}","level":level,
                        **({"profile_id":diagnostic["profile_id"],"profile_index":case} if diagnostic else {})})
            if count is None:
                from .diagnostics import PROFILES
                manifest["cases"].sort(key=lambda r:(PROFILES[task].index(r["profile_id"]),r["profile_index"]))
                manifest["purpose"] = "diagnostic_only_excluded_from_main_score"
            write_json(public/"manifest.json",manifest)
        shared_files = [{"sha256":sha256,"cross_split":len({r['split'] for r in rows})>1,"all_occurrences_expected_shared":all(r["expected_shared"] for r in rows),"occurrences":rows}
                        for sha256, rows in sorted(file_occurrences.items()) if len(rows)>1]
        write_json(root/"private"/task/"split_audit.json",{"latent_unique":len(fingerprints),"input_case_unique":len(input_cases),"operator_unique":len(operators) if operators else None,"operator_repetitions":[v for v in operators.values() if len(v)>1],"easy_same_operator_distinct_rhs":task=="poisson","cases":len(fingerprints),"shared_files":shared_files,"shared_file_policy":"Whole-case/latent duplicates stop generation. Medium/hard operator reuse is allowed only for the predeclared pair within the same diagnostic cache_order split. Other individual shared files require author review; never screen by solver scores."})
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
    parser.add_argument("--diagnostics",action="store_true")
    parser.add_argument("--entropy-file",type=Path,help="Private JSON containing root_entropy, such as a prior private/generation.json; never publish or mount into R/W")
    args=parser.parse_args()
    entropy = read_json(args.entropy_file)["root_entropy"] if args.entropy_file else None
    print(generate(args.output,args.task or TASKS,args.smoke,entropy=entropy,diagnostics=args.diagnostics))
