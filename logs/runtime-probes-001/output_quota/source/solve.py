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
directory=a.output
target=directory/'quota-probe.bin'
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
