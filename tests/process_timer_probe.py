"""Small explicit Linux-container probes; no model, T3 performance, or OOM load."""
import argparse
import json
from pathlib import Path
import subprocess

import numpy as np

from runner.common import file_hash, write_json
from runner.worker import run_worker
from tests.runtime_probe import PRELUDE

ROOT = Path(__file__).resolve().parents[1]
BODIES = {
    "normal": "zeros()\ntime.sleep(.15)\n",
    "double_fork_closed_pipes": """zeros()
if os.fork(): os._exit(0)
os.setsid()
if os.fork(): os._exit(0)
os.close(1); os.close(2)
time.sleep(.4)
for case in cases:
    np.save(a.output/'cases'/case['id']/'u0.npy',np.ones(256,dtype='<f8'),allow_pickle=False)
os._exit(0)
""",
    "candidate_subreaper": """import ctypes
zeros()
if os.fork(): os._exit(0)
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
if os.fork()==0:
    if os.fork(): os._exit(0)
    os.close(1); os.close(2)
    time.sleep(.4)
    for case in cases:
        np.save(a.output/'cases'/case['id']/'u0.npy',np.ones(256,dtype='<f8'),allow_pickle=False)
    os._exit(0)
while True:
    try: os.waitpid(-1,0)
    except ChildProcessError: break
os._exit(0)
""",
    "timer_tampering": """import ctypes,resource,socket
checks={}
def denied(name, action):
    try: action(); checks[name]=False
    except (PermissionError,FileNotFoundError,ConnectionRefusedError): checks[name]=True
denied('kill_init',lambda:os.kill(1,signal.SIGKILL))
denied('stop_init',lambda:os.kill(1,signal.SIGSTOP))
denied('prlimit_init',lambda:resource.prlimit(1,resource.RLIMIT_NOFILE,(1,1)))
denied('write_record',lambda:Path('/tmp/.sciresearch-timer-private/result.json').write_text('{}'))
denied('unlink_private_dir',lambda:Path('/tmp/.sciresearch-timer-private').rmdir())
denied('read_init_memory',lambda:open('/proc/1/mem','rb'))
denied('write_init_stdout',lambda:open('/proc/1/fd/1','wb'))
denied('second_handshake',lambda:socket.socket(socket.AF_UNIX).connect('/tmp/.sciresearch-timer/launch.sock'))
lib=ctypes.CDLL(None,use_errno=True)
checks['ptrace_init']=lib.ptrace(16,1,None,None)==-1 and ctypes.get_errno()==1
checks['no_inherited_socket']=all(not os.readlink('/proc/self/fd/'+fd).startswith('socket:') for fd in os.listdir('/proc/self/fd') if fd.isdigit() and os.path.exists('/proc/self/fd/'+fd))
checks['uid65534']=os.getuid()==65534
status=Path('/proc/self/status').read_text()
checks['no_capabilities']='CapEff:\\t0000000000000000' in status
checks['no_new_privileges']='NoNewPrivs:\\t1' in status
print(json.dumps(checks),flush=True)
assert all(checks.values()),checks
zeros()
""",
    "background_timeout": """zeros()
if os.fork(): os._exit(0)
os.setsid();os.close(1);os.close(2)
time.sleep(30)
""",
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--only",choices=tuple(BODIES))
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    image=subprocess.check_output(["docker","image","inspect","sciresearch-numeric:0.3.0","--format","{{.Id}}"],text=True).strip()
    inputs=ROOT/"authoring/data/pilot-smoke/inputs/heat/pilot-smoke"
    rows=[]
    for name in ([args.only] if args.only else BODIES):
        directory=args.output/name
        source=directory/"source"
        source.mkdir(parents=True)
        (source/"solve.py").write_text(PRELUDE+BODIES[name])
        result=run_worker("heat",source,inputs,directory/"worker",image,timeout=3 if name=="background_timeout" else 20)
        passed=(result["attempt_status"]=="completed" and result["artifact_valid"] and result.get("timing_complete") is True and result["formal_timing"] is False)
        if name in ("double_fork_closed_pipes","candidate_subreaper") and passed:
            passed=result["execution_wall_seconds"]>=.4 and all(np.all(np.load(p,allow_pickle=False)==1) for p in (directory/"worker/artifacts").glob("cases/*/u0.npy"))
        if name=="background_timeout":
            passed=result["attempt_status"]=="timeout" and not result["timing_complete"] and not result["artifact_valid"]
        remaining=subprocess.check_output(["docker","ps","-aq","--filter","name=^/"+result["container_name"]+"$"],text=True).strip()
        passed=passed and not remaining
        row={"probe":name,"passed":bool(passed),"attempt_status":result["attempt_status"],"execution_wall_seconds":result.get("execution_wall_seconds"),"remaining_container":remaining or None,"result_path":str(directory/"worker/worker.json")}
        rows.append(row)
        print(json.dumps(row),flush=True)
        write_json(args.output/"summary.json",{"formal":False,"model_calls":0,"scientific_performance_measured":False,"image":image,"worker_source_sha256":file_hash(ROOT/"runner/worker.py"),"timer_source_sha256":file_hash(ROOT/"runner/process_timer.py"),"passed":sum(r["passed"] for r in rows),"total":len(rows),"probes":rows})
        if not passed:
            raise SystemExit(1)


if __name__=="__main__":
    main()
