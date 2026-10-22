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
pid=os.fork()
if pid==0:
    pass
    time.sleep(2)
    for case in cases:
        np.save(a.output/'cases'/case['id']/'u0.npy',np.ones(256,dtype='<f8'),allow_pickle=False)
    time.sleep(15)
    os._exit(0)
print(json.dumps({'probe':'background','child_pid':pid}),flush=True)
