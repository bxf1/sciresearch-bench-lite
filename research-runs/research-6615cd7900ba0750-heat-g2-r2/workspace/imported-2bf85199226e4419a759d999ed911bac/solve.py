import argparse, json, os
import numpy as np

def solve_case(cdir, out_path):
    meta = json.load(open(os.path.join(cdir, 'metadata.json')))
    kappa = float(meta['kappa']); sigma = float(meta['sigma'])
    data = np.genfromtxt(os.path.join(cdir, 'observations.csv'), delimiter=',', names=True)
    x = np.atleast_1d(data['x']).astype(float)
    t = np.atleast_1d(data['t']).astype(float)
    y = np.atleast_1d(data['y']).astype(float)
    K = 32
    ks = np.arange(1, K+1)
    lam = kappa*np.pi**2*ks**2
    # design: rows (obs, mode) = sin(pi k x) * exp(-lam t)
    A = np.sin(np.pi*np.outer(x, ks)) * np.exp(-np.outer(t, lam))
    # ridge with tiny regularization for stability
    AtA = A.T@A
    reg = 1e-10*np.trace(AtA)/K
    c = np.linalg.solve(AtA + reg*np.eye(K), A.T@y)
    grid = np.load(os.path.join(cdir, 'target_grid.npy')).astype(float)
    u0 = np.sin(np.pi*np.outer(grid, ks)) @ c
    u0 = np.asarray(u0, dtype='<f8').reshape(256)
    np.save(out_path, u0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    man = json.load(open(os.path.join(a.input, 'manifest.json')))
    for case in man['cases']:
        cdir = os.path.join(a.input, case['path'])
        odir = os.path.join(a.output, 'cases', case['id'])
        os.makedirs(odir, exist_ok=True)
        solve_case(cdir, os.path.join(odir, 'u0.npy'))

if __name__ == '__main__':
    main()
