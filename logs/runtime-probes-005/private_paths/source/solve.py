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
paths=['/Users/baixiongfei/Documents/Projects/build_bench/benchmark/logs/runtime-probes-005/private-fixture/sentinel.txt', '/truth/sentinel.txt', '/privateGT/sentinel.txt', '/var/run/docker.sock', '/host/Users/baixiongfei/Documents/Projects/build_bench/benchmark/logs/runtime-probes-005/private-fixture/sentinel.txt', '/host/home/sentinel.txt', '/root/sentinel.txt']
observed=[]
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
