import numpy as np, json, os, time, warnings
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

def basis(Z):
    Z=np.asarray(Z)
    z1=Z[...,0]; z2=Z[...,1]
    cols=[np.ones_like(z1),z1,z2,z1*z1,z1*z2,z2*z2,z1**3,z1*z1*z2,z1*z2*z2,z2**3]
    return np.stack(cols,axis=-1)

def basis_bc(Z,S):
    # S same shape as Z, observation noise std; bias-correct monomials
    z1=Z[...,0]; z2=Z[...,1]; s1=S[...,0]; s2=S[...,1]
    B=basis(Z)
    B[...,3]-=s1*s1
    B[...,6]-=3*s1*s1*z1
    B[...,7]-=s1*s1*z2
    B[...,8]-=s2*s2*z1
    return B

def make_weak(t, Zs, Ss, Z0s, lengths=None):
    n=len(t); dt=t[1]-t[0]
    if lengths is None:
        lengths=[max(2,int(n*f)) for f in (0.015,0.03,0.07,0.13,0.27)]
        lengths=sorted(set(min(n-1,x) for x in lengths))
    Arows=[]; brows=[]; wrows=[]
    for z,s,z0 in zip(Zs,Ss,Z0s):
        z=np.array(z,dtype=float,copy=True); s=np.array(s,dtype=float,copy=True)
        z[0]=z0; s[0]=0.0
        B=basis_bc(z,s)
        cum=np.zeros_like(B)
        cum[1:]=np.cumsum((B[1:]+B[:-1])*0.5*dt,axis=0)
        for L in lengths:
            if L<1 or L>=n: continue
            idx=np.arange(0,n-L)
            A=cum[idx+L]-cum[idx]
            b=z[idx+L]-z[idx]
            # approximate variance for difference and integrated basis noise
            vb=s[idx+L]**2+s[idx]**2
            # integrated basis noise variance approx factor * L*dt * s^2
            w=1.0/(vb + 0.15*(L*dt)*(s[idx+L]**2+s[idx]**2))
            Arows.append(A); brows.append(b); wrows.append(w)
    return np.vstack(Arows),np.vstack(brows),np.vstack(wrows)

def wls(A,b,w,mask=None):
    p=A.shape[1]
    if mask is None: mask=np.ones(p,bool)
    c=np.zeros(p)
    if mask.any():
        c[mask]=np.linalg.lstsq(A[:,mask]*np.sqrt(w)[:,None],b*np.sqrt(w),rcond=None)[0]
    return c

def omp_path(A,b,w,maxk=10):
    p=A.shape[1]; sw=np.sqrt(w); Aj=A*sw[:,None]; bj=b*sw
    sel=[]; out=[]
    for k in range(1,min(maxk,p)+1):
        best=None
        for tt in range(p):
            if tt in sel: continue
            cols=sel+[tt]
            c=np.linalg.lstsq(Aj[:,cols],bj,rcond=None)[0]
            rr=np.sum((bj-Aj[:,cols]@c)**2)
            if best is None or rr<best[0]: best=(rr,tt)
        sel.append(best[1]); out.append(tuple(sorted(sel)))
    return out

def mag_path(A,b,w,maxk=10):
    sw=np.sqrt(w); c=np.linalg.lstsq(A*sw[:,None],b*sw,rcond=None)[0]
    order=np.argsort(np.abs(c))[::-1]
    return [tuple(sorted(order[:k])) for k in range(1,min(maxk,len(order))+1)]

def bic(A,b,w,sup,ne):
    mask=np.zeros(A.shape[1],bool)
    if sup: mask[list(sup)]=True
    c=wls(A,b,w,mask)
    ss=float(np.sum(w*(b-A@c)**2))
    ss=max(ss,1e-300)
    return ne*np.log(ss/ne)+len(sup)*np.log(ne),ss,c

def local_search(A,b,w,sup,ne,maxk=10):
    sup=set(sup)
    best=bic(A,b,w,tuple(sorted(sup)),ne)[0]
    for it in range(8):
        cands=[]
        p=A.shape[1]
        for tt in range(p):
            if tt not in sup: cands.append(tuple(sorted(sup|{tt})))
        for tt in list(sup): cands.append(tuple(sorted(sup-{tt})))
        for tt in list(sup):
            for uu in range(p):
                if uu not in sup: cands.append(tuple(sorted((sup-{tt})|{uu})))
        improved=False
        for cnd in cands:
            if len(cnd)>maxk: continue
            bc=bic(A,b,w,cnd,ne)[0]
            if bc<best-1e-10:
                best=bc; sup=set(cnd); improved=True
        if not improved: break
    return tuple(sorted(sup))

def select_supports(A,B,w,n_traj,n_times):
    ne=max(20,n_traj*n_times)
    masks=np.zeros((A.shape[1],2),bool); Cs=np.zeros((A.shape[1],2))
    for j in range(2):
        sups=set(omp_path(A,B[:,j],w[:,j])+mag_path(A,B[:,j],w[:,j]))
        scored=[]
        for sup in sups: scored.append((bic(A,B[:,j],w[:,j],sup,ne)[0],sup))
        scored.sort()
        sup=local_search(A,B[:,j],w[:,j],scored[0][1],ne)
        bc,ss,c=bic(A,B[:,j],w[:,j],sup,ne)
        masks[list(sup),j]=True; Cs[:,j]=c
    return masks,Cs

def simulate(C,z0,t,rtol=1e-9,atol=1e-11):
    def f(tt,z): return basis(z[None,:])[0]@C
    sol=solve_ivp(f,(float(t[0]),float(t[-1])),np.asarray(z0,float),t_eval=t,method='DOP853',rtol=rtol,atol=atol)
    if (not sol.success) or sol.y.shape[1]!=len(t) or not np.all(np.isfinite(sol.y)):
        return None
    return sol.y.T

def refine(C0,mask,Zobs,Z0,sig,t,max_nfev=80,rtol=1e-9,atol=1e-11):
    idx=np.where(mask) # tuple rows,cols
    # pack all active coefficients row-major by column
    idxs=[(i,j) for j in range(2) for i in np.where(mask[:,j])[0]]
    p=len(idxs)
    x0=np.array([C0[i,j] for i,j in idxs])
    def makeC(x):
        C=np.zeros((10,2))
        for v,(i,j) in zip(x,idxs): C[i,j]=v
        return C
    def resid(x):
        C=makeC(x); rr=[]
        for y,s,z0 in zip(Zobs,sig,Z0):
            pred=simulate(C,z0,t,rtol,atol)
            if pred is None: return np.ones(len(Zobs)*len(t)*2)*1e3
            rr.append(((pred-y)/s).ravel())
        return np.concatenate(rr)
    try:
        res=least_squares(resid,x0,method='trf',xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=max_nfev)
        C=makeC(res.x)
        return C,res
    except Exception:
        return makeC(x0),None

def solve_case(t,tr,tri,va,vai,mtrain,mval,verbose=False):
    Zs=list(tr)+list(va); S0=list(np.asarray(mtrain,dtype=float))+list(np.asarray(mval,dtype=float)); Ss=[np.tile(s,(len(t),1)) for s in S0]; Z0s=list(tri)+list(vai)
    A,B,w=make_weak(t,Zs,Ss,Z0s)
    masks,Cs=select_supports(A,B,w,len(Zs),len(t))
    # cap total selected <=10 if needed, prefer larger refined/weak coefs
    if masks.sum()>10:
        # iteratively drop smallest normalized weak coefficient among active
        while masks.sum()>10:
            vals=[]
            for i in range(10):
                for j in range(2):
                    if masks[i,j]: vals.append((abs(Cs[i,j]),i,j))
            vals.sort()
            _,i,j=vals[0]; masks[i,j]=False
    C,res=refine(Cs,masks,Zs,Z0s,S0,t)
    # zero tiny values, enforce cap
    C[np.abs(C)<1e-7]=0.0
    # if still >10, zero smallest abs values
    while np.count_nonzero(C)>10:
        idx=np.unravel_index(np.argmin(np.where(C!=0,np.abs(C),np.inf)),C.shape)
        C[idx]=0.0
    return C,masks,A,B,w

def main():
    import argparse, os, json
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--seed',type=int,default=0)
    args=ap.parse_args()
    inp=args.input; out=args.output
    man=json.load(open(os.path.join(inp,'manifest.json')))
    for case in man.get('cases',[]):
        cid=str(case['id'])
        d=os.path.join(inp,case['path'])
        meta=json.load(open(os.path.join(d,'metadata.json')))
        t=np.load(os.path.join(d,'t.npy')).astype(float)
        tr=np.load(os.path.join(d,'train.npy')).astype(float)
        va=np.load(os.path.join(d,'validation.npy')).astype(float)
        tri=np.load(os.path.join(d,'train_initial.npy')).astype(float)
        vai=np.load(os.path.join(d,'validation_initial.npy')).astype(float)
        ntr=tr.shape[0]; nva=va.shape[0]
        noise=meta.get('noise',{})
        st=np.asarray(noise.get('train_sigma',[]),dtype=float)
        sv=np.asarray(noise.get('validation_sigma',[]),dtype=float)
        if st.shape!=(ntr,2):
            st=np.tile(np.std(tr,axis=1),(1,1))
        if sv.shape!=(nva,2):
            sv=np.tile(np.std(va,axis=1),(1,1))
        st=np.maximum(st,1e-12); sv=np.maximum(sv,1e-12)
        try:
            C,masks,A,B,w=solve_case(t,tr,tri,va,vai,st,sv)
        except Exception:
            # conservative fallback: weak/full linear least squares, sparsified
            Zs=list(tr)+list(va); S0=list(st)+list(sv); Z0s=list(tri)+list(vai)
            Ss=[np.tile(s,(len(t),1)) for s in S0]
            A,B,w=make_weak(t,Zs,Ss,Z0s)
            C=np.zeros((10,2))
            for j in range(2):
                c=wls(A,B[:,j],w[:,j]); order=np.argsort(np.abs(c))[::-1][:10]
                m=np.zeros(10,bool); m[order]=True
                C[:,j]=wls(A,B[:,j],w[:,j],m)
        C=np.asarray(C,dtype=float)
        C[~np.isfinite(C)]=0.0
        C[np.abs(C)<1e-7]=0.0
        while np.count_nonzero(C)>10:
            idx=np.unravel_index(np.argmin(np.where(C!=0,np.abs(C),np.inf)),C.shape)
            C[idx]=0.0
        od=os.path.join(out,'cases',cid)
        os.makedirs(od,exist_ok=True)
        with open(os.path.join(od,'model.json'),'w') as f:
            json.dump({'coefficients':C.tolist()},f)

if __name__=='__main__':
    main()
