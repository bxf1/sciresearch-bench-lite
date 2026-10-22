"""Explicit Docker runtime probes, restricted to new benchmark workers and fixtures.

These are functional isolation evidence, not model runs or formal performance.
No existing container is stopped or changed. No 4 GiB allocation/OOM test runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import time

from runner.common import read_json, write_json
from runner.worker import run_worker

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT / "authoring/data/pilot-smoke/inputs/heat/pilot-smoke"
PROBES = ("normal_zero", "background_inherited_pipe", "background_closed_pipe", "private_paths",
          "forged_reward", "symlink_output", "stdout_flood", "output_quota", "tmp_quota", "timeout", "pids_pressure")
PRELUDE = '''import argparse,json,os,time,errno,signal
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser()
p.add_argument('--input',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--seed')
a=p.parse_args()
cases=json.loads((a.input/'manifest.json').read_text())['cases']
def zeros():
    for case in cases:
        d=a.output/'cases'/case['id']
        d.mkdir(parents=True,exist_ok=True)
        np.save(d/'u0.npy',np.zeros(256,dtype='<f8'),allow_pickle=False)
'''


def source_for(name, sentinel):
    if name == "normal_zero":
        body = "zeros()\nprint(json.dumps({'probe':'normal_zero','cases':len(cases)}),flush=True)\n"
    elif name.startswith("background_"):
        close_pipes = "os.close(1);os.close(2)" if name.endswith("closed_pipe") else "pass"
        body = """zeros()
pid=os.fork()
if pid==0:
    CLOSE_PIPES
    time.sleep(2)
    for case in cases:
        np.save(a.output/'cases'/case['id']/'u0.npy',np.ones(256,dtype='<f8'),allow_pickle=False)
    time.sleep(15)
    os._exit(0)
print(json.dumps({'probe':'background','child_pid':pid}),flush=True)
""".replace("CLOSE_PIPES", close_pipes)
    elif name == "private_paths":
        probes = [str(sentinel), "/truth/sentinel.txt", "/privateGT/sentinel.txt", "/var/run/docker.sock",
                  "/host" + str(sentinel), "/host/home/sentinel.txt", "/root/sentinel.txt"]
        body = f"paths={probes!r}\n" + """observed=[]
for target in paths:
    try:
        with open(target,'rb') as f:
            f.read(1)
        observed.append({'path':target,'readable':True})
    except OSError as exc:
        observed.append({'path':target,'readable':False,'errno':exc.errno})
zeros()
print(json.dumps({'probe':'private_paths','observed':observed,'uid':os.getuid(),'home':os.environ.get('HOME')}),flush=True)
if any(row['readable'] for row in observed):
    raise SystemExit(43)
"""
    elif name == "forged_reward":
        body = "zeros()\n(a.output/'reward.json').write_text('{\"reward\":1}')\n"
    elif name == "symlink_output":
        body = """zeros()
target=a.output/'cases'/cases[0]['id']/'u0.npy'
target.unlink()
target.symlink_to(a.input/cases[0]['path']/'target_grid.npy')
"""
    elif name == "stdout_flood":
        body = """zeros()
for _ in range(80):
    os.write(1,b'x'*65536)
"""
    elif name in ("output_quota", "tmp_quota"):
        directory = "a.output" if name == "output_quota" else "Path('/tmp')"
        body = f"directory={directory}\n" + """target=directory/'quota-probe.bin'
written=0
try:
    with target.open('wb',buffering=0) as f:
        for _ in range(300):
            written+=f.write(b'x'*1048576)
except OSError as exc:
    print(json.dumps({'probe':'quota','errno':exc.errno,'written_bytes':written,'file_bytes':target.stat().st_size}),flush=True)
    raise SystemExit(42 if exc.errno==errno.ENOSPC else 44)
print(json.dumps({'probe':'quota','limit_not_enforced':True,'written_bytes':written}),flush=True)
raise SystemExit(45)
"""
    elif name == "timeout":
        body = "zeros()\ntime.sleep(20)\n"
    elif name == "pids_pressure":
        body = """zeros()
spawned=[]
exhausted=False
try:
    for _ in range(130):
        pid=os.fork()
        if pid==0:
            os.close(1);os.close(2)
            time.sleep(20)
            os._exit(0)
        spawned.append(pid)
except OSError as exc:
    exhausted=exc.errno==errno.EAGAIN
    print(json.dumps({'probe':'pids','spawned':len(spawned),'errno':exc.errno,'limit_enforced':exhausted}),flush=True)
if not exhausted:
    print(json.dumps({'probe':'pids','spawned':len(spawned),'limit_enforced':False}),flush=True)
raise SystemExit(42 if exhausted else 45)
"""
    else:
        raise ValueError(name)
    return PRELUDE + body


def read_events(path):
    if not path.exists():
        return []
    values = []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("{"):
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return values


def assess(name, result, run_dir, sentinel):
    status = result["attempt_status"]
    events = read_events(run_dir / "stdout.txt")
    checks = {"candidate_not_misclassified_as_infrastructure": status != "infrastructure_failed"}
    if name in ("normal_zero", "private_paths"):
        checks["legal_artifacts_accepted"] = status == "completed" and result["artifact_valid"]
    if name == "normal_zero" or name == "background_closed_pipe":
        artifacts = list((run_dir / "artifacts").glob("cases/*/u0.npy"))
        import numpy as np
        checks["saved_arrays_remain_zero"] = bool(artifacts) and all(np.array_equal(np.load(p, allow_pickle=False), np.zeros(256)) for p in artifacts)
    if name.startswith("background_"):
        checks["descendants_cannot_mutate_admitted_artifacts"] = (status in ("timeout", "candidate_resource_failure") or
            (status == "completed" and result.get("candidate_processes_terminated") and
             bool(list((run_dir / "artifacts").glob("cases/*/u0.npy")))))
        if status in ("timeout", "candidate_resource_failure"):
            checks.pop("saved_arrays_remain_zero", None)
    if name == "private_paths":
        observed = next((e["observed"] for e in events if e.get("probe") == "private_paths"), [])
        checks["actual_host_sentinel_exists"] = sentinel.is_file()
        checks["private_paths_unreadable"] = len(observed) == 7 and all(not row["readable"] for row in observed)
        info = read_json(run_dir / "container.json")
        mounts = info["Mounts"]
        checks["only_public_source_input_and_trusted_timer_binds"] = {m["Destination"] for m in mounts if m["Type"] == "bind"} == {"/submission", "/input", "/trusted/process_timer.py"}
        checks["no_network"] = info["HostConfig"]["NetworkMode"] == "none"
        checks["distinct_nonroot_init_and_candidate"] = (info["Config"]["User"] == "65533:65533"
            and any(event.get("uid") == 65534 for event in events))
        checks["read_only_root"] = info["HostConfig"]["ReadonlyRootfs"] is True
        cg = read_json(run_dir / "cgroup_before.json")
        quota, period = cg["cpu.max"].split()
        checks["actual_cpu_one"] = quota != "max" and int(quota) == int(period)
        checks["actual_memory_4gib"] = cg["memory.max"].strip() == str(4*1024**3)
        checks["actual_no_swap"] = cg["memory.swap.max"].strip() == "0"
        checks["actual_pids_128"] = cg["pids.max"].strip() == "128"
    if name in ("forged_reward", "symlink_output"):
        checks["attack_rejected"] = status == "invalid_artifact" and not result["artifact_valid"]
    if name == "stdout_flood":
        checks["log_limit_reported"] = status == "log_limit"
        checks["host_log_storage_bounded"] = sum((run_dir / (s + ".txt")).stat().st_size for s in ("stdout", "stderr")) <= 4*1024**2
    if name in ("output_quota", "tmp_quota"):
        limit = (256 if name == "output_quota" else 64)*1024**2
        event = next((e for e in events if e.get("probe") == "quota"), {})
        checks["enospc_at_or_below_limit"] = event.get("errno") == 28 and 0 < event.get("file_bytes", 0) <= limit
        checks["candidate_failure_preserved"] = status == "candidate_failed"
    if name == "timeout":
        checks["timeout_reported"] = status == "timeout"
        checks["bounded_execution"] = result.get("total_wall_seconds", 100) < 10
    if name == "pids_pressure":
        event = next((e for e in events if e.get("probe") == "pids"), {})
        checks["pid_limit_enforced"] = event.get("limit_enforced") is True and event.get("spawned", 1000) < 128
        checks["candidate_failure_preserved"] = status in ("candidate_failed", "candidate_resource_failure", "timeout")
    return {"checks": checks, "passed": all(checks.values()), "events": events,
            "attempt_status": status, "artifact_valid": result["artifact_valid"], "worker_reason": result.get("reason")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT / "logs/runtime-probes-001")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--image", default="sciresearch-numeric:0.3.0")
    parser.add_argument("--probes", nargs="+", choices=PROBES, default=list(PROBES))
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    private = root / "private-fixture"
    private.mkdir(exist_ok=True)
    sentinel = private / "sentinel.txt"
    if not sentinel.exists():
        sentinel.write_text("private probe sentinel " + secrets.token_hex(16) + "\n")
    for name in args.probes:
        case_root = root / name
        case_root.mkdir(exist_ok=False)
        source = case_root / "source"
        source.mkdir()
        (source / "solve.py").write_text(source_for(name, sentinel))
        worker_source = PROJECT / "runner/worker.py"
        gate_source = PROJECT / "runner/artifact_gate.py"
        write_json(case_root / "provenance.json", {
            "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "candidate_source_sha256": hashlib.sha256((source / "solve.py").read_bytes()).hexdigest(),
            "worker_source_sha256": hashlib.sha256(worker_source.read_bytes()).hexdigest(),
            "timer_source_sha256": hashlib.sha256((PROJECT/"runner/process_timer.py").read_bytes()).hexdigest(),
            "artifact_gate_source_sha256": hashlib.sha256(gate_source.read_bytes()).hexdigest(),
            "input_manifest_sha256": hashlib.sha256((args.input / "manifest.json").read_bytes()).hexdigest(),
            "formal": False, "model_execution": False, "started_at": time.time(),
        })
        timeout = 1 if name in ("timeout", "background_inherited_pipe") else 15
        result = run_worker("heat", source, args.input, case_root / "worker", args.image, timeout=timeout)
        report = assess(name, result, case_root / "worker", sentinel)
        write_json(case_root / "probe.json", report)
        print(json.dumps({"probe": name, **report}, ensure_ascii=False), flush=True)
        rows = [{"probe": p.parent.name, **read_json(p)} for p in sorted(root.glob("*/probe.json"))]
        write_json(root / "summary.json", {"formal": False, "probes": rows, "passed": sum(r["passed"] for r in rows),
                                           "total": len(rows), "termination_protocol":"separate-UID PID1 waits for natural descendant termination; original deadline kills the whole W",
                                           "not_run": ["real 4GiB OOM pressure", "R/model endpoint isolation", "formal T3 exclusive timing"]})
        if name == "normal_zero" and not report["passed"]:
            raise SystemExit("Normal worker path failed; preserve evidence and fix before attack probes")


if __name__ == "__main__":
    main()
