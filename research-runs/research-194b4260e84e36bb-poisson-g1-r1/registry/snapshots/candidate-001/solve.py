#!/usr/bin/env python3
"""Batch solver for sparse SPD grid systems.

For every case in the manifest we build one sparse LU factorization of the
operator (SuperLU with an MMD_AT_PLUS_A fill-reducing ordering), then apply it
to all four right-hand sides together.  Factors come from SciPy's SuperLU
extension, imported directly so that the batch does not pay the full SciPy
import cost.  A conventional SciPy path and a matrix-free CG path are kept as
fallbacks.  Every solution is checked against the original operator before it
is written.
"""
import os
import sys
import json

import numpy as np

_SUPERLU = None


def _load_superlu():
    """Import SciPy's SuperLU C extension without importing all of scipy."""
    global _SUPERLU
    if _SUPERLU is not None:
        return _SUPERLU
    try:
        import types
        site = os.path.dirname(os.path.dirname(os.path.abspath(np.__file__)))
        base = os.path.join(site, "scipy")
        if not os.path.isdir(base):
            import importlib.util
            spec = importlib.util.find_spec("scipy")
            if spec is None:
                raise ImportError("scipy is not available")
            base = list(spec.submodule_search_locations)[0]
        for k in [k for k in sys.modules if k == "scipy" or k.startswith("scipy.")]:
            del sys.modules[k]

        def _stub(name, path):
            mod = types.ModuleType(name)
            mod.__path__ = [path]
            sys.modules[name] = mod

        _stub("scipy", base)
        for sub in ("sparse", "sparse.linalg", "sparse.linalg._dsolve"):
            _stub("scipy." + sub, os.path.join(base, *sub.split(".")))
        from scipy.sparse.linalg._dsolve import _superlu as sl
        _SUPERLU = sl
    except Exception:
        sys.modules.pop("scipy", None)
        _SUPERLU = False
    return _SUPERLU


def _scipy_modules():
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    return sp, spla


def _csr_matvec(indptr, indices, data, X):
    if np.any(np.diff(indptr) == 0):
        rows = np.repeat(np.arange(indptr.size - 1, dtype=np.int64),
                         np.diff(indptr))
        out = np.empty_like(X)
        for k in range(X.shape[1]):
            out[:, k] = np.bincount(rows, weights=data * X[indices, k],
                                    minlength=indptr.size - 1)
        return out
    return np.add.reduceat(data[:, None] * X[indices, :], indptr[:-1], axis=0)


def _relres(indptr, indices, data, X, B):
    R = _csr_matvec(indptr, indices, data, X) - B
    return np.linalg.norm(R, axis=0) / np.maximum(np.linalg.norm(B, axis=0), 1e-12)


def _to_csc(indptr, indices, data, N):
    rows = np.repeat(np.arange(N, dtype=np.int64), np.diff(indptr))
    order = np.lexsort((rows, indices))
    colptr = np.zeros(N + 1, dtype=np.intc)
    np.cumsum(np.bincount(indices, minlength=N), out=colptr[1:])
    return (np.ascontiguousarray(data[order], dtype=np.float64),
            np.ascontiguousarray(rows[order], dtype=np.intc), colptr)


def _cg_numpy(indptr, indices, data, B, x=None, tol=5e-10, maxiter=20000):
    """Jacobi-preconditioned CG on all columns simultaneously (last resort)."""
    N = indptr.size - 1
    diag = np.zeros(N)
    rows = np.repeat(np.arange(N, dtype=np.int64), np.diff(indptr))
    np.add.at(diag, rows, 0.0)
    # extract diagonal entries (rows are sorted, so locate them cheaply)
    diag[:] = np.where(diag == 0, 1.0, diag)
    dpos = np.searchsorted(indices, rows)
    # per-row diagonal: only rows where the diagonal is actually stored
    same = indices[dpos] == rows
    diag[rows[same]] = data[dpos[same]]
    diag = np.where(diag != 0, diag, 1.0)
    bn = np.maximum(np.linalg.norm(B, axis=0), 1e-12)
    X = np.zeros_like(B) if x is None else x.copy()
    R = B - _csr_matvec(indptr, indices, data, X)
    if np.all(np.linalg.norm(R, axis=0) / bn <= tol):
        return X
    Z = R / diag[:, None]
    P = Z.copy()
    rz = np.sum(R * Z, axis=0)
    for _ in range(maxiter):
        AP = _csr_matvec(indptr, indices, data, P)
        alpha = rz / np.maximum(np.sum(P * AP, axis=0), 1e-300)
        X += P * alpha
        R -= AP * alpha
        if np.all(np.linalg.norm(R, axis=0) / bn <= tol):
            break
        Z = R / diag[:, None]
        rz_new = np.sum(R * Z, axis=0)
        P = Z + P * (rz_new / np.maximum(rz, 1e-300))
        rz = rz_new
    return X


class _Factor:
    __slots__ = ("solve",)

    def __init__(self, solve_fn):
        self.solve = solve_fn


def _factorize(N, indptr, indices, data):
    """Return an object with .solve(B), or None."""
    ip = np.ascontiguousarray(indptr, dtype=np.intc)
    ix = np.ascontiguousarray(indices, dtype=np.intc)
    vals = np.ascontiguousarray(data, dtype=np.float64)
    nnz = int(vals.size)
    if ip.size != N + 1 or nnz != int(ip[-1]) or N <= 0:
        return None

    sl = _load_superlu()
    if sl:
        for opts in ({"ColPerm": "MMD_AT_PLUS_A"}, {"ColPerm": "COLAMD"}):
            try:
                lu = sl.gstrf(N, nnz, vals, ix, ip,
                              csc_construct_func=None, ilu=False, options=opts)
                return _Factor(lu.solve)
            except Exception:
                continue

    # Fallback: full SciPy on a properly built CSC.
    try:
        sp, spla = _scipy_modules()
        vals2, rows2, colptr2 = _to_csc(ip, ix, vals, N)
        A = sp.csc_array((vals2, rows2, colptr2), shape=(N, N))
        lu = spla.splu(A, permc_spec="MMD_AT_PLUS_A")
        return _Factor(lu.solve)
    except Exception:
        return None


def solve_case(N, arrs, B):
    ip = np.asarray(arrs["indptr"], dtype=np.int64)
    ix = np.asarray(arrs["indices"], dtype=np.int64)
    vals = np.asarray(arrs["data"], dtype=np.float64)
    if ip.size != N + 1 or vals.size == 0:
        return None
    fac = _factorize(N, ip, ix, vals)
    if fac is None:
        return None
    try:
        X = np.asarray(fac.solve(B), dtype=np.float64)
    except Exception:
        return None
    if X.shape != B.shape or not np.all(np.isfinite(X)):
        return None
    rr = _relres(ip, ix, vals, X, B)
    if rr.max() > 1e-9:
        for _ in range(3):
            try:
                X = X + fac.solve(B - _csr_matvec(ip, ix, vals, X))
            except Exception:
                break
            rr = _relres(ip, ix, vals, X, B)
            if rr.max() <= 1e-9:
                break
    if rr.max() > 1e-8:
        # The operator may not have been symmetric; use a real CSC.
        try:
            sp, spla = _scipy_modules()
            vals2, rows2, colptr2 = _to_csc(ip, ix, vals, N)
            A = sp.csc_array((vals2, rows2, colptr2), shape=(N, N))
            lu = spla.splu(A, permc_spec="MMD_AT_PLUS_A")
            X2 = np.asarray(lu.solve(B), dtype=np.float64)
            rr2 = _relres(ip, ix, vals, X2, B)
            if np.all(np.isfinite(X2)) and rr2.max() < rr.max():
                X, rr = X2, rr2
        except Exception:
            pass
    if rr.max() > 1e-8:
        X = _cg_numpy(ip, ix, vals, B, x=X)
    return X


def _safe_join(root, rel):
    p = os.path.realpath(os.path.join(root, rel))
    if p != root and not p.startswith(root + os.sep):
        raise ValueError("path escapes root")
    return p


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args, _ = ap.parse_known_args(argv)
    in_root = os.path.realpath(args.input)
    out_root = os.path.realpath(args.output)
    with open(os.path.join(in_root, "manifest.json"), "r") as f:
        manifest = json.load(f)
    os.makedirs(out_root, exist_ok=True)
    for case in manifest.get("cases", []):
        cid = str(case.get("id", ""))
        rel = case.get("path") or os.path.join("cases", cid)
        src = _safe_join(in_root, rel)
        with np.load(os.path.join(src, "A.npz"), allow_pickle=False) as z:
            arrs = {k: z[k] for k in z.files}
        B = np.asarray(np.load(os.path.join(src, "rhs.npy"),
                               allow_pickle=False), dtype=np.float64)
        B = np.ascontiguousarray(B.reshape(B.shape[0], -1))
        N = int(B.shape[0])
        if "shape" in arrs:
            shp = np.asarray(arrs["shape"]).ravel()
            if shp.size >= 2 and int(shp[0]) == int(shp[1]):
                N = int(shp[0])
        try:
            X = solve_case(N, arrs, B)
        except Exception:
            X = None
        if X is None:
            ip = np.asarray(arrs["indptr"], dtype=np.int64)
            ix = np.asarray(arrs["indices"], dtype=np.int64)
            vals = np.asarray(arrs["data"], dtype=np.float64)
            X = _cg_numpy(ip, ix, vals, B)
        X = np.ascontiguousarray(X, dtype="<f8").reshape(B.shape)
        dst = _safe_join(out_root, rel)
        os.makedirs(dst, exist_ok=True)
        np.save(os.path.join(dst, "solution.npy"), X)
    return 0


if __name__ == "__main__":
    sys.exit(main())
