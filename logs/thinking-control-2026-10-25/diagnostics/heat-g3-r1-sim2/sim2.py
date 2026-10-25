import numpy as np, json, glob, os
from scipy.optimize import minimize_scalar, brentq

rng = np.random.default_rng(2024)
cases = []
for d in sorted(glob.glob('/input/cases/*')):
    meta = json.load(open(d + '/metadata.json'))
    a = np.genfromtxt(d + '/observations.csv', delimiter=',', names=True)
    cases.append((os.path.basename(d)[:4], meta, a['x'], a['t'], a['y']))

K = 32
k = np.arange(1, K+1, dtype=float)
tg = np.arange(1, 257)/257

def logev(A, y, sig, C):
    As = A*np.sqrt(C)[None, :]
    B = np.eye(K)+(As.T@As)/sig**2
    sign, ld = np.linalg.slogdet(B)
    z = As.T@y
    q = y@y/sig**2 - z@np.linalg.solve(sig**2*np.eye(K)+As.T@As, z)/sig**2
    return -0.5*(len(y)*np.log(2*np.pi*sig**2)+ld+q)

def fitq(A, y, sig, p):
    kk = np.arange(1, A.shape[1]+1, dtype=float)
    f = lambda lq: -logev(A, y, sig, np.exp(lq)*kk**(-2*p))
    r = minimize_scalar(f, bounds=(-4, 5), method='bounded', options={'xatol': 1e-4})
    return np.exp(r.x), kk**(-2*p)

def post(A, y, sig, C):
    B = A.T@A + sig**2*np.diag(1/C)
    return np.linalg.solve(B, A.T@y)

def constrained(A, y, sig, C, norm=np.sqrt(2)):
    P = sig**2*np.diag(1/C)
    B = A.T@A + P
    g = A.T@y
    ev = np.linalg.eigvalsh(B)
    lo = -ev[0]*(1-1e-9)
    def c_of(lam):
        return np.linalg.solve(B+lam*np.eye(len(g)), g)
    f = lambda lam: np.sum(c_of(lam)**2)-norm**2
    f0 = f(0)
    if abs(f0) < 1e-10:
        return c_of(0)
    if f0 > 0:
        hi = max(ev[-1],1)*2+1
        while f(hi) > 0:
            hi *= 2
        lam = brentq(f, 0, hi, xtol=1e-10)
    else:
        hi = lo
        # f -> +inf near lo
        step = (hi-0)/2
        while True:
            mid = (0+hi)/2
            if f(mid) < 0:
                hi = mid
            else:
                break
        lam = brentq(f, hi, 0, xtol=1e-10)
    return c_of(lam)

def evaluate(c, p_est, method, p_true=2.0, nrep=100):
    name, meta, x, t, yobs = c
    kap = meta['kappa']; sig = meta['sigma']; tf = meta['future_time']
    A = np.sin(np.pi*np.outer(x, k))*np.exp(-kap*np.pi**2*np.outer(t, k*k))
    Phi0 = np.sin(np.pi*np.outer(tg, k))
    Phif = np.sin(np.pi*np.outer(tg, k))*np.exp(-kap*np.pi**2*np.outer(tf, k*k))
    out = []
    for rep in range(nrep):
        raw = rng.normal(size=K)*k**(-p_true)
        truth = raw*np.sqrt(2/np.sum(raw**2))
        y = A@truth + rng.normal(scale=sig, size=len(x))
        q, shape = fitq(A, y, sig, p_est)
        C = q*shape
        est = post(A, y, sig, C)
        if method == 'con':
            est = constrained(A, y, sig, C)
        elif method == 'rescale':
            est = est*np.sqrt(2/np.sum(est**2))
        elif method == 'tail':
            # keep low 8 modes, scale high tail to fill remaining norm
            low = est[:8].copy()
            rest = est[8:].copy()
            rem = 2 - np.sum(low**2)
            if rem > 0:
                if np.sum(rest**2) > 0:
                    rest *= np.sqrt(rem/np.sum(rest**2))
                else:
                    rest = np.sqrt(rem/K)*np.ones(K-8)
                est = np.r_[low, rest]
        u = Phi0@est; ut = Phi0@truth
        uf = Phif@est; uft = Phif@truth
        ei = np.linalg.norm(u-ut)/max(np.linalg.norm(ut), 1e-12)
        ef = np.linalg.norm(uf-uft)/max(np.linalg.norm(uft), 1e-12)
        out.append((ei, ef))
    return np.array(out)

for p_true in [1.75, 2.0, 2.25]:
    print('=== ptrue', p_true)
    for pest in [2.0, 2.25]:
        for method in ['mean','con','rescale','tail']:
            allout=[]
            for c in cases:
                allout.append(evaluate(c,pest,method,p_true,nrep=100))
            allout=np.vstack(allout)
            print('pest',pest,method,'med',np.round(np.median(allout,axis=0),4),'90',np.round(np.quantile(allout,.9,axis=0),4),'99',np.round(np.quantile(allout,.99,axis=0),4),'max',np.round(allout.max(axis=0),4),'fails',round(np.mean(allout[:,0]>.15),4),round(np.mean(allout[:,1]>.03),4))
