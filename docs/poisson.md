# T3: discrete sparse systems

The v0.3 task supplies A and four-column B and asks for U satisfying AU=B.
Easy/medium/hard grids have n=32/64/128 and coefficient contrasts 1/30/300.
Three disks use independent uniform centers in `[.2,.8]^2` and radii in
`[.08,.18]`; the coefficient is `1+(contrast-1)*indicator(union(disks))`.
Overlaps do not accumulate. With h=1/(n+1), interior weights are the harmonic
mean of neighboring coefficients divided by h². Each boundary face adds the
adjacent internal coefficient divided by h² to the diagonal. Indexing is
`i*n+j`. Positive edge and boundary weights give the discrete energy identity
and SPD; small dense Cholesky is an auxiliary check, not the proof.

Private generation draws four independent standard-normal solution columns
from a random stream separate from geometry and stores B=fl(AU*) in binary64.
This is a discrete manufactured solution, not a continuous PDE error test.
The corresponding source can be rough. Easy operators repeat by design, so
easy split generalization concerns RHS only. Medium and hard datasets require
distinct effective coefficient fields and systems. The generator returns
separate fingerprints for effective coefficients, operator, latent instance,
and `(A,B)` so the split auditor can enforce those distinctions.

Public case files are `A.npz`, `rhs.npy`, `metadata.json`. Private `truth.npz`
contains `solution`, `coefficient`, `disks`, `independent_rhs`,
`interior_weights`, and `boundary_weights`; `qc.json` contains the checks.
No private generation artifact belongs in R/W images or mounts.

QC checks finite data, symmetry, nonpositive off-diagonals, positive weights,
an independent node-centered flux application, an independent 8×8 row stencil,
and small-grid Cholesky. Exact Decimal sums bound the saved binary64 diagonal
defect. The conservative solution discrepancy bound is
`gamma10 * max_absolute_row_sum / (8-max_diagonal_defect)` under binary64
normal rounding without significant overflow/underflow. Each generated case
requires this bound below `1e-7`, well inside the `1e-5` scoring threshold.
Generation never solves the system to define truth or accepts/rejects an
instance based on baseline recovery performance.

The private scorer first verifies trusted dimensions, finite GT, manufacturing
consistency, independent RHS agreement and the stored rounding margin. A
trusted-input defect raises `TruthError`, which must invalidate evaluation.
Malformed output is an ordinary artifact failure. Finite output whose arithmetic
overflows remains a valid numeric artifact with a scientific failure. The
scorer reports four columnwise residuals and solution errors. It does not run
submitted code and does not accept candidate-reported resource or time values.

The standalone baseline has three methods: unpreconditioned CG, Jacobi-CG,
and one COLAMD sparse LU reused across all four columns. Both CG methods use
`rtol=1e-10,atol=0,maxiter=10000`. There is no private helper import. The common
worker interface and trusted full-batch timer must run all three methods.
The full protocol, performance profile calibration and final efficiency
reward live in the host runner. Per-case numeric success alone is not a
claim of resource compliance or task performance success.

Tests use diagnostic seeds outside the reserved pilot range, separate from
formal split namespaces. They cover all difficulty QC, repeated easy operators
with different RHS, overlap/boundary semantics, manufactured truth, all three
solvers, zero solutions, controlled perturbations, invalid shape/dtype/NaN,
finite overflow and trusted-data corruption. Test execution evidence and
formal baseline/calibration status must be read from the run logs; this data
card by itself does not certify containers or Agent experiments.
