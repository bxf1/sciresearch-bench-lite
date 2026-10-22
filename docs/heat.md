# T1: heat inverse problem data card

Contract: execution plan v0.3. This card describes the implementation; actual dataset provenance, calibration, container acceptance and experimental results belong in the generated manifests and run reports. Passing a local numerical test is not evidence of isolated Agent execution.

The dimensionless PDE is `u_t=kappa*u_xx` on `(0,1)` with homogeneous Dirichlet boundaries. The private initial condition has 32 sine modes. The generator samples `p~U[1.5,2.5]`, coefficients proportional to independent normal draws divided by `k^p`, and replaces the first coefficient by a random sign times `U[0.8,1.2]` before normalizing the coefficient norm to `sqrt(2)`. Thus continuous RMS equals 1; the RMS on the 256-point internal target grid equals `sqrt(257/256)`. Diffusivity is uniform in `[0.5,1.5]`.

| Level | Observation times | Missing fraction | Noise / retained clean RMS |
|---|---|---|---|
| 0 (easy) | 0.001, 0.004 | 0 | 0.005 |
| 1 (medium) | 0.003, 0.009 | 0.15 | 0.01 |
| 2 (hard) | 0.006, 0.018 | 0.30 | 0.02 |

Observation locations before masking are `j/129`, `j=1,...,128`. Mask draws alone are repeated when either time retains fewer than 64 points, with a maximum of 1,000 attempts. Coefficients are not redrawn and solver performance is never a generation filter. Noise is sampled after masking, using one absolute standard deviation across all retained observations. System, mask and noise receive independent random streams from the host's stable namespace. The T1 latent fingerprint hashes the normalized initial-field coefficients, so reusing an initial field with a different diffusivity or noise draw is detectable.

Public files are `observations.csv(x,t,y)`, `metadata.json`, and `target_grid.npy`. The target points are `j/257`, `j=1,...,256`; `future_time` is `1.25*max(observation_times)`. Private files retain coefficients, true initial and future fields, clean observations, exact noise draw, full mask, private distribution parameters and QC. The public input contains neither root entropy nor latent coefficients.

Generator QC checks continuous normalization (absolute error at most `1e-12`), finite arrays, t=0 reconstruction, an independent FFT DST-I coefficient/propagation calculation, and heat semigroup composition (relative errors below `1e-10`). Complex-step differentiation independently verifies each spectral ODE against `-kappa*pi^2*k^2*q_k`, scaled by the larger term magnitude or `1e-12`. Zero boundaries use an absolute tolerance of `1e-12*max(1,max(abs(u0)))`. QC evidence is written before a failed generation is rejected; failure must stop the host rather than replace the sample.

The five standalone baselines are 32-mode unregularized least squares (`rcond=1e-12`), five-mode least squares, fixed second-order Tikhonov (`alpha=1e-5`), discrepancy Tikhonov, and discrepancy TSVD. Tikhonov scales lambda by the squared largest singular value of `A D^-1`, with `D=diag(k^2)`. The adaptive grid is 81 logarithmically spaced alpha values from `1e-10` through 1; it selects the largest whose residual square is at most `sigma^2*chi2.ppf(.99,m)`. TSVD uses the unscaled matrix, skips singular values at or below `s_max*1e-12`, and selects the first accepted rank. Both methods fall back to five-mode least squares if their rule has no candidate. Fallbacks are logged to stdout and are not hidden from reports. All choices use public data only.

The public checker derives all 256 sine interpolation modes from the submitted field via DST-I, evaluates the exact observation coordinates/times and reports normalized residual and zero-boundary finite-difference roughness. The private scorer independently uses explicit sine sums for the same 256-mode operator, compares initial and future fields and applies the 15% / 3% gates. It validates saved GT against the spectral coefficients before scoring; corrupted GT raises `EvaluationInvalid`. A malformed candidate scores zero, while a finite candidate whose calculations overflow is a valid artifact with a scientific failure. Neither the checker nor the judge imports submitted code.

The continuous per-case score is `100*(0.8*clip(1-E_init/.30,0,1)+0.2*clip(1-E_forward/.06,0,1))`. Task-level batch and replay aggregation is the host's responsibility. The two errors are relative Euclidean errors with denominator floor `1e-12`. Missing cases remain in the denominator. T1 does not require any particular inverse algorithm or exact spectral support recovery.

This distribution favors low-frequency-dominated fields and can heavily damp high-frequency information before observations. Gaussian noise is unbounded. No finite error guarantee applies to every generated instance, and the discrepancy noise quantile is not a recovery probability. Good forward agreement alone can coexist with inaccurate initial conditions. The test suite uses disposable diagnostic seeds and never selects or tunes against final-test recovery scores.
