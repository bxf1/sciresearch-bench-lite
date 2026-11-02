#!/usr/bin/env python3
import os
os.environ.setdefault("OMP_NUM_THREADS","1")
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("MKL_NUM_THREADS","1")
os.environ.setdefault("NUMEXPR_NUM_THREADS","1")
import sys, json, argparse
import numpy as np
from scipy.signal import savgol_filter

def basis(Z):
    Z=np.atleast_2d(Z); z1=Z[:,0]; z2=Z[:,1]
    return np.column_stack([np.ones_like(z1),z1,z2,z1*z1,z1*z2,z2*z2,
                            z1**3,z1*z1*z2,z1*z2*z2,z2**3])

def weak_fit(t, sets, win=31, poly=3, thr=0.02, rounds=8):
    X=[];Y=[]
    dt=float(t[1]-t[0])
    h=win//2
    for Z in sets:
        for k in range(Z.shape[0]):
            Zs=savgol_filter(Z[k],win,poly,axis=0,mode='interp')
            D=savgol_filter(Z[k],win,poly,deriv=1,delta=dt,axis=0,mode='interp')
            X.append(basis(Zs[h:-h])); Y.append(D[h:-h])
    X=np.vstack(X);Y=np.vstack(Y)
    C=np.linalg.lstsq(X,Y,rcond=None)[0]
    for r in range(rounds):
        for j in range(2):
            keep=np.abs(C[:,j])>=thr
            if keep.sum()==0:
                C[:,j]=0.0
            else:
                C[keep,j]=np.linalg.lstsq(X[:,keep],Y[:,j],rcond=None)[0]
                C[~keep,j]=0.0
    return C

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--seed',type=int,default=0)
    args=ap.parse_args()
    manifest=json.load(open(os.path.join(args.input,'manifest.json')))
    outroot=args.output
    os.makedirs(outroot,exist_ok=True)
    for case in manifest['cases']:
        cid=case['id']; rel=case['path']
        cdir=os.path.join(args.input,rel)
        t=np.load(os.path.join(cdir,'t.npy'))
        tr=np.load(os.path.join(cdir,'train.npy'))
        sets=[tr]
        vp=os.path.join(cdir,'validation.npy')
        if os.path.exists(vp):
            sets.append(np.load(vp))
        C=weak_fit(t,sets,31,3,0.02,8)
        C=np.where(np.abs(C)<1e-6,0.0,C)
        # enforce at most 10 nonzero coefficients, dropping smallest magnitude
        flat=C.ravel(); nz=np.flatnonzero(flat!=0.0)
        if len(nz)>10:
            order=nz[np.argsort(np.abs(flat[nz]))]
            flat[order[:len(nz)-10]]=0.0
            C=flat.reshape(10,2)
        odir=os.path.join(outroot,'cases',cid)
        os.makedirs(odir,exist_ok=True)
        with open(os.path.join(odir,'model.json'),'w') as f:
            json.dump({"coefficients":C.tolist()},f,allow_nan=False)
    return 0

if __name__=='__main__':
    sys.exit(main())
