# Harbor and Pi integration status

The user authorized continuing local functional work. Formal resource budgets
remain unchanged, and completed formal guidance cells/sessions are still 0/0.
The evidence currently consists of a real model/source/W/J pilot, network probe
005, and a nine-check real R-to-W file-bridge probe. They are separate bounded
tests; the complete model-driven research lifecycle still needs its own result.
The first real research-loop pilot has now returned with one registered valid
candidate but no explicit finalize; its `deadline_fallback` result is retained
as `pilot_returned_without_required_registration`, not marked successful.
Its fallback-selected candidate subsequently completed the real Harbor verifier
hook and three independent W/J batches on pilot-smoke: each passed 3/3 with
score 87.69277970613776 and reward 1. The [successful third verifier attempt](../logs/research-loop-pilot-001-wj-replay-003/result.json)
retains parent links to two infrastructure failures (container/sidecar check,
then a missing package file). First and final share the same source hash;
final reuses the three first replays. This is separate from the older zero-solution
pilot and provides no iteration or final-test result.

This is the wiring for the read-only reference checkout at
`harbor/`, version 0.24.0, commit
`38b9be0164a910015a0be9a37ba6e8e78c562dfe`. No Harbor source is modified.
The installed host Pi was checked as 0.84.1. A real pilot subsequently ran
Harbor's built-in `Pi.setup()` and `Pi.run()` inside its `DockerEnvironment`;
see `logs/model-smoke-20261022-02/result.json` and the retained native Pi session.
It used the configured Anthropic-compatible DeepSeek endpoint and requested
`deepseek-v4-pro`, which is also the model identifier recorded by Pi. A separate
provider-side proof of the served model revision is not available. The model
printed public input shapes and created the requested deliberately incorrect
zero-solution program. The paused container's source was copied and hashed;
the container was then removed. This validates model-to-source wiring, not a
formal scientific research condition. The retained source subsequently passed
the independent registry/W/J wiring check in
[pilot-model-registry-wj-001](../logs/pilot-model-registry-wj-001/result.json):
first/final were the same candidate, with three legal zero-score replays.

The successful pilot reports Pi 0.84.1, Node v22.23.4, 8,924 input tokens
(including 6,528 cached tokens), 625 output tokens, and 11.84 seconds in the
model phase. Monetary cost is null because custom-endpoint prices were not
verified. Actual cgroup limits were 2 CPU and 2 GiB memory with 2 GiB swap;
network access was unrestricted and there were no host/volume mounts. Its
resource and network statuses explicitly remain diagnostic. The preceding
`model-smoke-20261022-01` failed before any model call because the local Docker
legacy builder did not accept a display option; the linked new attempt fixed
only that compatibility issue. Both attempts retain matching controller source
hashes and credential-value scans. No failure was overwritten or omitted.

The custom verifier is `runner.harbor_verifier:ResearchReplayVerifier`.
It uses Harbor's existing `BaseVerifier` import hook and its numeric-or-missing
`VerifierResult`. Invalid trusted evaluation writes a diagnostic record with
`reward=null` and returns `rewards=None`; it does not write null into Harbor's
numeric `reward.json`. Ordinary scientific failures return numeric zero.

The controller creates the host registry outside the R workspace. The current
research-side `bench evaluate <relative-source-dir>` / `bench finalize <candidate-id>`
client uses bounded files under `/workspace/.bench`; the trusted host FileBridge
polls requests and exports only a checked source snapshot through Docker's
management API. R receives no Docker socket, host mount, bridge credential or
host HTTP listener. The controller must stop research, close the registry, check
the freeze/phase gate and then invoke verification. The adapter refuses an
open registry. It verifies registered snapshot hashes and replays first and
final through `runner.replay.replay_checkpoint`. T1/T2 execute three fresh
batches per distinct source hash; T3 invokes its internal B,C,C,B,B,C protocol
once. Identical first/final hashes reuse the recorded replay, explicitly.

Host configuration for the verifier has this shape (paths are supplied by the
trusted run launcher, never read from a candidate file):

```json
{
  "import_path": "runner.harbor_verifier:ResearchReplayVerifier",
  "kwargs": {
    "registry_root": "/host/private/run/registry",
    "replay_config": {
      "task": "heat",
      "input_root": "/host/private/data/heat/final-test/input",
      "truth_root": "/host/private/data/heat/final-test/truth",
      "output_root": "/host/private/run/replays",
      "image": "frozen-worker-image-id",
      "judge_source_root": "/host/private/trusted-judge-source",
      "freeze_path": "/host/private/freezes/heat.json",
      "profile": null
    }
  }
}
```

This is a schema example, not a ready-to-run command or a claim of a freeze.
For formal T3, profile must be the calibration-selected frozen profile.
The replay runner owns W and the independent no-network judge; the Harbor
verifier hook orchestrates it on the host. The Harbor-provided separate
environment is checked for unwanted transfers but is not represented as the
actual scoring container unless the replay runner explicitly uses it.
R/W must never receive the private config or truth paths as mounts or files.

The existing Pi agent supports a custom Anthropic-compatible endpoint without
a new adapter. Its AgentConfig fields should be frozen as:

```json
{
  "name": "pi",
  "model_name": "anthropic/deepseek-v4-pro",
  "model_base_url": "https://api.deepseek.com/anthropic",
  "model_api_key_name": "BENCH_MODEL_API_KEY",
  "model_api_format": "anthropic_messages",
  "skills": [],
  "kwargs": {"version": "0.84.1", "reasoning_effort": "off"}
}
```

The launcher may copy only the authorized model credential into the dedicated
runtime variable. Never write its value into job JSON, logs, prompts, image
layers, or this document. The `reasoning_effort` shown is an explicit proposed
configuration to smoke-test, not evidence that the model supports a particular
reasoning mode. Harbor builds Pi's isolated `models.json` with an environment
variable reference and `api="anthropic-messages"`. No unrelated skills,
extensions or MCP servers should be supplied; inspect and freeze any inherited
Pi settings, and use a fresh container/session/workdir for each condition.

Pilot001 requested `reasoning_effort="off"` but retained 12 thinking blocks; the
pinned Harbor `_build_custom_models_json` sets `model.reasoning=true` only for
non-off effort, while off omits that field rather than explicitly disabling
the API mode. DeepSeek documents thinking enabled by default with high effort
and ignored temperature in that mode; its Anthropic API supports `thinking`
but ignores `budget_tokens`, while supporting `max_tokens` ([thinking controls](https://api-docs.deepseek.com/guides/thinking_mode/), [API compatibility](https://api-docs.deepseek.com/guides/anthropic_api/)).
Default activation due to the omitted field is an inference, not a captured
wire-payload observation; effective thinking, sampling and aggregate output-cap
enforcement remain unresolved and must not be frozen as successfully applied.

Pi setup runs an npm install each time. Pinning its version prevents a moving
`latest`; preinstalling it alone does not skip Harbor's setup code. Trusted
setup may access pinned installation dependencies. After setup, R's network
must be restricted to the model endpoint; the current file bridge needs no
network exception. Verify the restriction with real probes. W/J are separately no-network and have no
model key. The controller must account for model errors/waits and preserve
failed attempts rather than silently replacing them.

## Automatic artifact transfer requires an explicit exclusion

Harbor's `SingleStepTrial` uploads collected artifacts to the separate verifier
before constructing the custom verifier. `artifacts=[]` does **not** disable
this: `with_convention_entry` adds `/logs/artifacts`. Configure this explicit
replacement at the top level of the task TOML and add no other R artifact paths:

```toml
artifacts = [{ source = "/logs/artifacts", exclude = ["*", "**/*"] }]

[verifier]
environment_mode = "separate"
timeout_sec = 1200.0

[verifier.environment]
network_mode = "no-network"
cpus = 1
memory_mb = 4096
```

The adapter independently rejects residual R artifact files, links or special
files in the host collection tree and a nonempty `/logs/artifacts` inside the
Harbor verifier environment, before calling the replay runner with GT paths.
The exception is Harbor's host-side root `manifest.json`, which is not trusted
as a candidate result. These checks are additional guards, not substitutes for
an actual transfer attack probe. Candidate source and R-written rewards must
never be auto-uploaded or added to the trusted scorer's import path.

Relevant inspected sources are `agents/installed/pi.py`, `verifier/base.py`,
`verifier/factory.py`, `models/verifier/result.py`, `trial/single_step.py`,
`trial/trial.py`, `trial/artifact_handler.py`, `models/task/artifacts.py`, and
`models/trial/config.py` in that exact checkout. Source inspection and adapter
unit tests do not establish the nine formal scientific cells. The retained
model pilot and its subsequent W/J replay establish the limited wiring described
above, not a model-directed iterative research session.
Formal isolation, the frozen resource contract, three-condition research and
independent scientific replay remain separately tracked milestones.

The [file-bridge-runtime-001 result](../logs/file-bridge-runtime-001/result.json)
records 9/9 real R/W checks: six public inputs match their hashes, the researcher
cannot replace helpers or feedback, escaping paths are rejected and charged,
accepted snapshots execute in W, feedback excludes hidden metrics, post-submit
R mutations cannot change the snapshot, and finalize/first/final are retained.
It used no model calls; both selected checkpoints are candidate-002 because the
first rejected path consumed candidate-001. The R container and bridge thread
were removed/stopped. The earlier localhost HTTP bridge's seven-check result
is preserved separately and does not describe the current R transport.
The later [file-bridge-runtime-002](../logs/file-bridge-runtime-002/result.json)
also passed 9/9 after host execution changes; it still made no model request.

The generated `tasks/{heat,ode,poisson}` packages contain only six public dev
cases, public helpers/checkers, and the source-format utility needed for export.
T3 also includes the public Jacobi-CG comparator for every guidance condition.
They parse with the installed Harbor TaskConfig; each default `tests/test.sh`
exits 2 deliberately. Generic Harbor execution cannot replace the closed-registry
custom verifier with an unverified reward.

## Retained research network probes

`runner/research_network_probe.py` exercises the pinned Harbor
`DockerEnvironment` directly, with PUBLIC during setup, declared ALLOWLIST
phase support, then `set_network_policy` for `api.deepseek.com`. It performs no
Pi installation or model request and forwards no credential. It checks actual
container state and the sidecar's **nftables** rules, not merely the requested
policy. It deletes only its uniquely named Compose project's containers,
networks and volumes. Images/build cache remain available for subsequent runs.

The local attempt chain is retained under `logs/research-network-probe-00N`:

| Attempt | Actual result |
| --- | --- |
| 001 | Native sidecar build stopped because Docker buildx was unavailable. |
| 002 | Unchanged Harbor context with legacy build stopped at `COPY --chmod`, which needs BuildKit. |
| 003 | Project-local buildx built the unchanged sidecar; isolated Docker config initially lacked the existing Compose plugin. |
| 004 | Standard URL controls and host-boundary checks passed, but root R retained NET_RAW and swap; not adopted as the research configuration. |
| 005 | Nonroot R, explicit security/resource overlay, socket-permission tests, URL controls and `bench --help` passed. |

Buildx is pinned to [Docker's official v0.32.1 release](https://github.com/docker/buildx/releases/tag/v0.32.1)
inside ignored `benchmark/.docker/cli-plugins`. Its Darwin arm64 asset SHA-256
`f508d57e82e661fc9daa4fc8bc5dc69e9625743366fe0d30c934deff55ed2526`
matched the official release API asset digest before execution. This release's
`checksums.txt` omits Darwin assets; the record explicitly states that it was
not a second verification of the Darwin binary. Full provenance is retained in
`build/buildx-install-001/`. The project-local config points at the already
installed Compose 5.1.4 plugin; no user Docker credentials/config were copied,
and no global Docker, Colima or host-network setting was changed.

The unchanged Harbor sidecar context hash is `e9f39ce1643ee690`; its built image
ID is `sha256:db417066dc87f39c9aae48fc36485fc2c72f5460cc32612c7cbf5d0110a1a3ec`.
Probe 005 used `sciresearch-heat-r:0.3.1`, image ID
`sha256:6619dd1526ec8d635d0e57d068dc3e750821ddd82443d44777fe847340944bdb`.
The daemon kernel was Linux 6.8.0-100-generic, aarch64, with cgroup v2.

Harbor's public `extra_docker_compose=[path]` constructor argument (also exposed
in the run environment configuration) accepts this host-owned overlay without
modifying Harbor. `EnvironmentConfig`'s task resource schema itself does not
have the individual capability/security/swap fields.

```yaml
services:
  main:
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    pids_limit: 128
    mem_limit: 1g
    memswap_limit: 1g
  harbor-docker-egress-control-sidecar:
    cpus: 0.25
    mem_limit: 128m
    memswap_limit: 128m
```

Harbor's later native egress overlay retains its required sidecar NET_ADMIN and
NET_RAW and does not override these limits or main's capability settings. The
probe verified R UID/GID 1000, CapEff/CapPrm/CapBnd zero, NoNewPrivs 1,
`cpu.max=100000 100000`, `memory.max=1073741824`, `memory.swap.max=0`, and
`pids.max=128`. Both marked-socket `SO_MARK=114514` and raw-socket creation
returned EPERM; these permission probes sent no packets. R had no mounts,
Docker socket, DOCKER_HOST, host networking or host PID namespace. The sidecar
had the requested 0.25 CPU and 128 MiB memory limits. R rootfs remained writable
to support research workspace/home/tmp and native Pi setup.

Before restriction, the three URL controls returned HTTP 401 (DeepSeek), 200
(example.com), and 301 (1.1.1.1). After restriction, DeepSeek still returned
401; the other two connections were rejected with TLS EOF. Redirects and proxy
environment use were disabled. Certificate validation was disabled only for
these unauthenticated connectivity probes so an IP certificate mismatch could
not be misclassified as network rejection; this is not a production TLS
configuration. Actual `gost_egress` redirect/filter rules are retained alongside
the results. `bench --help` returned zero, but this was not a bridge evaluation.

Probe 005 can be repeated into a fresh output directory with:

```sh
env -u DOCKER_CONTEXT -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
  DOCKER_CONFIG="$PWD/benchmark/.docker" \
  DOCKER_HOST=unix:///Users/baixiongfei/.colima/default/docker.sock \
  PYTHONPATH=benchmark benchmark/.venv/bin/python -m runner.research_network_probe \
  --output benchmark/logs/research-network-probe-NEW \
  --parent-attempt research-network-probe-005 \
  --buildx-provenance benchmark/build/buildx-install-001/provenance.json \
  --image sciresearch-heat-r:0.3.1 --expected-uid 1000 \
  --harden-research --helper-command 'bench --help'
```

These are functional observations, not formal resource acceptance or a complete
adversarial network audit. Probe 005 did not run Pi setup. The separately logged
[research-loop-pilot-001](../logs/research-loop-pilot-001/result.json) currently
records CHOWN, DAC_OVERRIDE and FOWNER for Harbor's host-issued trusted root
configuration helper, while the researcher remains UID1000 with CapEff=0,
NoNewPrivs=1 and no NET_ADMIN/NET_RAW. This is a distinct configuration from 005;
its full lifecycle is described below. A starting record or successful Pi
installation alone is not a completed research run.

## Real public-development research pilot

`runner/research_loop.py` is a thin controller around the pinned Harbor's built-in
Pi setup and run methods. It uses the existing public Docker Compose overlay
hook and host file bridge; there is no replacement Pi adapter or Harbor fork.
Its input guard accepts only the six heat `public-dev` cases. It has no private
truth or final-test input argument. Resources remain diagnostic: R has 1 CPU,
1 GiB memory, zero swap and 128 PIDs; the sidecar has 0.25 CPU and 128 MiB.

The three added root capabilities are needed by Harbor's existing config writer
to traverse the researcher's mode-0700 configuration directory, chown the
uploaded file and chmod it. Pi itself runs as researcher UID 1000, with effective
capabilities zero and no-new-privileges enabled. The controller exercises native
setup and those original config-writing methods before permitting a model call.
It then switches PUBLIC setup networking to the model-domain allowlist and
checks actual network rules and the three URL controls.

The retained `research-loop-pilot-001` used the 600-second wall budget,
four-evaluation allowance and native 12-turn limit. The model ran for 108.39
seconds and submitted one source snapshot through a real `bench evaluate` call;
W executed all six public cases and returned public feedback. The native turn
limit stopped further work before an explicit `bench finalize`. The registry
selected its last valid candidate using the documented fallback, so first and
final both identify `candidate-001`, source hash
`87f89f466a74b5cffd58fab2283b66d52d03ba247118598c4f09a23d7761c53b`.
No extra model call was made to turn this fallback into an explicit-finalize
result. The original status text `pilot_returned_without_required_registration`
is preserved, despite its inaccurate implication that registration was absent;
[model-observation.json](../logs/research-loop-pilot-001/model-observation.json) records that registration succeeded and finalization
was the missing step.

The auxiliary session reports 131,931 input tokens including 120,064 cached
tokens, and 12,409 output tokens. Although the request set reasoning effort to
`off`, 12 thinking blocks were observed; disabled thinking is therefore not
confirmed. These R-authored counters and model labels are auxiliary observations,
not trusted billing or API-failure evidence. Cost remains null, and these results
cannot set a formal output-token or reasoning budget without further review.

Pilot 001's original controller bytes and 11 originally recorded trusted-source
hashes are retained and match exactly in the [source-retention manifest](../logs/research-loop-pilot-001/controller-snapshot-manifest.json). Its additional source snapshot was
captured after the run; the manifest distinguishes those extra files from sources
whose hashes were recorded at startup. A worker deadline-line change made after
the run was reversed only in a retained copy, whose SHA-256 strictly matches the
original run record. The original [input hash audit](../logs/research-loop-pilot-001/input-audit.json) also occurred during the run,
not as a preflight. These timing limits remain explicit in the evidence.
The updated controller captures all runner/public/judge Python sources before
container start, and compares actual R `/input` hashes with the selected host
public input before model execution.

The current controller records a trusted attempt outcome when closing the
registry: completed, research timeout, infrastructure failure or cancellation.
It does not infer provider failure from model-writable session text. Cleanup
stages are independent, and final result saving survives stop/inspection errors.
It drains the accepted public evaluation before closing the registry. Additional
W cleanup is limited to container names/IDs in that run's own
`registry/evaluations/*/{worker,container}.json`; no global worker scan or prune
is used. The existing pilot's evidence and closed registry are unchanged.

New auxiliary retention accepts only bounded text logs and direct session JSONL
files, canonicalizes decoded JSON, redacts literal/Unicode/base64 credential
strings, and drops image attachments. Limits apply to transport bytes, retained
bytes, file count, individual file size, event count and JSON structure size.
Native trajectory/attachment population is not called. Usage extraction only
reads these bounded files and cannot write decoded images. The retained pilot
001 [safety scan](../logs/research-loop-pilot-001/retention-check.json) checked 80 files and found zero literal, decoded-string or
decoded-base64 matches for the configured credential; only counts and the scan
result are recorded. Unit tests cover these guards and failed cleanup commands;
they are mocked fault tests, not additional model or formal-resource trials.
