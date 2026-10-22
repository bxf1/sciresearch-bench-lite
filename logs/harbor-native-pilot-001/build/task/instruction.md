PILOT EXECUTION CONTRACT (overrides formal-study resources/budgets in common):
This is a single infrastructure/research-loop pilot using only six public development
cases at /input. It is not a formal G1/G2/G3 study and accesses no hidden/final-test
truth or scores. You have 600 seconds of TOTAL wall time, including evaluation
waits, at most FOUR accepted bench evaluations (including failed submissions), and
12 model turns. R has 1 CPU/1 GiB; workers retain the published worker contract.
Work only in /workspace as researcher. Python/NumPy/SciPy are preinstalled.
The network allows only the model endpoint. Do not inspect credentials, environment
variables, other directories, host/container management, or private data. Do not
install dependencies or start background processes.
Implement a legitimate solver from the common task and G1 guidance below. You must
make at least one actual `bench evaluate <relative-source-directory>` call, inspect
its public feedback, and `bench finalize <returned-candidate-id>` before finishing.
Keep solve.py in a candidate subdirectory such as candidate/, and use `bench evaluate
candidate` from /workspace. Do not use a file path or absolute source path. Every
evaluation uses all six public cases. Public residual/roughness do not establish
hidden accuracy. Scientific success and multiple iterations are not required;
never fabricate evaluations, improvement, hidden results, or performance. If an
error prevents progress, report it honestly. Finish after finalization.

# Recover the initial temperature field

Build a program for batches of previously unseen one-dimensional heat inverse problems. The dimensionless equation is `u_t = kappa*u_xx` on `0<x<1` with `u(0,t)=u(1,t)=0`. The initial field belongs to the first 32 sine modes. The diffusivity lies in `[0.5,1.5]`. You receive noisy, possibly missing observations at two positive times; the retained coordinates are exact. Each observation has independent zero-mean Gaussian noise with the same known absolute standard deviation `sigma` for that case. There are at least 64 observations at each time. All parameters needed to interpret the observations are public.

Your entry point must accept:

```text
python solve.py --input /input --output /output --seed 0
```

`manifest.json` in the input directory lists `cases`, each with `id`, `path` and difficulty `level`. Each case directory contains `observations.csv` with columns `x,t,y`, `metadata.json` with `kappa`, `sigma`, observation `times` and `future_time`, and `target_grid.npy`. The target grid is `x_j=j/257` for `j=1,...,256`. Write exactly `cases/<id>/u0.npy` for every case: finite little-endian float64, shape `(256,)`. Do not write reward files or extra output files. A submitted program must solve all instances from their provided inputs; `--seed` controls your algorithm and does not identify a generated system. Object arrays, pickle, complex numbers, NaN/Infinity, links and paths outside the output directory are forbidden.

The evaluator constructs the full 256-mode sine interpolant of your output: `b_k=(2/257)*sum_j u0_j*sin(pi*k*j/257)`, for `k=1,...,256`. Its propagation to coordinate `x` and time `t` is `sum_k b_k*exp(-kappa*pi^2*k^2*t)*sin(pi*k*x)`. It does not truncate your output to 32 modes. The hidden initial-field relative Euclidean error must be at most `0.15`; the propagated-field relative error at the public `future_time` and target grid must be at most `0.03`. Every relative-error denominator is `max(norm(truth),1e-12)`. The per-case continuous score is `100*(0.8*clip(1-E_init/0.30,0,1)+0.2*clip(1-E_forward/0.06,0,1))`. All 12 hidden cases, including four per difficulty, must pass in each of three clean replays for the task reward to be 1. Illegal/missing outputs and worker failures score 0. High scores or low observation residual alone do not establish correct recovery.

You may use the common public evaluation interface on all six development cases. It returns `R=||H_obs(u0)-y||^2/(m*sigma^2)` at the actual observation locations and times, plus roughness `sqrt(mean((D2(u0)/h^2)^2))`, with `h=1/257` and zero boundary padding. These diagnostics contain no hidden recovery error. Save your hypotheses and experiments in your working directory. Register candidates with `bench evaluate <candidate-relative-directory>` and select an evaluated snapshot with `bench finalize <snapshot-id>`; only registered evaluated snapshots may be finalized. The host preserves the first valid candidate and your final selection. Valid means the entire dev batch executes and yields well-formed finite outputs, regardless of scientific accuracy. Without explicit finalization, the most recent valid candidate is used at the deadline; an explicitly invalid ID is a submission failure.

The common research budget is 30 minutes and at most 20 accepted registered evaluations, including failed candidates. Research resources are 4 vCPU and 4 GiB. Each fresh candidate worker has 1 vCPU, 4 GiB, no swap, no network and a 120-second batch timeout, with numerical library threads fixed to one. Source is limited to 20 MiB and 1,000 ordinary files; output to 256 MiB and temporary storage to 64 MiB. Use the fixed preinstalled Python/NumPy/SciPy environment and the exact dataset manifest; do not install dependencies during candidate execution. Your program and its numeric outputs are independently replayed; self-reported scores are not used.

# Detailed method guidance

Start with a fixed second-derivative Tikhonov method. For each observation `(x_i,t_i,y_i)`, form the 32-column matrix `A_ik=sin(pi*k*x_i)*exp(-kappa*pi^2*k^2*t_i)` for `k=1,...,32`. Let `D=diag(k^2)` and compute `A*D^-1=U*diag(s)*V^T`. With `lambda=alpha*s_max^2`, the regularized coefficient estimate is `a=D^-1*V*diag(s/(s^2+lambda))*U^T*y`. Begin with the fixed public choice `alpha=1e-5`. Evaluate the resulting sine series on the target grid and save it in the required output format.

First implement and evaluate this fixed method. You may explore parameter selection using public observation residual and roughness; neither diagnostic guarantees lower hidden recovery error. A noise-based alternative uses the grid `alpha=logspace(-10,0,81)`. The residual-square acceptance bound is `delta2=sigma^2*chi2.ppf(0.99,m)`. Among grid candidates with `||A*a-y||^2 <= delta2`, choose the largest alpha. If none qualifies, fit the first five sine modes by ordinary least squares and set modes 6–32 to zero. Preserve a diagnostic of fallback, minimum residual, bound and parameter range. This 99% bound concerns the energy of the unfitted Gaussian noise; it is not a 99% recovery guarantee or a guarantee that any parameter will qualify.

Non-executable outline:

```text
for each public input case:
    read the actual observed positions, times, values, and common noise sigma
    form the 32-mode forward matrix
    compute the SVD after dividing column k by k squared
    solve first at fixed normalized alpha 1e-5
    evaluate the estimate at all 256 target points and save u0.npy
register and inspect the entire development batch
if exploring discrepancy selection:
    evaluate the stated alpha grid using only public observations
    choose largest accepted alpha; otherwise use the five-mode fallback
    compare public diagnostics and record the hypothesis for any change
finalize a registered candidate using only public evidence
```

You may choose another valid algorithm or improve this approach. Do not infer hidden ground truth from the guidance or assume that adaptation must outperform the fixed method.

PILOT EXECUTION CONTRACT (overrides formal-study resources/budgets in common):
This is a single infrastructure/research-loop pilot using only six public development
cases at /input. It is not a formal G1/G2/G3 study and accesses no hidden/final-test
truth or scores. You have 600 seconds of TOTAL wall time, including evaluation
waits, at most FOUR accepted bench evaluations (including failed submissions), and
12 model turns. R has 1 CPU/1 GiB; workers retain the published worker contract.
Work only in /workspace as researcher. Python/NumPy/SciPy are preinstalled.
The network allows only the model endpoint. Do not inspect credentials, environment
variables, other directories, host/container management, or private data. Do not
install dependencies or start background processes.
Implement a legitimate solver from the common task and G1 guidance below. You must
make at least one actual `bench evaluate <relative-source-directory>` call, inspect
its public feedback, and `bench finalize <returned-candidate-id>` before finishing.
Keep solve.py in a candidate subdirectory such as candidate/, and use `bench evaluate
candidate` from /workspace. Do not use a file path or absolute source path. Every
evaluation uses all six public cases. Public residual/roughness do not establish
hidden accuracy. Scientific success and multiple iterations are not required;
never fabricate evaluations, improvement, hidden results, or performance. If an
error prevents progress, report it honestly. Finish after finalization.
