"""Run a full native Harbor SingleStepTrial as a nonformal heat pilot.

Only public-dev research and pilot-smoke replay are accepted. The native Pi
agent, Trial lifecycle and verifier factory remain Harbor's implementations.
The host owns admission, file bridge, termination evidence and final validity.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import threading
import time
from urllib.parse import urlsplit
import uuid

from harbor.models.task.config import NetworkMode, NetworkPolicy
from harbor.models.trial.config import AgentConfig, EnvironmentConfig, TaskConfig, TrialConfig, VerifierConfig
from harbor.trial.hooks import TrialEvent
from harbor.trial.single_step import SingleStepTrial
from harbor.trial.trial import Trial

from .common import canonical, digest, file_hash, read_json, tree_hashes, write_json
from .file_bridge import FileBridge
from .model_smoke import RedactingFormatter
from .phase import IMAGE_ID, validate_manifest
from .registry import Registry
from authoring.package_tasks import INPUTS
from .replay import prepare_judge
from .research_loop import (CAP_REASON, ROOT_CAPS, auxiliary_usage, cleanup_own_workers,
                            command, pilot_prompt, public_input, retain_controller_sources,
                            retain_logs, sanitize_auxiliary)
from .research_network_probe import SECURITY_PROGRAM, SOCKET_PRIVILEGES_PROGRAM


def pilot_settings():
    return {"formal": False, "task": "heat", "group": "g1-pilot", "research_seconds": 600,
            "max_evaluations": 4, "max_turns": 12, "research_vcpu": 1,
            "research_memory_bytes": 1024**3, "session_output_limit": 32768,
            "request_output_limit": 4096, "relay_ttl_seconds": 1500}


def research_public_input(root, task):
    from .phase import checked_hashes
    manifest = validate_manifest(task, root, expected_split="public-dev")
    expected = {"manifest.json"} | {f"{case['path']}/{name}" for case in manifest["cases"] for name in INPUTS[task]}
    if set(checked_hashes(root)) != expected:
        raise ValueError("research inputs must be exactly the six public-dev cases and their public files")
    return manifest


def require_host_capacity(settings):
    """Read actual daemon capacity before allocating a formal relay/container."""
    info = json.loads(command(["docker", "info", "--format", "{{json .}}"]).stdout)
    # R and one W can overlap. Relay/sidecar together require another 0.5 CPU
    # and 384 MiB; reserve 512 MiB for their controls rather than overcommit.
    minimum_cpu = math.ceil(settings["research_vcpu"] + 1 + .5)
    minimum_memory = settings["research_memory_bytes"] + 4 * 1024**3 + 512 * 1024**2
    actual_cpu, actual_memory = info.get("NCPU"), info.get("MemTotal")
    if (type(actual_cpu) is not int or type(actual_memory) is not int
            or actual_cpu < minimum_cpu or actual_memory < minimum_memory):
        raise RuntimeError("Docker daemon physical capacity is below the formal R/W/control requirement")
    return {"actual_vcpu": actual_cpu, "actual_memory_bytes": actual_memory,
            "minimum_vcpu": minimum_cpu, "minimum_memory_bytes": minimum_memory,
            "acceptance_source": "frozen plan plus actual daemon capacity; no acceptance was promoted"}


def transport():
    # Kept lazy so config/unit checks need neither a relay nor Docker.
    from . import relay_transport
    return relay_transport


def admission_public(admission):
    """Explicit allowlist: admission contains a live, private relay token."""
    names = ("base_url", "relay_ip", "relay_port", "network_name", "container_id",
             "container_name", "image_id", "admission_path")
    return {name: admission[name] for name in names if name in admission}


def validate_admission(admission):
    transport().validate_admission(admission)
    endpoint = urlsplit(admission["base_url"])
    if (endpoint.scheme not in ("http", "https") or endpoint.username or endpoint.password
            or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment
            or endpoint.hostname != admission["relay_ip"] or endpoint.port != admission["relay_port"]):
        raise ValueError("model endpoint must be the exact admitted relay IP and port")
    if not isinstance(admission.get("token"), str) or len(admission["token"]) < 24:
        raise ValueError("missing private session relay token")
    return endpoint.hostname


def relay_outcome(status, *, interrupted=False):
    """Only host-read relay state can establish provider failure."""
    if not isinstance(status, dict) or status.get("schema_version") != 1 or status.get("model") != "deepseek-v4-pro":
        return "infrastructure_failed", "missing trusted relay status schema"
    for key in ("request_count", "successful_requests", "failed_requests", "inflight"):
        if type(status.get(key)) is not int or status[key] < 0:
            return "infrastructure_failed", "invalid trusted relay counters"
    if status.get("evidence_error") is not False or status.get("state") == "failed_closed":
        return "infrastructure_failed", "relay could not persist trusted evidence"
    if status.get("protocol_violation") is not False or status["inflight"]:
        return "infrastructure_failed", "relay protocol violation or active upstream request"
    outcome = status.get("last_request_outcome")
    if outcome == "evidence_error":
        return "infrastructure_failed", "relay could not persist trusted evidence"
    if outcome in ("upstream_http_error", "upstream_transport_error", "upstream_timeout", "stream_error"):
        return "api_failed", "terminal trusted relay outcome: " + outcome
    if interrupted:
        return None  # Host timeout/cancellation may disconnect a valid stream.
    if not status["request_count"]:
        return "infrastructure_failed", "no authenticated model request was recorded"
    if outcome != "success":
        return "infrastructure_failed", "model transport did not finish successfully"
    return None


async def native_setup_evidence(agent, environment, config, relay_status, *, settings=None):
    """Hash the native setup before R can write research code or call a model."""
    settings = settings or pilot_settings()
    limits = relay_status.get("limits", {})
    if (relay_status.get("state") != "ready" or relay_status.get("request_count") != 0
            or relay_status.get("model") != "deepseek-v4-pro" or relay_status.get("inflight") != 0
            or relay_status.get("protocol_violation") is not False or relay_status.get("evidence_error") is not False
            or limits.get("thinking") != {"type": "disabled"} or limits.get("temperature") != 0.0
            or limits.get("top_p") != 1.0 or limits.get("request_output_limit") != settings["request_output_limit"]
            or limits.get("session_output_limit") != settings["session_output_limit"]):
        raise RuntimeError("fresh relay policy differs from the research contract")
    expected = {"models.json": digest((json.dumps(config, indent=2) + "\n").encode())}
    if settings["max_turns"] is not None:
        expected["max-turns.ts"] = digest(agent._build_max_turns_extension(settings["max_turns"]).encode())
    if settings["formal"] and any(limits.get(key) != settings[key] for key in ("expected_system_sha256", "expected_tools_sha256")):
        raise RuntimeError("fresh relay wire system/tools policy differs from the frozen research contract")
    program = """import hashlib,json,pathlib,shutil
root=pathlib.Path(shutil.which('pi')).resolve().parent.parent
package=json.loads((root/'package.json').read_text())
assert package['name']=='@earendil-works/pi-coding-agent'
config=pathlib.Path('/tmp/harbor-pi-agent')
sources=[root/'dist/core/provider-composer.js',root/'node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js',root/'node_modules/@earendil-works/pi-ai/dist/api/simple-options.js']
tools=sorted((root/'dist/core/tools').rglob('*.js'))
assert tools
sources+=tools
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
NAMES
print(json.dumps({'version':package['version'],'configuration_sha256':{name:sha(config/name) for name in names},'installed_source_sha256':{p.relative_to(root).as_posix():sha(p) for p in sources}}))
"""
    declaration = "names=" + repr(list(expected))
    if settings["max_turns"] is None:
        declaration += "\nassert not (config/'max-turns.ts').exists(), 'unexpected turn cap extension'"
    program = program.replace("NAMES", declaration)
    actual = await environment.exec(command=". ~/.nvm/nvm.sh && python -I -c " + shlex.quote(program), timeout_sec=15)
    if actual.return_code:
        raise RuntimeError("native Pi installed source audit failed")
    observed = json.loads(actual.stdout)
    if observed.get("version") != "0.84.1" or observed.get("configuration_sha256") != expected:
        raise RuntimeError("native Pi version or configuration hash mismatch")
    return {**observed, "native_requested_reasoning_effort": "off",
            "max_turns": settings["max_turns"],
            "relay_enforced_policy": limits, "fresh_upstream_request_count": 0,
            "policy_source": "trusted relay status; native off alone does not prove disabled thinking"}


def retain_safe_records(output, trial_directory, admission):
    """Redact only this new run; never publish the private admission itself."""
    secret, changes = admission["token"], []
    if trial_directory and trial_directory.exists():
        paths = sorted(path for path in trial_directory.rglob("*") if path.is_file())
        if len(paths) > 512:
            raise ValueError("native trial record quota exceeded")
        for path in paths:
            if path.is_symlink() or path.stat().st_size > 16 * 1024**2:
                raise ValueError("unsafe or excessive native trial record")
            before = path.read_bytes()
            try:
                value = json.loads(before)
            except (ValueError, UnicodeError):
                after = before.replace(secret.encode(), b"[RELAY_SESSION_TOKEN_REDACTED]")
            else:
                clean = sanitize_auxiliary(value, secret)
                after = (json.dumps(clean, indent=2, sort_keys=True, allow_nan=False) + "\n").encode() if clean != value else before
            if before != after:
                path.write_bytes(after)
                changes.append({"path": path.relative_to(output).as_posix(), "original_sha256": digest(before),
                                "retained_sha256": digest(after), "reason": "temporary_relay_token_redaction"})
    relay_root = Path(admission["output_root"])
    retained = {}
    for relative in ("startup.json", "evidence/events.jsonl", "cleanup.json"):
        path = relay_root / relative
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024**2:
            raise ValueError("unsafe or excessive relay evidence")
        rows = [sanitize_auxiliary(json.loads(line), secret) for line in path.read_text().splitlines()] if path.suffix == ".jsonl" else sanitize_auxiliary(read_json(path), secret)
        target = output / "relay-evidence" / relative
        if path.suffix == ".jsonl":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"".join(canonical(row) + b"\n" for row in rows))
        else:
            write_json(target, rows)
        retained[relative] = file_hash(target)
    write_json(output / "record-retention.json", {"token_redactions": changes, "relay_evidence_sha256": retained,
               "private_admission_copied": False, "native_records_scanned": True})
    return retained


def build_task(directory, public_root, research_image, numeric_image, relay_host, *, settings=None):
    """Fresh task build contains only public inputs and host-authored wiring."""
    settings = settings or pilot_settings()
    research_public_input(public_root, settings["task"])
    if not IMAGE_ID.fullmatch(research_image) or not IMAGE_ID.fullmatch(numeric_image):
        raise ValueError("pilot images must be immutable SHA256 image IDs")
    directory.mkdir(parents=True, exist_ok=False)
    environment = directory / "environment"
    environment.mkdir()
    shutil.copytree(public_root, environment / "public-dev")
    (environment / "Dockerfile").write_text("FROM " + research_image + "\nCOPY public-dev/ /input/\n")
    (directory / "tests").mkdir()
    (directory / "tests/test.sh").write_text("#!/bin/sh\n# Trusted import-hook verifier is mandatory.\nexit 2\n")
    if settings["formal"]:
        prompt, hashes = settings["prompt"], settings["prompt_hashes"]
    else:
        prompt, hashes = pilot_prompt(settings["research_seconds"])
    (directory / "instruction.md").write_text(prompt)
    quoted = json.dumps
    (directory / "task.toml").write_text(f'''schema_version = "1.4"
artifacts = [{{source = "/logs/artifacts", exclude = ["*", "**/*"]}}]
[task]
name = "{'sciresearch' if settings['formal'] else 'sciresearch-pilot'}/{settings['task']}"
description = "Public development research; host-controlled registration"
authors = []
[agent]
timeout_sec = {float(settings['research_seconds'])}
user = "researcher"
network_mode = "allowlist"
allowed_hosts = [{quoted(relay_host)}]
[environment]
network_mode = "public"
docker_image = {quoted(research_image)}
build_timeout_sec = 600.0
cpus = {settings['research_vcpu']}
memory_mb = {settings['research_memory_bytes'] // 1024**2}
workdir = "/workspace"
mcp_servers = []
[verifier]
environment_mode = "separate"
timeout_sec = 1200.0
network_mode = "no-network"
[verifier.environment]
network_mode = "no-network"
docker_image = {quoted(numeric_image)}
cpus = 1
memory_mb = 512
workdir = "/tmp"
''')
    return {"files": tree_hashes(directory), "prompt_source_sha256": hashes,
            "public_input_sha256": tree_hashes(public_root), "image_mode": "pinned_prebuilt_with_fresh_public_task"}


def trial_config(output, task, admission, overlay, replay_config, *, settings=None):
    settings = settings or pilot_settings()
    validate_admission(admission)
    verifier = (VerifierConfig(import_path="runner.study:RegistrationVerifier",
                              kwargs={"registry_root": str(output / "registry"), "task_name": settings["task"]})
                if settings["formal"] else VerifierConfig(import_path="runner.harbor_verifier:ResearchReplayVerifier",
                    kwargs={"registry_root": str(output / "registry"), "replay_config": replay_config}))
    return TrialConfig(task=TaskConfig(path=task), trial_name=settings.get("attempt_id", "heat-pilot-" + uuid.uuid4().hex[:12]),
        trials_dir=output / "harbor", agent=AgentConfig(name="pi", model_name="anthropic/deepseek-v4-pro",
            model_base_url=admission["base_url"], model_api_key_name="BENCH_RELAY_KEY", model_api_format="anthropic_messages",
            env={"BENCH_RELAY_KEY": admission["token"], "ANTHROPIC_OAUTH_TOKEN": ""},
            kwargs={"version": "0.84.1", "reasoning_effort": "off", "max_turns": settings["max_turns"]},
            override_timeout_sec=settings["research_seconds"], override_setup_timeout_sec=600, exclude_logs=["*", "**/*"]),
        environment=EnvironmentConfig(import_path="runner.harbor_environment:ResearchDockerEnvironment",
            stream=False, delete=True, extra_docker_compose=[overlay], cpu_enforcement_policy="limit", memory_enforcement_policy="limit",
            kwargs={"auto_mounting": False, "enable_environment_dir_upload": False,
                    "pilot_audit_root": str(output / "environment-audit"), "formal": settings["formal"]}),
        verifier=verifier)


def exception_name(result):
    info = getattr(result, "exception_info", None)
    return None if info is None else info.exception_type


def verify_model_credential(agent, admission):
    connection = agent.model_connection
    if connection.api_key != admission["token"]:
        raise RuntimeError("native Pi did not resolve the temporary relay credential")
    provider_keys = {value for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
                     if (value := os.environ.get(name)) and value != admission["token"]}
    values = list(connection.env.values()) + list(agent.extra_env.values())
    if any(value in provider_keys for value in values):
        raise RuntimeError("native Pi environment unexpectedly contains a provider credential")
    return {"native_api_key_matches_relay_token": True, "provider_credential_absent_from_native_env": True}


def container_records(infos, token):
    provider_keys = {value for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
                     if (value := os.environ.get(name)) and value != token}
    records = []
    for item in infos:
        env = item["Config"].get("Env") or []
        if any(value.partition("=")[2] in provider_keys for value in env):
            raise RuntimeError("R/sidecar container environment unexpectedly contains a provider credential")
        record = {key: item[key] for key in ("Id", "Image", "HostConfig", "Mounts")}
        record["Config"] = {key: item["Config"].get(key) for key in ("User", "Labels")}
        record["Config"]["environment_variable_names"] = [value.partition("=")[0] for value in env]
        records.append(sanitize_auxiliary(record, token))
    return records


class PilotController:
    def __init__(self, output, public_root, numeric_image, admission, *, settings=None):
        self.settings = settings or pilot_settings()
        settings = self.settings
        self.output, self.public_root = Path(output), Path(public_root)
        self.numeric_image, self.admission = numeric_image, admission
        self.trial = self.registry = self.bridge_thread = self.watchdog = None
        self.cid = None
        self.stop_bridge = threading.Event()
        self.bridge_errors, self.cleanup_errors = [], {}
        self.events, self.events_lock = [], threading.Lock()
        self.stopped = False
        self.deadline_fired = False
        self.cancelled = False
        self.agent_started_at = None
        self.closed = None
        self.record = {"formal": settings["formal"], "task": settings["task"], "group": settings["group"],
                       "study_phase": "public-dev" if settings["formal"] else "public-dev-pilot",
                       "replay_split": None if settings["formal"] else "pilot-smoke",
                       "resource_status": "frozen_contract_pending_runtime_admission" if settings["formal"] else "local_pilot_diagnostic",
                       "research_budget_seconds": settings["research_seconds"], "relay_ttl_seconds": settings["relay_ttl_seconds"],
                       "max_turns": settings["max_turns"], "max_evaluations": settings["max_evaluations"],
                       "root_helper_capabilities": ROOT_CAPS, "root_helper_capabilities_reason": CAP_REASON,
                       "model_run_started": False, "relay": admission_public(admission),
                       "cost_usd": None, "status": "starting", "started_at": time.time()}
        if settings["formal"]:
            self.record.update({key: settings[key] for key in ("run_id", "attempt_id", "parent_attempt", "session_id", "repeat", "plan_ref")})
            self.record.update(evaluation_status="not_run", score=None, reward=None)

    def redact(self, value):
        return str(value).replace(self.admission["token"], "[RELAY_SESSION_TOKEN_REDACTED]")

    def event(self, kind, **fields):
        with self.events_lock:
            row = {"time": time.time(), "kind": kind, "fields": fields,
                   "previous_hash": self.events[-1]["event_hash"] if self.events else "0" * 64}
            row["event_hash"] = digest(canonical(row))
            self.events.append(row)
            with (self.output / "host-events.jsonl").open("ab") as stream:
                stream.write(canonical(row) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())

    async def hook(self, event):
        self.event(event.event.value, native_exception=exception_name(event.result))
        if event.event == TrialEvent.AGENT_START:
            await self.admit()
        elif event.event == TrialEvent.AGENT_END:
            await self.stop_research()
        elif event.event == TrialEvent.VERIFICATION_START:
            await self.stop_research()
            await self.inspect_session(self.trial.agent_environment.session_id)
            await self.close_registry(event.result)
        elif event.event == TrialEvent.CANCEL:
            self.cancelled = True
            await self.stop_research()
        elif event.event == TrialEvent.END:
            await self.stop_research()
            if self.registry is not None and self.closed is None:
                await self.close_registry(event.result)

    async def admit(self):
        env = self.trial.agent_environment
        ids = command(["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=" + env.session_id]).stdout.split()
        infos = json.loads(command(["docker", "inspect", *ids]).stdout) if ids else []
        main = [item for item in infos if item["Config"]["Labels"].get("com.docker.compose.service") == "main"]
        if len(main) != 1 or any(item["Mounts"] for item in infos):
            raise RuntimeError("unexpected R containers or host mounts")
        sidecars = [item for item in infos if item["Config"]["Labels"].get("com.docker.compose.service") == "harbor-docker-egress-control-sidecar"]
        if not (len(infos) == 2 and len(sidecars) == 1 and sidecars[0]["HostConfig"]["Memory"] == 134217728
                and sidecars[0]["HostConfig"]["MemorySwap"] == 134217728 and sidecars[0]["HostConfig"]["NanoCpus"] == 250000000):
            raise RuntimeError("sidecar resource admission failed")
        item = main[0]
        hc = item["HostConfig"]
        if hc["Privileged"] or hc["PidMode"] == "host" or hc["NetworkMode"] == "host":
            raise RuntimeError("unsafe R host namespace")
        if set(cap.removeprefix("CAP_") for cap in hc["CapAdd"]) != set(ROOT_CAPS) or hc["CapDrop"] != ["ALL"]:
            raise RuntimeError("R capability configuration differs from the host contract")
        if (hc.get("NanoCpus") != self.settings["research_vcpu"] * 10**9
                or hc.get("Memory") != self.settings["research_memory_bytes"]
                or hc.get("MemorySwap") != self.settings["research_memory_bytes"]
                or hc.get("PidsLimit") != 128):
            raise RuntimeError("R Docker resource limits differ from the research contract")
        self.cid = item["Id"]
        write_json(self.output / "research-containers.json", container_records(infos, self.admission["token"]))
        await env.upload_dir(self.public_root, "/input")
        permission = await env.exec(command="chown -R root:root /input && chmod -R a-w /input", user="root")
        if permission.return_code:
            raise RuntimeError("could not make public inputs read-only")
        with env.with_default_user("researcher"):
            program = "import hashlib,json,pathlib; r=pathlib.Path('/input'); p=sorted(r.rglob('*')); assert not any(x.is_symlink() for x in p); print(json.dumps({x.relative_to(r).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in p if x.is_file()}))"
            actual = await env.exec(command="python -I -c " + shlex.quote(program), timeout_sec=15)
            if actual.return_code or json.loads(actual.stdout) != tree_hashes(self.public_root):
                raise RuntimeError("actual R public input hash mismatch")
            self.record["actual_input_sha256"] = json.loads(actual.stdout)
            security = await env.exec(command="python -I -c " + shlex.quote(SECURITY_PROGRAM), timeout_sec=10)
            privileges = await env.exec(command="python -I -c " + shlex.quote(SOCKET_PRIVILEGES_PROGRAM), timeout_sec=10)
            if security.return_code or privileges.return_code:
                raise RuntimeError("R security inspection failed")
            state, sockets = json.loads(security.stdout), json.loads(privileges.stdout)
            if not (state["uid"] == 1000 and state["cap_eff"] == "0000000000000000" and state["no_new_privs"] == "1"
                    and not any(state[key] for key in ("cap_net_admin", "cap_net_raw", "docker_socket_present", "docker_host_env_present", "host_mount_paths_present"))
                    and state["cgroup"] == {"cpu.max": f"{self.settings['research_vcpu'] * 100000} 100000",
                                           "memory.max": str(self.settings["research_memory_bytes"]), "memory.swap.max": "0", "pids.max": "128"}
                    and all(sockets[key]["permission_denied"] for key in ("marked_socket", "raw_socket"))):
                raise RuntimeError("R privilege/resource admission failed")
            self.record.update(research_security=state, socket_privileges=sockets)
            # Native Pi run rewrites this config. Exercise exactly its existing
            # writer now; the approved root capabilities must work before model use.
            agent = self.trial.agent
            self.record["model_credential_admission"] = verify_model_credential(agent, self.admission)
            config = agent._build_custom_models_json(agent.model_connection, "deepseek-v4-pro")
            await agent._write_custom_models_json(env, config)
            if self.settings["max_turns"] is not None:
                await agent._write_max_turns_extension(env, self.settings["max_turns"])
            fresh_status = await asyncio.to_thread(transport().read_status, self.admission)
            self.record["native_setup_evidence"] = await native_setup_evidence(agent, env, config, fresh_status, settings=self.settings)
            self.record["relay_network_probe"] = await transport().lock_and_probe(env, self.admission, self.output / "relay-network-probe")
            await env.seal_research_network(NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=[self.admission["relay_ip"]]))
        imported = self.output / ("workspace" if self.settings["formal"] else "imported-workspace")
        imported.mkdir()
        self.registry = Registry.create(self.output / "registry", imported, self.settings["task"], self.settings["group"],
                                        self.settings["research_seconds"], self.settings["max_evaluations"])
        bridge = FileBridge(self.cid, self.registry, self.public_root, self.numeric_image, self.output / "file-bridge")
        def serve():
            try:
                bridge.serve(stop_event=self.stop_bridge, interval=.4)
            except Exception as exc:
                if not self.stop_bridge.is_set():
                    self.bridge_errors.append(self.redact(f"{type(exc).__name__}: {exc}"))
                    self.stop_bridge.set()
                    try:
                        command(["docker", "stop", "--time", "0", self.cid], timeout=30)
                    except Exception:
                        pass
        self.bridge_thread = threading.Thread(target=serve, name="harbor-pilot-file-bridge", daemon=True)
        self.bridge_thread.start()
        self.agent_started_at = read_json(self.registry.root / "state.json")["started_at"]
        def deadline_stop():
            self.deadline_fired = True
            self.event("host_research_deadline")
            try:
                command(["docker", "stop", "--time", "0", self.cid], timeout=30)
            except Exception as exc:
                self.cleanup_errors["deadline_stop"] = self.redact(exc)
        self.watchdog = threading.Timer(max(.01, self.agent_started_at + self.settings["research_seconds"] - time.time()), deadline_stop)
        self.watchdog.daemon = True
        self.watchdog.start()
        self.record["model_run_started"] = True
        self.event("research_admitted", input_hashes=self.record["actual_input_sha256"])

    async def stop_research(self):
        if self.stopped:
            return
        self.stopped = True
        self.record["research_stop_requested_at"] = time.time()
        self.stop_bridge.set()
        if self.cid:
            try:
                stopped = await asyncio.to_thread(command, ["docker", "stop", "--time", "0", self.cid], timeout=30)
                self.record["research_stop_returncode"] = stopped.returncode
            except BaseException as exc:
                self.cleanup_errors["research_stop"] = self.redact(exc)
        if self.watchdog:
            try:
                self.watchdog.cancel()
                await asyncio.to_thread(self.watchdog.join, 35)
                if self.watchdog.is_alive():
                    raise RuntimeError("deadline thread remains active")
            except BaseException as exc:
                self.cleanup_errors["watchdog"] = self.redact(exc)
        if self.bridge_thread:
            try:
                await asyncio.to_thread(self.bridge_thread.join, 150)
                if self.bridge_thread.is_alive():
                    raise RuntimeError("accepted public evaluation remains active")
            except BaseException as exc:
                self.cleanup_errors["bridge_join"] = self.redact(exc)
        if self.cid and self.record.get("research_stop_returncode") == 0:
            try:
                auxiliary = self.output / "auxiliary-agent"
                self.record["auxiliary_logs"] = await asyncio.to_thread(retain_logs, self.cid, auxiliary, self.admission["token"])
                self.record["auxiliary_usage"] = auxiliary_usage(auxiliary)
            except BaseException as exc:
                self.record["auxiliary_log_error"] = self.redact(exc)
        self.event("research_stopped", cleanup_errors=self.cleanup_errors, bridge_errors=self.bridge_errors)

    async def inspect_session(self, session_id):
        findings = {}
        for name, argv in (("containers", ["docker", "ps", "-aq"]), ("networks", ["docker", "network", "ls", "-q"]), ("volumes", ["docker", "volume", "ls", "-q"])):
            try:
                findings[name] = command(argv + ["--filter", "label=com.docker.compose.project=" + session_id], timeout=30).stdout.split()
                if findings[name]:
                    raise RuntimeError("own resources remain")
            except BaseException as exc:
                self.cleanup_errors[session_id + "/" + name] = self.redact(exc)
                findings.setdefault(name, ["inspection_failed"])
        self.record.setdefault("resource_checks", {})[session_id] = findings

    def outcome(self, native_result):
        native_error = exception_name(native_result)
        if self.cleanup_errors or self.bridge_errors:
            return "infrastructure_failed", "host cleanup or file bridge failed"
        interrupted = self.cancelled or self.deadline_fired or native_error in ("CancelledError", "AgentTimeoutError")
        relay_failure = relay_outcome(self.record.get("relay_status"), interrupted=interrupted)
        if relay_failure:
            return relay_failure
        if self.cancelled or native_error == "CancelledError":
            return "cancelled", "host trial was cancelled"
        if self.deadline_fired or native_error == "AgentTimeoutError":
            return "research_timeout", "host/native research wall budget reached"
        if self.record["relay_status"].get("budget_exhausted") is True:
            # A relay-local quota rejection does not overwrite the successful
            # upstream outcome. A real terminal upstream error was classified
            # above and must not be hidden by its conservative token charge.
            quota = "request quota" if self.record["relay_status"].get("remaining_output_tokens", 0) > 0 else "output token quota"
            return "research_timeout", "trusted relay " + quota + " exhausted"
        if native_error:
            return "infrastructure_failed", "native trial failed: " + native_error
        if not self.record["model_run_started"]:
            return "infrastructure_failed", "research admission did not complete"
        return "completed", ("native Pi returned" if self.settings["max_turns"] is None else
                             "native Pi returned; turn limit may have stopped further turns")

    async def close_registry(self, native_result):
        if self.closed is not None:
            return
        if self.registry is None:
            raise RuntimeError("verification requires an admitted host registry")
        if self.bridge_thread and self.bridge_thread.is_alive():
            raise RuntimeError("cannot close registry while a public evaluation is active")
        try:
            drain_deadline = time.monotonic() + 135
            while True:
                status = await asyncio.to_thread(transport().read_status, self.admission)
                self.record["relay_status"] = status
                if not status.get("inflight") or time.monotonic() >= drain_deadline:
                    break
                await asyncio.sleep(.25)
        except BaseException as exc:
            self.cleanup_errors["relay_status"] = self.redact(exc)
        status, reason = self.outcome(native_result)
        evidence = {"attempt_status": status, "reason": reason, "native_exception": exception_name(native_result),
                    "deadline_fired": self.deadline_fired, "cleanup_errors": self.cleanup_errors,
                    "bridge_errors": self.bridge_errors, "relay_status": self.record.get("relay_status")}
        write_json(self.output / "host-termination.json", evidence)
        self.closed = self.registry.close(attempt_status=status, reason=reason,
                                         evidence_sha256=file_hash(self.output / "host-termination.json"))
        self.record.update(attempt_status=status, registry=self.closed)
        self.event("registry_closed", attempt_status=status, first_id=self.closed["first_id"], final_id=self.closed["final_id"])

    async def finish(self):
        try:
            try:
                await self.stop_research()
            except BaseException as exc:
                self.cleanup_errors["research_stop_unexpected"] = self.redact(exc)
            if self.trial is not None:
                try:
                    await asyncio.wait_for(self.trial.agent_environment.stop(delete=True), 90)
                except BaseException as exc:
                    self.cleanup_errors["environment_stop"] = self.redact(exc)
            if not self.bridge_thread or not self.bridge_thread.is_alive():
                try:
                    self.record["worker_cleanup"] = await asyncio.to_thread(cleanup_own_workers, self.output / "registry/evaluations")
                    if not self.record["worker_cleanup"]["all_removed"]:
                        raise RuntimeError("own worker cleanup failed")
                except BaseException as exc:
                    self.cleanup_errors["worker_cleanup"] = self.redact(exc)
            for path in sorted((self.output / "environment-audit").glob("*.json")):
                if path.name.endswith("compose.json"):
                    continue
                try:
                    await self.inspect_session(read_json(path)["session_id"])
                except BaseException as exc:
                    self.cleanup_errors["environment_audit"] = self.redact(exc)
            if self.registry is not None and self.closed is None:
                try:
                    await self.close_registry(self.trial.result)
                except BaseException as exc:
                    self.cleanup_errors["registry_close"] = self.redact(exc)
        finally:
            try:
                self.record["relay_cleanup"] = await asyncio.to_thread(transport().cleanup_relay, self.admission)
                if self.record["relay_cleanup"].get("all_removed") is not True or self.record["relay_cleanup"].get("errors"):
                    raise RuntimeError("relay removal/evidence could not be verified")
            except BaseException as exc:
                self.cleanup_errors["relay_cleanup"] = self.redact(exc)
            try:
                native_dir = self.trial.paths.trial_dir if self.trial else None
                self.record["relay_evidence_sha256"] = retain_safe_records(self.output, native_dir, self.admission)
            except BaseException as exc:
                self.cleanup_errors["record_retention"] = self.redact(exc)
            self.record.update(cleanup_errors=self.cleanup_errors, bridge_errors=self.bridge_errors,
                               finished_at=time.time(), cost_usd=None)
            if self.settings["formal"]:
                self.record.setdefault("attempt_status", "infrastructure_failed")
                valid = (not self.cleanup_errors and not self.bridge_errors and self.closed is not None
                         and self.record.get("registration_status") == "registered"
                         and self.record.get("attempt_status") in ("completed", "research_timeout"))
                self.record.update(status="research_frozen" if valid else "research_invalid",
                                   evaluation_status="not_run", replay_split=None, score=None, reward=None)
            else:
                self.record["status"] = "pilot_completed" if (not self.cleanup_errors and self.record.get("evaluation_status") == "valid"
                    and self.record.get("attempt_status") in ("completed", "research_timeout")) else "pilot_invalid"
                if self.record["status"] != "pilot_completed":
                    self.record.update(evaluation_status="invalid", score=None, reward=None)
            write_json(self.output / "result.json", sanitize_auxiliary(self.record, self.admission["token"]))


async def run(args, *, session_spec=None):
    settings = pilot_settings()
    capacity = None
    if session_spec is not None:
        # Direct programmatic calls have the same gate as the study CLI. This
        # must precede mkdir, image inspection, relay allocation and Trial.create.
        from .study import validate_session
        validate_session(session_spec)
        if Path(session_spec["project"]).resolve() != Path(__file__).resolve().parents[1]:
            raise ValueError("formal controller must execute from the frozen project source")
        settings = session_spec["settings"]
        capacity = require_host_capacity(settings)
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    controller = None
    admission = None
    failure = {"formal": settings["formal"], "task": settings["task"], "group": settings["group"],
               "study_phase": "public-dev" if settings["formal"] else "public-dev-pilot",
               "replay_split": None if settings["formal"] else "pilot-smoke",
               "status": "research_invalid" if settings["formal"] else "pilot_invalid",
               "attempt_status": "infrastructure_failed", "evaluation_status": "not_run" if settings["formal"] else "invalid",
               "model_run_started": False, "score": None, "reward": None}
    if settings["formal"]:
        failure.update({key: settings[key] for key in ("run_id", "attempt_id", "parent_attempt", "session_id", "repeat", "plan_ref")})
    try:
        public_root = args.public_input.resolve(strict=True)
        research_public_input(public_root, settings["task"])
        if not settings["formal"]:
            pilot_input, pilot_truth = args.pilot_input.resolve(strict=True), args.pilot_truth.resolve(strict=True)
            validate_manifest("heat", pilot_input, expected_split="pilot-smoke")
            if pilot_truth.name != "pilot-smoke" or not pilot_truth.is_dir():
                raise ValueError("pilot truth must be an explicit pilot-smoke directory")
        for image in (args.research_image, args.numeric_image):
            if IMAGE_ID.fullmatch(image) is None or json.loads(command(["docker", "image", "inspect", image]).stdout)[0]["Id"] != image:
                raise ValueError("image is not the requested immutable local ID")
        sources = retain_controller_sources(output)
        if settings["formal"]:
            for name in ("common.md", settings["group"] + ".md"):
                source = root / "prompts" / settings["task"] / name
                target = output / "controller_snapshot" / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(source.read_bytes())
                    target.chmod(0o444)
                sources[source.relative_to(root).as_posix()] = file_hash(source)
            write_json(output / "controller-snapshot-manifest.json", {"capture_stage": "before_container_start", "files_sha256": sources})
        admission = (transport().load_admission(args.relay_admission) if args.relay_admission else
                     await asyncio.to_thread(transport().start_relay, root / "build" / ("relay-" + uuid.uuid4().hex[:12]),
                                             image=args.numeric_image, session_seconds=settings["relay_ttl_seconds"],
                                             session_output_limit=settings["session_output_limit"],
                                             request_output_limit=settings["request_output_limit"],
                                             expected_system_sha256=settings.get("expected_system_sha256"),
                                             expected_tools_sha256=settings.get("expected_tools_sha256")))
        validate_admission(admission)
        private_root = Path(admission["output_root"]).resolve()
        if not private_root.is_relative_to((root / "build").resolve()) or not Path(admission["admission_path"]).resolve().is_relative_to(private_root):
            raise ValueError("private relay admission must remain in the ignored benchmark/build directory")
        controller = PilotController(output, public_root, args.numeric_image, admission, settings=settings)
        controller.record["trusted_source_sha256"] = sources
        if capacity is not None:
            controller.record["physical_resource_admission"] = capacity
        task = output / "build/task"
        controller.record["task_build"] = build_task(task, public_root, args.research_image, args.numeric_image, admission["relay_ip"], settings=settings)
        overlay = {"services": {"main": {"cap_drop": ["ALL"], "cap_add": ROOT_CAPS,
            "security_opt": ["no-new-privileges:true"], "pids_limit": 128,
            "mem_limit": settings["research_memory_bytes"], "memswap_limit": settings["research_memory_bytes"]},
            "harbor-docker-egress-control-sidecar": {"cpus": .25, "mem_limit": "128m", "memswap_limit": "128m"}}}
        relay_overlay = transport().relay_overlay(admission)
        for service, fields in relay_overlay.get("services", {}).items():
            overlay["services"].setdefault(service, {}).update(fields)
        overlay.update({key: value for key, value in relay_overlay.items() if key != "services"})
        overlay_path = output / "research-security-compose.json"
        write_json(overlay_path, overlay)
        replay = None if settings["formal"] else {
            "task": "heat", "input_root": str(pilot_input), "truth_root": str(pilot_truth),
            "output_root": str(output / "replays"), "image": args.numeric_image,
            "judge_source_root": str(prepare_judge(root, output / "build/judge")), "profile": None}
        config = trial_config(output, task, admission, overlay_path, replay, settings=settings)
        trial = controller.trial = await Trial.create(config)
        if not isinstance(trial, SingleStepTrial):
            raise RuntimeError("pilot requires native SingleStepTrial")
        controller.record["model_credential_admission"] = verify_model_credential(trial.agent, admission)
        # Harbor's own env serialization is templated; also redact runtime log
        # messages before they reach the host file handler.
        if trial._log_handler is not None:
            trial._log_handler.setFormatter(RedactingFormatter(admission["token"]))
        for event in TrialEvent:
            trial.add_hook(event, controller.hook)
        write_json(output / "result.json", controller.record)
        result = await trial.run()
        controller.record["native_result_path"] = str(trial.paths.result_path)
        controller.record["native_exception"] = exception_name(result)
        controller.record["native_reward_valid"] = result.reward_valid
        controller.record["trusted_budget_override"] = (exception_name(result) not in (None, "AgentTimeoutError")
            and controller.record.get("attempt_status") == "research_timeout")
        diagnostic_path = trial.paths.verifier_dir / ("research-registration.json" if settings["formal"] else "research-replay.json")
        if diagnostic_path.is_file():
            diagnostics = read_json(diagnostic_path)
            if settings["formal"]:
                controller.record["registration_status"] = diagnostics["registration_status"]
            else:
                controller.record.update(evaluation_status=diagnostics["evaluation_status"],
                                         reward=diagnostics["reward"], score=diagnostics["score"])
        if exception_name(result) not in (None, "AgentTimeoutError") and controller.record.get("attempt_status") != "research_timeout":
            controller.record.update(evaluation_status="invalid", reward=None, score=None)
    except asyncio.CancelledError:
        if controller:
            controller.cancelled = True
        failure["error"] = "host controller cancelled"
    except BaseException as exc:
        failure["error"] = (controller.redact(exc) if controller else str(exc))[:2048]
        if controller:
            controller.cleanup_errors["controller"] = failure["error"]
    finally:
        if controller:
            await controller.finish()
        else:
            if admission:
                try:
                    failure["relay_cleanup"] = await asyncio.to_thread(transport().cleanup_relay, admission)
                except BaseException as exc:
                    failure["cleanup_error"] = str(exc)[:2048]
            write_json(output / "result.json", failure)
    result = read_json(output / "result.json")
    print(json.dumps({key: result.get(key) for key in ("status", "formal", "model_run_started", "score", "reward")}))
    return result


async def run_research_session(spec):
    """Formal single-session entry; there are deliberately no truth/replay args."""
    args = argparse.Namespace(public_input=Path(spec["public_input"]), output_root=Path(spec["output_root"]),
                              research_image=spec["research_image"], numeric_image=spec["numeric_image"],
                              relay_admission=None)
    return await run(args, session_spec=spec)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("public-input", "pilot-input", "pilot-truth", "output-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("research-image", "numeric-image"):
        parser.add_argument("--" + name, required=True, help="Immutable local sha256 image ID")
    parser.add_argument("--relay-admission", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run(args))
    if result["status"] != "pilot_completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
