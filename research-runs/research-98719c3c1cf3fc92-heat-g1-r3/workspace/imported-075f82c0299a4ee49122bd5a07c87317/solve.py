import argparse, json, os
from pathlib import Path
import numpy as np

def solve_case(case_dir, out_path, alpha=1e-5):
    meta=json.load(open(case_dir/'metadata.json'))
    obs=np.loadtxt(case_dir/'observations.csv',delimiter=',',skiprows=1,ndmin=2)
    x=obs[:,0]; t=obs[:,1]; y=obs[:,2]
    kappa=float(meta['kappa'])
    k=np.arange(1,33,dtype=float)
    A=np.sin(np.pi*np.outer(x,k))*np.exp(-kappa*np.pi**2*outer_t(k,t))
    D=k**2
    U,s,Vt=np.linalg.svd(A/D,full_matrices=False)
    lam=alpha*s[0]**2
    a=(Vt.T@(s/(s*s+lam)*((U.T)@y)))/D
    grid=np.load(case_dir/'target_grid.npy').astype(np.float64)
    u=np.sin(np.pi*np.outer(grid,k))@a
    return u

def outer_t(k,t):
    return np.outer(t,k*k)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--input',required=True); p.add_argument('--output',required=True); p.add_argument('--seed',type=int,default=0)
    args=p.parse_args()
    inp=Path(args.input); out=Path(args.output)
    man=json.load(open(inp/'manifest.json'))
    for c in man['cases']:
        cid=c['id']; d=inp/c['path']
        u=solve_case(d,None)
        o=out/'cases'/cid; o.mkdir(parents=True,exist_ok=True)
        np.save(o/'u0.npy', np.asarray(u,dtype='<f8'))
if __name__=='__main__': main()
