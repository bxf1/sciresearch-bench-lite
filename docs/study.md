# Formal study controller

`runner.study` is the minimal host entry point for the frozen 15-session matrix. It does not freeze or approve a plan. The current local acceptance results do not authorize formal research: a draft, unresolved policy, missing freeze, changed trusted source or insufficient actual Docker resources fails before a relay, research container or model request is allocated.

From `benchmark/`, launch one predeclared row:

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study start \
  --plan path/to/frozen-plan.json --run-id <predeclared-run-id>
```

Initial sessions follow the plan sequence. Rows 1–9 cover each task/group once; rows 10–15 complete the heat repeats. Every row gets a fresh workspace, native Pi session and relay. The fixed research budget is 1800 seconds and 20 accepted evaluations, with R limited to 4 vCPU and 4 GiB. No max-turns extension is installed. The frozen output-token budget remains an independent limit. The relay checks the retained actual system JSON and tool schemas on every request using the plan's wire hashes. Admission records the actual native configuration/source hashes, R resources, public input hashes, network probes and trusted termination evidence.

Research reads only the six public-dev cases. The native Harbor verifier uses `RegistrationVerifier`, which checks the closed host registry and retained selected sources, and writes `research-registration.json`. It never runs hidden replay, writes a scientific reward, or imports the old pilot replay verifier. Scientific score and reward remain null throughout research.

The host ledger is `research-runs/<plan-id>/manifest.json`. It binds the exact plan hash and indexes every attempted launch, including pre-container capacity failures and API failures. Each record has a unique attempt ID, result hash, and a closed registry/relay-events reference when available. A later invocation continues the declared matrix; it does not overwrite previous rows. A failed infrastructure/API/cancelled attempt can be retried only with its exact latest parent ID:

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study start \
  --plan path/to/frozen-plan.json --run-id <predeclared-run-id> \
  --retry-of <failed-attempt-id>
```

The retry has a new session and a separate `retries/<attempt-id>/workspace`. Completed or normally timed-out research cannot be replaced, including a session with no valid submission or a later scientific score of zero. If cleanup, verification, or the host controller fails after research registration was closed, the host attempt becomes `infrastructure_failed` with `post_registry_failure=true` and the original `registry_attempt_status`. The registry and its event log remain unchanged; the invalid host attempt is retained, excluded from scientific completion, and can receive an explicit linked retry. A process killed before its host result is finalized leaves an unresolved ledger record and blocks continuation; the controller does not silently relabel or rerun it.

## Explicit final replay

Final replay is a separate command for one selected run, with one original replay:

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study final \
  --plan path/to/frozen-plan.json --run-id <predeclared-run-id> \
  --data /host/path/to/retained-data
```

The data layout is `inputs/<task>/final-test` and `private/<task>/final-test`. Poisson additionally requires `--timing-contract /host/path/to/accepted-timing-contract.json`.

Before reading either final directory, the host requires every predeclared session for that task to have validly completed research: nine heat sessions, three ODE sessions, or three Poisson sessions. Failed attempts alone do not satisfy this barrier. All registries must be closed and match their host outcomes, selected snapshots must match their recorded hashes, and the current plan/freeze/judge sources must validate. The first admitted final replay permanently closes further research for that task, even if scoring subsequently fails.

First and final use the existing `replay_checkpoint`: three independent heat/ODE replays, or one complete Poisson BCCBBC group. Identical source hashes reuse the first checkpoint's replay explicitly. Missing submissions and candidate-invalid artifacts retain their defined scientific zero; a selected public evaluation that failed in trusted infrastructure remains invalid with null verdicts. Trusted replay failure also preserves null score/reward. The final wrapper binds `formal=true`, `split=final-test`, the freeze hash and the exact closed registry hash. Its reference is added to the existing ledger for `runner.study_report`.

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study_report \
  --project . --plan path/to/frozen-plan.json \
  --manifest research-runs/<plan-id>/manifest.json --output results/<report-name>
```

The report consumes the append-only `manifest.baselines` references separately from research attempts. Each author replay must bind the same task, final-test split, frozen plan, numeric image, scoring profile, declared method and complete frozen baseline source tree. The report also verifies each retained batch's phase/image/source and the Poisson protocol's candidate method and BCCBBC measurements. Calibration and pilot records cannot substitute for these final records, and all research sessions for the task must already be validly closed.

`baselines.csv` always lists all eleven declared methods (five heat, three ODE, three Poisson); missing or unfinished methods remain explicitly unscored. `baseline-attempts.csv` preserves failed and linked retry attempts, while `baseline-cases.csv` retains their available case records. Only the latest admissible attempt for each method supplies a reference. An infrastructure retry must name the latest invalid parent; a scientific zero cannot be replaced. The single investigated Poisson instability retry must retain both protocol attempts.

`fixed-reference-runs.csv`, `fixed-reference-groups.csv` and `fixed-reference-cases.csv` compare final research checkpoints with the predeclared heat `tikhonov`, ODE `fixed` and Poisson `lu` references. They retain score, passed-case and reward differences, and per-case score/error/pass-rate differences. Identical first/final sources reuse the first case records; a missing submission retains its twelve scientific zeros. An absent or invalid reference yields null comparisons. Author methods and their replays never increase research-session denominators; the existing n=1 descriptive and n=3 exploratory limits still apply.

## Investigated Poisson timing retry

An original Poisson group marked `baseline_unstable` and `retry_permitted=true` permits one explicit complete BCCBBC remeasurement after the host investigates interference:

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study final \
  --plan path/to/frozen-plan.json --run-id <predeclared-run-id> \
  --data /host/path/to/retained-data \
  --timing-contract /host/path/to/accepted-timing-contract.json \
  --retry-replay research-runs/<plan-id>/final-replays/<attempt-id>/result.json \
  --interference-resolution 'Recorded investigation and removal of the interference'
```

The path must identify the exact original replay in the ledger. The controller calls the existing `retry_t3_attempt` only for originally unstable checkpoints, preserves the original wrapper under `replay_history`, and stores a separate linked wrapper containing both protocol attempts. A stable checkpoint is reused unchanged; identical first/final sources share the remeasurement. A second final retry, a retry without investigation, or a retry of a stable or candidate-failed result is rejected before execution. The task remains closed to research. Reports count the selected group once and retain both original and retry evidence; cases, replay groups and retries do not become additional independent research sessions.

## Frozen author baselines

`study baseline` replays one predeclared author method on final-test using the same task research-completion barrier as `study final`. The source, image, freeze, and plan are checked before final-data access. The task is closed to further research before the replay begins.

| Task | Methods | Fixed reference |
| --- | --- | --- |
| heat | `ls`, `rank5`, `tikhonov`, `discrepancy`, `tsvd` | `tikhonov` |
| ode | `raw`, `fixed`, `search` | `fixed` |
| poisson | `cg`, `jacobi`, `lu` | `lu` |

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study baseline \
  --plan path/to/frozen-plan.json --task heat --method tikhonov \
  --data /host/path/to/retained-data
```

Poisson also requires `--timing-contract /host/path/to/accepted-timing-contract.json`. Each heat/ODE method receives three fresh replays. Each Poisson method receives one complete BCCBBC group, with Jacobi fixed as the baseline role and the declared method passed as `candidate_method`. Methods and source paths cannot be overridden beyond the table above. The controller makes a read-only copy of the exact baseline source files already hashed in the frozen plan. Ordinary Python bytecode caches are ignored and never copied; undeclared source/data files and links are rejected.

`manifest.baselines` indexes every baseline attempt separately from `manifest.attempts`. Each result binds the method, source tree, freeze, plan, image and final-test split. Failures and partial replay evidence remain visible. They do not add research replications or change the research denominator.

An infrastructure failure can receive an explicitly linked new attempt using `--retry-of <latest-baseline-attempt-id> --retry-reason 'Recorded investigation and repair'`. A normal result, including a scientific zero, cannot be rerun. A Poisson group with verified baseline instability permits one investigated linked remeasurement through the same command using `--retry-of <latest-baseline-attempt-id> --interference-resolution 'Recorded investigation and removal of interference'`. This calls the existing `retry_t3_attempt`, keeps both complete protocol groups, and retains the original baseline entry. No retry is automatic, and a second baseline-instability retry is rejected.

## Validation scope

The controller and reporting paths have synthetic no-Docker/no-API coverage. A real formal matrix and final replay have not been executed or accepted. The existing nonformal heat pilot remains separate, at 600 seconds, four evaluations, 12 turns and R 1 vCPU/1 GiB.

Recovery tests cover an unchanged closed registry followed by host cleanup failure, explicit linked research retry, and a complete T3 replay-history/report path using synthetic groups. They verify that one original and one linked remeasurement remain one scientific session. No final attempt is deleted or replaced to obtain a better score.
