# Sparse linear systems: correctness and complete execution time

Implement a reusable program that solves every system in an input batch. Each
case supplies a real, symmetric positive definite CSR matrix `A.npz`, four
right-hand sides in little-endian float64 `rhs.npy`, and `metadata.json`.
For grid width n, A has shape `(n*n,n*n)` and B has shape `(n*n,4)`.
Indices use row-major `i*n+j`. Coordinates and values are dimensionless.
Some easy cases share a fixed operator and have independent right-hand sides;
medium and hard cases also use unseen operators.

The entry point is:

```sh
python solve.py --input /input --output /output --seed 0
```

Read `/input/manifest.json`; `cases` lists each `id`, relative input `path`,
and difficulty `level`. The solver seed is not a generator seed. For each case
write only `cases/<id>/solution.npy` of shape `(n*n,4)`, little-endian float64,
with finite real values. Do not write a score or diagnostics into the output
directory. JSON, CSV, NPY and numeric/sparse NPZ input formats are supported;
pickle, object arrays, complex values, links, special files and escaping paths
are forbidden. Source is at most 20 MiB and 1000 regular files; numeric outputs
are at most 256 MiB, and temporary space at most 64 MiB.

Each solution column must have relative residual at most `1e-8` and relative
error against the private discrete manufactured solution at most `1e-5`.
Relative-error denominators are `max(norm(truth),1e-12)`. All 12 final cases
must pass. Public evaluation reports independently computed residuals,
complete execution time, memory and comparison with the shared Jacobi-CG
baseline. Public feedback does not reveal private solution errors.

The shared comparison program uses Jacobi-preconditioned CG with
`rtol=1e-10`, `atol=0`, `maxiter=10000`, independently on all four columns.
Both comparator and submission must meet identical correctness and resource
requirements. Trusted timing includes Python startup, imports, input/output,
preprocessing, format conversion, factorization and solving until all child
processes exit. It excludes container preparation and trusted scoring, which
are reported separately. Comparator B and candidate C run in fresh workers in
the order `B,C,C,B,B,C`; speedup is the ratio of median times. A new container
does not imply a cold host page cache.

The frozen task contract selects either `efficiency_gate_1.5` (all cases correct
and speedup at least 1.5), or `accuracy_with_efficiency_diagnostic` (all cases
correct; speedup reported separately). If all cases are correct, the continuous
efficiency score is `100*clip(log(speedup)/log(8),0,1)`; otherwise it is zero.
No numerical artifact may supply its own official time, memory, or score.

Research has 30 minutes, 4 vCPU, 4 GiB and at most 20 registered public
evaluations. Each accepted evaluation consumes one request and processes all
six dev cases. Candidate workers have 1 vCPU, 4 GiB, no swap, one BLAS/OpenMP
thread, no network, and a 60-second complete-batch limit. Use
`bench evaluate <relative-source-dir>` to register a source snapshot and receive
feedback; use `bench finalize <candidate-id>` to select a snapshot already
evaluated in this session. Invalid finalize IDs are
submission failures. If no finalize occurs, the latest valid evaluated snapshot
is selected. Your first valid and final candidates are retained, including
valid candidates that fail scientific criteria. Implement, evaluate, and keep
an evidence-based experiment record within the common budget.


# Additional detailed method guidance

Start with sparse LU and reuse each factorization across its four right-hand
sides. Convert each CSR matrix to CSC once. Use a fill-reducing COLAMD column
ordering, factorize once, and solve the dense four-column RHS with the same
factors. Keep the result in original coordinates and row ordering. Check all
four residuals with the original A and B before writing the required array.

Non-executable pseudocode:

1. For each manifest case, load A and B.
2. Convert A to CSC and construct a sparse LU factorization using COLAMD.
3. Apply this one factorization to all four columns of B.
4. Check relative residuals `norm(A*u_j-b_j)/max(norm(b_j),1e-12)`.
5. Save the `(n*n,4)` solution as little-endian float64.
6. Register the complete program for trusted dev evaluation and compare its
   full execution time against the shared Jacobi-CG comparator.

Avoid repeating symbolic ordering and factorization for each RHS. Include
format conversion, factorization and I/O when investigating total cost.
You may explore further changes if the public measurements justify them;
every final program must also work on new matrices and right-hand sides.
