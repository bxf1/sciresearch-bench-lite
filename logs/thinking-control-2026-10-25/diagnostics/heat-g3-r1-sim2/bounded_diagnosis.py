"""Reproduce the first nonterminating branch using public inputs, without running the loop."""
import ast
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize_scalar

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
source = OUT / 'sim2.py'
tree = ast.parse(source.read_text())
# Only the two inspected finite fitting helpers are needed. Never execute
# constrained(), evaluate(), or the source file's top-level experiment loops.
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('logev', 'fitq')]
assert len(helpers) == 2
namespace = {'np': np, 'K': 32, 'minimize_scalar': minimize_scalar}
exec(compile(ast.Module(body=helpers, type_ignores=[]), str(source), 'exec'), namespace)
cases = []
for path in sorted((ROOT / 'tasks/heat/environment/public-dev/cases').iterdir()):
    meta = json.loads((path / 'metadata.json').read_text())
    obs = np.genfromtxt(path / 'observations.csv', delimiter=',', names=True)
    cases.append((path.name, meta, obs['x'], obs['t']))
assert len(cases) == 6
rng = np.random.default_rng(2024)
k = np.arange(1, 33, dtype=float)
# Advance exactly the draws made by the completed first 'mean' method:
# six public geometries times 100 synthetic repetitions. No solves needed.
for _, meta, x, _ in cases:
    for _ in range(100):
        rng.normal(size=32)
        rng.normal(scale=meta['sigma'], size=len(x))
for case_id, meta, x, t in cases:
    sig = meta['sigma']
    A = np.sin(np.pi * np.outer(x, k)) * np.exp(-meta['kappa'] * np.pi**2 * np.outer(t, k*k))
    for rep in range(100):
        raw = rng.normal(size=32) * k**(-1.75)
        truth = raw * np.sqrt(2 / np.sum(raw**2))
        y = A @ truth + rng.normal(scale=sig, size=len(x))
        q, shape = namespace['fitq'](A, y, sig, 2.0)
        B = A.T @ A + sig**2 * np.diag(1 / (q * shape))
        g = A.T @ y
        eigenvalues = np.linalg.eigvalsh(B)
        lo = -eigenvalues[0] * (1 - 1e-9)
        def f(lam):
            return float(np.sum(np.linalg.solve(B + lam * np.eye(32), g)**2) - np.sqrt(2)**2)
        f0, midpoint = f(0), lo / 2
        if f0 < -1e-10 and f(midpoint) < 0:
            samples = []
            hi = lo
            for iteration in range(64):
                mid = hi / 2
                value = f(mid)
                assert value < 0
                if iteration < 5 or iteration == 63:
                    samples.append({'iteration': iteration + 1, 'hi_before': float(hi), 'mid': float(mid), 'f_mid': value})
                hi = mid
            for iteration in range(2000):
                mid = hi / 2
                if mid == hi:
                    break
                hi = mid
            assert hi == 0 and f(hi) < 0
            result = {'status': 'nonterminating_branch_reproduced', 'checked_at': time.time(),
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'case_id': case_id, 'method': 'con', 'p_true': 1.75, 'p_est': 2.0, 'rep_zero_based': rep,
                'prior_completed_mean_repetitions': 600, 'f_zero': f0, 'lambda_lower_bound': float(lo),
                'first_midpoint_f': f(lo / 2), 'bounded_iterations': samples,
                'floating_point_fixed_point': float(hi), 'f_at_fixed_point': f(hi),
                'mathematical_reason': 'B is positive definite and f(lambda)=sum_i((Q.T@g)_i/(eigenvalue_i+lambda))^2-2 decreases as lambda increases. When f(hi/2)<0, replacing hi by hi/2 moves toward zero, so f remains negative. Rounding eventually fixes hi=mid=-0.0; the loop can never reach its else/break.',
                'mode': 'Host-side bounded diagnosis using original seed and public inputs; no signal, tracing, modification, or feedback to the running researcher.',
                'hidden_data_accessed': False, 'new_scientific_score': False}
            (OUT / 'diagnosis.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result))
            raise SystemExit(0)
raise RuntimeError('Expected branch not reproduced; inspect evidence before concluding a live loop.')
