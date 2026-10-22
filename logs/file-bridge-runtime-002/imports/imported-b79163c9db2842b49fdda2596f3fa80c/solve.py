import argparse,json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser()
p.add_argument('--input');p.add_argument('--output');p.add_argument('--seed')
a=p.parse_args()
for c in json.loads((Path(a.input)/'manifest.json').read_text())['cases']:
    out=Path(a.output)/'cases'/c['id']
    out.mkdir(parents=True)
    np.save(out/'u0.npy',np.zeros(256,dtype='<f8'),allow_pickle=False)
