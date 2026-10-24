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
blocks=[]
for i in range(60):
    block=bytearray(64*1024**2)
    block[::4096]=b'\xa5'*(len(block)//4096)
    blocks.append(block)
    if (i+1)%4==0: print(json.dumps({'touched_bytes':(i+1)*64*1024**2}),flush=True)
time.sleep(3)
blocks.clear()
zeros()
