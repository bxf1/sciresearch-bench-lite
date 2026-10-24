#!/usr/bin/env python3
"""Sparse SPD solver for the Poisson benchmark.

Strategy
--------
The systems are 2-D 5-point Laplacian-like SPD matrices (n*n unknowns) with a
localized high-contrast inclusion.  Jacobi-preconditioned CG struggles on the
high-contrast region, so instead we use a *direct* sparse factorization
(SuperLU via scipy.sparse.linalg.splu) which is exact up to round-off:

  * one factorization per matrix, reused for all 4 RHS columns (block solve),
  * operator reuse across cases that share the same matrix (level-0 cases),
  * no iteration => residual ~ machine precision, well below 1e-8.

For very large n where a direct factorization would be too expensive we fall
back to incomplete-Cholesky-preconditioned CG (also shared across RHS).
"""

import argparse
import json
import os
import sys

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _hash_csr(A):
    """Cheap content hash of a CSR matrix for operator reuse across cases."""
    import hashlib

    h = hashlib.blake2b(digest_size=16)
    h.update(np.asarray(A.shape, dtype=np.int64).tobytes())
    h.update(np.ascontiguousarray(A.indptr, dtype=np.int64).tobytes())
    h.update(np.ascontiguousarray(A.indices, dtype=np.int64).tobytes())
    h.update(np.ascontiguousarray(A.data, dtype=np.float64).tobytes())
    return h.hexdigest()


def _ic0(A):
    """Incomplete Cholesky (IC(0)) preconditioner for a CSR SPD matrix.

    Returns a LinearOperator applying M^{-1} = (L L^T)^{-1}.
    """
    n = A.shape[0]
    A = A.tocsc()
    indptr, indices, data = A.indptr, A.indices, A.data

    # Build lower-triangular pattern of A (including diagonal).
    Lp = [0] * (n + 1)
    Li = []
    Lx = []
    diag_pos = [0] * n
    for i in range(n):
        cols = []
        vals = []
        for k in range(indptr[i], indptr[i + 1]):
            j = indices[k]
            if j <= i:
                cols.append(j)
                vals.append(data[k])
        # ensure sorted ascending (CSC column i is already sorted by row)
        order = np.argsort(cols, kind="stable")
        cols = [cols[o] for o in order]
        vals = [vals[o] for o in order]
        Lp[i + 1] = Lp[i] + len(cols)
        Li.extend(cols)
        Lx.extend(vals)
        diag_pos[i] = Lp[i + 1] - 1  # diagonal is last (largest col index)

    Li = np.asarray(Li, dtype=np.int64)
    Lx = np.asarray(Lx, dtype=np.float64)
    Lp = np.asarray(Lp, dtype=np.int64)

    # In-place IC(0) factorization (row-wise, using column storage of L).
    # We work with L stored by columns (CSC) which is what we built.
    for i in range(n):
        s = Lp[i]
        e = Lp[i + 1]
        # subtract contributions from previous columns
        for p in range(s, e - 1):  # all but diagonal
            k = Li[p]
            # dot product of row i and row k of L over common columns < k
            acc = 0.0
            pk = Lp[k]
            ek = Lp[k + 1]
            # walk both column lists
            a = s
            b = pk
            while a < e - 1 and b < ek - 1:
                ja = Li[a]
                jb = Li[b]
                if ja == jb:
                    acc += Lx[a] * Lx[b]
                    a += 1
                    b += 1
                elif ja < jb:
                    a += 1
                else:
                    b += 1
            Lx[p] = (Lx[p] - acc) / Lx[diag_pos[k]]
        d = Lx[e - 1]
        for p in range(s, e - 1):
            d -= Lx[p] * Lx[p]
        if d <= 0:
            d = 1e-12
        Lx[e - 1] = np.sqrt(d)

    L = sp.csc_matrix((Lx, Li, Lp), shape=(n, n))
    solve_L = spla.splu(L, permc_spec="NATURAL", diag_pivot_thresh=0.0,
                        options=dict(SymmetricMode=True))
    solve_LT = spla.splu(L.T.tocsc(), permc_spec="NATURAL",
                         diag_pivot_thresh=0.0,
                         options=dict(SymmetricMode=True))

    def apply(r):
        return solve_LT.solve(solve_L.solve(r))

    return spla.LinearOperator((n, n), matvec=apply, dtype=np.float64)


def _pcg(A, M, B, rtol=1e-12, maxiter=20000):
    """Preconditioned CG for multiple RHS columns simultaneously."""
    n, k = B.shape
    X = np.zeros((n, k))
    R = B.copy()
    Z = M @ R
    P = Z.copy()
    rz = np.einsum("ij,ij->j", R, Z)
    bnorm = np.linalg.norm(B, axis=0)
    bnorm[bnorm == 0] = 1.0
    active = np.ones(k, dtype=bool)
    for _ in range(maxiter):
        if not active.any():
            break
        AP = A @ P
        pAp = np.einsum("ij,ij->j", P, AP)
        alpha = np.where(active & (pAp != 0), rz / np.where(pAp == 0, 1, pAp), 0.0)
        X += P * alpha
        R -= AP * alpha
        res = np.linalg.norm(R, axis=0) / bnorm
        active = res > rtol
        if not active.any():
            break
        Z = M @ R
        rz_new = np.einsum("ij,ij->j", R, Z)
        beta = np.where(rz != 0, rz_new / np.where(rz == 0, 1, rz), 0.0)
        P = Z + P * beta
        rz = rz_new
    return X


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(os.path.join(args.input, "manifest.json")) as f:
        manifest = json.load(f)

    cache = {}  # matrix hash -> factorization / preconditioner

    for case in manifest["cases"]:
        cid = case["id"]
        cdir = os.path.join(args.input, case["path"])
        A = sp.load_npz(os.path.join(cdir, "A.npz")).tocsr()
        A.sort_indices()
        rhs = np.load(os.path.join(cdir, "rhs.npy"))
        rhs = np.asarray(rhs, dtype=np.float64)
        if rhs.ndim == 1:
            rhs = rhs[:, None]

        key = _hash_csr(A)
        entry = cache.get(key)

        if entry is None:
            n = A.shape[0]
            # Direct factorization is exact and fast for these sizes.
            if n <= 4_000_000:
                try:
                    lu = spla.splu(A.tocsc(), permc_spec="MMD_AT_PLUS_A",
                                   diag_pivot_thresh=0.0,
                                   options=dict(SymmetricMode=True))
                    entry = ("lu", lu)
                except Exception:
                    entry = ("pcg", _ic0(A))
            else:
                entry = ("pcg", _ic0(A))
            cache[key] = entry

        kind, obj = entry
        if kind == "lu":
            X = obj.solve(rhs)
        else:
            X = _pcg(A, obj, rhs)

        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X[:, None]
        X[~np.isfinite(X)] = 0.0

        outdir = os.path.join(args.output, "cases", cid)
        os.makedirs(outdir, exist_ok=True)
        np.save(os.path.join(outdir, "solution.npy"),
                np.ascontiguousarray(X, dtype="<f8"))


if __name__ == "__main__":
    main()
