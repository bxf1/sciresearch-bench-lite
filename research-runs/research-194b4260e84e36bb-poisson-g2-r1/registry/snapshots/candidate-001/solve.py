#!/usr/bin/env python3
"""Solve batched SPD sparse linear systems with reusable direct factorization.

Strategy:
  * read manifest + cases
  * group cases that share an identical operator (hash + exact compare)
  * one sparse LU/Cholesky-like factorization per distinct operator
  * solve all right-hand sides of all cases sharing that operator in one shot
  * verify residual; one step of iterative refinement if needed
  * write cases/<id>/solution.npy  (little-endian float64)
"""
import os
import sys
import json
import hashlib

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


def load_csr(path):
    A = sp.load_npz(os.path.join(path, "A.npz"))
    if not sp.isspmatrix_csr(A):
        A = A.tocsr()
    A.sum_duplicates()
    if not A.has_sorted_indices:
        A.sort_indices()
    return A


def operator_key(A):
    h = hashlib.sha256()
    h.update(np.asarray(A.shape, dtype=np.int64).tobytes())
    h.update(np.ascontiguousarray(A.indptr).tobytes())
    h.update(np.ascontiguousarray(A.indices).tobytes())
    h.update(np.ascontiguousarray(A.data, dtype=np.float64).tobytes())
    return h.hexdigest()


def same_operator(A, B):
    return (A.shape == B.shape
            and np.array_equal(A.indptr, B.indptr)
            and np.array_equal(A.indices, B.indices)
            and np.array_equal(A.data, B.data))


def factorize(A):
    C = A.tocsc()
    # MMD on A^T+A is the best of scipy's built-in orderings for grid matrices
    try:
        return spla.splu(C, permc_spec="MMD_AT_PLUS_A",
                         diag_pivot_thresh=0.0, options=dict(SymmetricMode=True))
    except Exception:
        return spla.splu(C, permc_spec="MMD_AT_PLUS_A")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    inp = args.input
    out = args.output
    with open(os.path.join(inp, "manifest.json"), "r") as fh:
        manifest = json.load(fh)
    cases = manifest.get("cases", manifest)

    # ---- load -------------------------------------------------------------
    loaded = []
    for c in cases:
        cid = str(c["id"])
        path = os.path.join(inp, str(c["path"]))
        A = load_csr(path)
        rhs = np.load(os.path.join(path, "rhs.npy"))
        rhs = np.ascontiguousarray(rhs, dtype=np.float64)
        if rhs.ndim == 1:
            rhs = rhs[:, None]
        loaded.append((cid, A, rhs))

    # ---- group by identical operator -------------------------------------
    groups = []          # list of dict(key, A, members=[(idx, rhs)])
    by_key = {}
    for idx, (cid, A, rhs) in enumerate(loaded):
        k = operator_key(A)
        g = by_key.get(k)
        if g is not None and not same_operator(g["A"], A):
            g = None
        if g is None:
            g = {"A": A, "members": []}
            by_key[k] = g
            groups.append(g)
        g["members"].append((cid, rhs))

    # ---- factor once per distinct operator, solve all RHS together --------
    sols = {}
    for g in groups:
        A = g["A"]
        members = g["members"]
        B = np.concatenate([m[1] for m in members], axis=1)
        lu = factorize(A)
        X = lu.solve(np.asfortranarray(B))
        if not np.all(np.isfinite(X)):
            X = lu.solve(B)
        # residual check / iterative refinement
        R = B - A @ X
        nb = np.linalg.norm(B, axis=0)
        nb[nb == 0.0] = 1.0
        if np.max(np.linalg.norm(R, axis=0) / nb) > 1e-10:
            X = X + lu.solve(np.asfortranarray(R))
        off = 0
        for cid, rhs in members:
            k = rhs.shape[1]
            sols[cid] = np.array(X[:, off:off + k], dtype="<f8", order="C")
            off += k

    # ---- write ------------------------------------------------------------
    for cid, X in sols.items():
        d = os.path.join(out, "cases", cid)
        os.makedirs(d, exist_ok=True)
        np.save(os.path.join(d, "solution.npy"), np.ascontiguousarray(X, dtype="<f8"))


if __name__ == "__main__":
    main()
