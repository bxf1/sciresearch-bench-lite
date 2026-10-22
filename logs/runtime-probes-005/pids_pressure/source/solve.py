import argparse,json,os,time,errno,signal
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
zeros()
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
