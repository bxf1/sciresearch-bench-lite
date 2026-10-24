"""Thin, real Harbor/Pi heat pilot with a host-polled public-only file bridge.

This is deliberately not a formal condition launcher. No private truth or
final-test argument exists. Native Pi installation/configuration/run remain in
Harbor; the controller owns resource/policy checks, deadline and host records.
"""
from __future__ import annotations

import argparse
import base64
import asyncio
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile
import threading
import time
import uuid

from harbor.agents.installed.pi import Pi
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.task.config import EnvironmentConfig, NetworkMode, NetworkPolicy
from harbor.models.trial.paths import TrialPaths

from .artifact_gate import MAX_FILES, MAX_SOURCE, regular_tree
from .common import canonical, digest, file_hash, read_json, tree_hashes, write_json
from .file_bridge import FileBridge
from .model_smoke import RedactingFormatter
from .phase import validate_manifest
from .registry import Registry
from .research_network_probe import REACHABILITY_PROGRAM, SECURITY_PROGRAM, SOCKET_PRIVILEGES_PROGRAM

ROOT_CAPS = ["CHOWN", "DAC_OVERRIDE", "FOWNER"]
CAP_REASON = ("Harbor's native Pi config writer uploads as root, traverses the researcher's 0700 "
              "config directory, then chowns and chmods the file. These capabilities are available "
              "only to host-issued trusted root helpers; researcher is UID 1000 with CapEff=0, "
              "NoNewPrivs=1 and neither NET_ADMIN nor NET_RAW.")
MAX_LOG_BYTES = 16 * 1024**2
MAX_LOG_FILE = 4 * 1024**2


def command(argv, *, timeout=30, check=True):
    process = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if check and process.returncode:
        raise RuntimeError(f"{argv[:2]} failed ({process.returncode}): {process.stderr[-2000:]}")
    return process


def cleanup_own_workers(evaluations_root):
    """Inspect only containers recorded by this run's trusted worker metadata."""
    records, errors = [], {}
    if not evaluations_root.exists():
        return {"records": records, "errors": errors, "all_removed": True}
    if evaluations_root.is_symlink():
        raise ValueError("worker metadata directory must not be a symlink")
    for directory in sorted(evaluations_root.iterdir()):
        if not re.fullmatch(r"candidate-[0-9]{3,}", directory.name):
            continue
        row = {"candidate_id": directory.name}
        records.append(row)
        try:
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError("worker metadata directory must be a regular directory")
            metadata = {}
            for filename in ("worker.json", "container.json"):
                path = directory / filename
                if path.is_symlink():
                    raise ValueError("worker metadata must not be a symlink")
                if path.exists():
                    if not path.is_file() or path.stat().st_size > 1024**2:
                        raise ValueError("invalid worker metadata file")
                    metadata[filename] = read_json(path)
            name = metadata.get("worker.json", {}).get("container_name")
            identity = metadata.get("container.json", {}).get("Id")
            if name is not None and not re.fullmatch(r"sciresearch-w-[0-9a-f]{12}", name):
                raise ValueError("invalid recorded worker container name")
            if identity is not None and not re.fullmatch(r"[0-9a-f]{64}", identity):
                raise ValueError("invalid recorded worker container ID")
            if name is None and identity is None:
                row.update(status="no_container_record", remaining=[])
                continue
            selector = "id=" + identity if identity else "name=^/" + name + "$"
            argv = ["docker", "ps", "-aq", "--no-trunc", "--filter", selector]
            row["recorded_container"] = identity or name
            found = command(argv, timeout=15).stdout.split()
            if len(found) > 1 or any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in found):
                raise RuntimeError("unexpected worker container inspection response")
            if identity and found and found != [identity]:
                raise RuntimeError("worker ID inspection did not match recorded ID")
            row["found"] = found
            if found:
                command(["docker", "rm", "-f", found[0]], timeout=15)
            row["remaining"] = command(argv, timeout=15).stdout.split() if found else []
            if row["remaining"]:
                raise RuntimeError("recorded worker container remains after removal")
            row["status"] = "removed_or_absent"
        except Exception as exc:
            errors[directory.name] = f"{type(exc).__name__}: {exc}"
            row["status"] = "cleanup_failed"
    return {"records": records, "errors": errors, "all_removed": not errors}


def public_input(root):
    manifest = validate_manifest("heat", root, expected_split="public-dev")
    expected = {"manifest.json"}
    for case in manifest["cases"]:
        expected.update(f"{case['path']}/{name}" for name in ("metadata.json", "observations.csv", "target_grid.npy"))
    actual = {p.relative_to(root).as_posix() for p in regular_tree(root, MAX_SOURCE, MAX_FILES)}
    if actual != expected:
        raise ValueError("Only the six heat public-dev cases and their public files are allowed")
    return manifest


def retain_controller_sources(output):
    root = Path(__file__).resolve().parents[1]
    paths = sorted(path for folder in ("runner", "public", "judge") for path in (root / folder).rglob("*.py"))
    paths += [root / "prompts/heat/common.md", root / "prompts/heat/g1.md"]
    hashes = {}
    for path in paths:
        if path.is_symlink():
            raise ValueError("trusted source must not be a symlink")
        relative = path.relative_to(root)
        data = path.read_bytes()
        target = output / "controller_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o444)
        hashes[relative.as_posix()] = digest(data)
    write_json(output / "controller-snapshot-manifest.json", {"capture_stage": "before_container_start", "files_sha256": hashes})
    return hashes


def sanitize_auxiliary(value, secret, *, depth=0, counter=None):
    """Text-only auxiliary data: no attachments are decoded or written."""
    if counter is None:
        counter = [0]
    counter[0] += 1
    if depth > 48 or counter[0] > 100000:
        raise ValueError("auxiliary JSON structure quota exceeded")
    if isinstance(value, str):
        decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match[1], 16)), value)
        if secret in decoded:
            return decoded.replace(secret, "[MODEL_CREDENTIAL_REDACTED]")
        if len(value) >= 16 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", value):
            try:
                raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
                if secret.encode() in raw:
                    return "[ENCODED_MODEL_CREDENTIAL_REDACTED]"
            except ValueError:
                pass
        return value
    if isinstance(value, dict):
        if value.get("type") in ("image", "image_url", "input_image", "output_image"):
            return {"type": "omitted_attachment", "reason": "text_only_pilot"}
        return {sanitize_auxiliary(key, secret, depth=depth+1, counter=counter):
                sanitize_auxiliary(item, secret, depth=depth+1, counter=counter) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_auxiliary(item, secret, depth=depth+1, counter=counter) for item in value]
    return value


def sanitize_log_bytes(payload, secret):
    lines = payload.decode("utf-8").splitlines()
    if len(lines) > 10000:
        raise ValueError("auxiliary log event quota exceeded")
    cleaned, counter = [], [0]
    for line in lines:
        try:
            value = json.loads(line, parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
        except ValueError:
            cleaned.append(sanitize_auxiliary(line, secret, counter=counter))
        else:
            cleaned.append(canonical(sanitize_auxiliary(value, secret, counter=counter)).decode())
    result = ("\n".join(cleaned) + "\n").encode()
    if len(result) > MAX_LOG_FILE:
        raise ValueError("canonical auxiliary file exceeds quota")
    return result


def auxiliary_usage(directory):
    """Read bounded text logs; this is R-authored auxiliary usage, never reward."""
    messages = []
    for path in sorted((directory / "pi/sessions").glob("*.jsonl")):
        if path.stat().st_size > MAX_LOG_FILE:
            raise ValueError("auxiliary session exceeds quota")
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            message = row.get("message") if isinstance(row, dict) else None
            if isinstance(message, dict) and message.get("role") == "assistant":
                messages.append(message)
    totals = {key: 0 for key in ("input", "output", "cacheRead", "cacheWrite")}
    for message in messages:
        usage = message.get("usage", {})
        if not isinstance(usage, dict):
            continue
        for key in totals:
            value = usage.get(key, 0)
            if type(value) is not int or not 0 <= value <= 10**9:
                raise ValueError("invalid auxiliary usage counter")
            totals[key] += value
    return {"provenance": "R-authored bounded JSONL; auxiliary_only_not_billing_or_verdict",
            "reported_n_input_tokens_including_cache": totals["input"] + totals["cacheRead"] + totals["cacheWrite"],
            "reported_n_output_tokens": totals["output"], "reported_cache_read_tokens": totals["cacheRead"],
            "reported_cache_write_tokens": totals["cacheWrite"], "assistant_messages": len(messages),
            "assistant_messages_with_usage": sum(bool(message.get("usage", {}).get("totalTokens")) for message in messages),
            "observed_thinking_blocks": sum(sum(isinstance(part, dict) and part.get("type") == "thinking" for part in message.get("content", [])) for message in messages),
            "recorded_models": sorted({message["model"] for message in messages if isinstance(message.get("model"), str)}),
            "requested_reasoning_effort": "off", "reasoning_disable_confirmed": False, "cost_usd": None}


def pilot_prompt(budget):
    directory = Path(__file__).resolve().parents[1] / "prompts" / "heat"
    texts = {name: (directory / (name + ".md")).read_text() for name in ("common", "g1")}
    override = f"""PILOT EXECUTION CONTRACT (overrides formal-study resources/budgets in common):
This is a single infrastructure/research-loop pilot using only six public development
cases at /input. It is not a formal G1/G2/G3 study and accesses no hidden/final-test
truth or scores. You have {budget} seconds of TOTAL wall time, including evaluation
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
"""
    prompt = override + "\n" + texts["common"] + "\n" + texts["g1"] + "\n" + override
    return prompt, {name: digest(text.encode()) for name, text in texts.items()}


class BoundedReader:
    def __init__(self, stream, limit):
        self.stream, self.remaining = stream, limit

    def read(self, size=-1):
        if self.remaining <= 0:
            raise ValueError("auxiliary tar stream exceeded its quota")
        data = self.stream.read(min(self.remaining + 1, size if size >= 0 else self.remaining + 1))
        self.remaining -= len(data)
        if self.remaining < 0:
            raise ValueError("auxiliary tar stream exceeded its quota")
        return data


def retain_logs(cid, destination, secret):
    """Read a stopped R's bounded tar; never extract links or save raw secrets."""
    process = subprocess.Popen(["docker", "cp", cid + ":/logs/agent/.", "-"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timer = threading.Timer(30, process.kill)
    timer.daemon = True
    timer.start()
    retained, total, entries, retained_bytes, log_events = [], 0, 0, 0, 0
    try:
        stream = BoundedReader(process.stdout, MAX_LOG_BYTES + 1024**2)
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                entries += 1
                if entries > 256:
                    raise ValueError("too many auxiliary log entries")
                name = member.name
                while name.startswith("./"):
                    name = name[2:]
                if name in ("", "."):
                    if not member.isdir():
                        raise ValueError("invalid auxiliary tar root")
                    continue
                path = PurePosixPath(name)
                if path.is_absolute() or any(part in ("..", ".", "") for part in name.split("/")) or "\\" in name:
                    raise ValueError("unsafe auxiliary path")
                if member.isdir():
                    continue
                if not member.isfile() or member.issym() or member.islnk() or member.sparse:
                    raise ValueError("links/special auxiliary files are forbidden")
                if not (name == "pi.txt" or (len(path.parts) == 3 and path.parts[:2] == ("pi", "sessions") and name.endswith(".jsonl"))):
                    continue
                total += member.size
                if member.size > MAX_LOG_FILE or total > MAX_LOG_BYTES or len(retained) >= 128:
                    raise ValueError("auxiliary log retention quota exceeded")
                payload = archive.extractfile(member).read(member.size + 1)
                if len(payload) != member.size:
                    raise ValueError("truncated auxiliary file")
                log_events += len(payload.splitlines())
                if log_events > 10000:
                    raise ValueError("total auxiliary event quota exceeded")
                cleaned = sanitize_log_bytes(payload, secret)
                retained_bytes += len(cleaned)
                if retained_bytes > MAX_LOG_BYTES:
                    raise ValueError("canonical auxiliary total exceeds quota")
                if secret in name:
                    raise ValueError("credential appeared in auxiliary filename")
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    output.write(cleaned)
                retained.append({"path": name, "source_bytes": member.size,
                                 "retained_sha256": digest(cleaned), "credential_redacted": payload != cleaned})
        if process.wait(timeout=5):
            raise RuntimeError("auxiliary Docker copy failed")
        return {"complete": True, "files": retained, "source_bytes": total,
                "retained_bytes": retained_bytes, "retained_events": log_events,
                "max_total_bytes": MAX_LOG_BYTES, "max_file_bytes": MAX_LOG_FILE}
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()


async def run(args):
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "controller.py").write_bytes(Path(__file__).read_bytes())
    result = {"formal": False, "study_phase": "public-dev-pilot", "task": "heat", "condition": "g1-pilot",
              "model_requested": "deepseek-flash", "pi_version_requested": "0.84.1", "reasoning_effort": "off",
              "max_turns": 12, "max_evaluations": 4, "research_budget_seconds": args.budget_seconds,
              "resource_status": "local_pilot_diagnostic", "network_policy": "public_setup_then_model_allowlist",
              "root_helper_capabilities": ROOT_CAPS, "root_helper_capabilities_reason": CAP_REASON,
              "cost_usd": None, "hidden_or_final_evaluation": False, "parent_attempt": args.parent_attempt,
              "controller_sha256": file_hash(Path(__file__)), "started_at": time.time(), "status": "starting",
              "harbor_commit": "38b9be0164a910015a0be9a37ba6e8e78c562dfe", "model_run_started": False}
    result["trusted_source_sha256"] = retain_controller_sources(output)
    result["attempt_status"] = "infrastructure_failed"
    result["attempt_reason"] = "controller did not reach model completion"
    write_json(output / "result.json", result)
    secret = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    def redact(text):
        return str(text).replace(secret, "[MODEL_CREDENTIAL_REDACTED]") if secret else str(text)
    logger = logging.getLogger("benchmark.research_loop." + output.name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = logging.FileHandler(output / "harbor-host.log")
    handler.setFormatter(RedactingFormatter(secret) if secret else logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    event_lock, events = threading.Lock(), []
    def event(kind, **payload):
        with event_lock:
            row = {"time": time.time(), "kind": kind, "payload": payload,
                   "previous_hash": events[-1]["event_hash"] if events else "0" * 64}
            row["event_hash"] = digest(canonical(row))
            events.append(row)
            with (output / "host-events.jsonl").open("ab") as stream:
                stream.write(canonical(row) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
    env = registry = bridge_thread = watchdog = None
    cid = None
    stop_bridge = threading.Event()
    bridge_errors, watchdog_events = [], []
    paths = TrialPaths(output / "harbor-trial")
    paths.mkdir()
    agent = None
    deadline = None
    session_id = "bench-research-pilot-" + uuid.uuid4().hex[:12]
    result["session_id"] = session_id
    try:
        if not 300 <= args.budget_seconds <= 600:
            raise ValueError("Pilot budget must be 300 through 600 seconds")
        input_root = args.input_root.resolve(strict=True)
        public_input(input_root)
        if not secret:
            raise ValueError("Model credential unavailable; no model call made")
        endpoint = os.environ.get("ANTHROPIC_BASE_URL", "")
        if endpoint != "https://api.deepseek.com/anthropic":
            raise ValueError("Endpoint differs from the reviewed model-only domain")
        prompt, prompt_sources = pilot_prompt(args.budget_seconds)
        result.update(public_input_hashes=tree_hashes(input_root), prompt_sha256=digest(prompt.encode()),
                      prompt_source_sha256=prompt_sources, model_endpoint=endpoint,
                      model_api_format="anthropic_messages")
        write_json(output / "prompt.json", {"prompt": prompt})
        image = json.loads(command(["docker", "image", "inspect", args.image]).stdout)[0]
        numeric = json.loads(command(["docker", "image", "inspect", args.worker_image]).stdout)[0]
        if image["Id"] != args.expected_image_id:
            raise ValueError("Research image ID changed; retain attempt and review the new image")
        result.update(research_image_id=image["Id"], worker_image_id=numeric["Id"])
        overlay = {"services": {"main": {"cap_drop": ["ALL"], "cap_add": ROOT_CAPS,
            "security_opt": ["no-new-privileges:true"], "pids_limit": 128,
            "mem_limit": "1g", "memswap_limit": "1g"},
            "harbor-docker-egress-control-sidecar": {"cpus": .25, "mem_limit": "128m", "memswap_limit": "128m"}}}
        overlay_path = output / "research-security-compose.json"
        write_json(overlay_path, overlay)
        result["compose_overlay_sha256"] = file_hash(overlay_path)
        allowlist = NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=["api.deepseek.com"])
        env = DockerEnvironment(environment_dir=Path(__file__).resolve().parents[1] / "environment" / "research-smoke",
            environment_name="bench-research-pilot", session_id=session_id, trial_paths=paths,
            task_env_config=EnvironmentConfig(docker_image=image["Id"], cpus=1, memory_mb=1024, workdir="/workspace"),
            network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC), phase_network_policies=[allowlist],
            extra_docker_compose=[overlay_path], cpu_enforcement_policy="limit", memory_enforcement_policy="limit",
            auto_mounting=False, enable_environment_dir_upload=False, logger=logger)
        await asyncio.wait_for(env.start(force_build=False), 180)
        ids = command(["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=" + session_id]).stdout.split()
        infos = json.loads(command(["docker", "inspect", *ids]).stdout)
        result["containers"] = []
        for info in infos:
            hc = info["HostConfig"]
            service = info["Config"]["Labels"]["com.docker.compose.service"]
            result["containers"].append({"id": info["Id"], "service": service, "image_id": info["Image"],
                "user": info["Config"]["User"], "mounts": info["Mounts"], "host_config": {key: hc[key] for key in
                ("CapAdd", "CapDrop", "SecurityOpt", "PidsLimit", "Memory", "MemorySwap", "NanoCpus", "NetworkMode", "PidMode", "Privileged")}})
            if service == "main":
                if cid is not None or info["Mounts"] or hc["Privileged"] or hc["NetworkMode"] == "host" or hc["PidMode"] == "host":
                    raise RuntimeError("Unexpected research container/host boundary")
                cid = info["Id"]
        if cid is None:
            raise RuntimeError("Missing research container")
        sidecars = [row for row in result["containers"] if row["service"] == "harbor-docker-egress-control-sidecar"]
        if not (len(sidecars) == 1 and sidecars[0]["host_config"]["Memory"] == 134217728
                and sidecars[0]["host_config"]["MemorySwap"] == 134217728
                and sidecars[0]["host_config"]["NanoCpus"] == 250000000):
            raise RuntimeError("Sidecar resource admission failed")
        await env.upload_dir(input_root, "/input")
        permission = await env.exec(command="chown -R root:root /input && chmod -R a-w /input", user="root")
        if permission.return_code:
            raise RuntimeError("Could not make public input read-only to researcher")
        with env.with_default_user("researcher"):
            hash_program = "import hashlib,json,pathlib; r=pathlib.Path('/input'); paths=sorted(r.rglob('*')); assert not any(p.is_symlink() for p in paths); print(json.dumps({p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}))"
            actual_input = await env.exec(command="python -I -c " + shlex.quote(hash_program), timeout_sec=15)
            if actual_input.return_code or json.loads(actual_input.stdout) != result["public_input_hashes"]:
                raise RuntimeError("Actual R /input differs from selected public-dev inputs")
            result["actual_input_sha256"] = json.loads(actual_input.stdout)
            result["actual_input_exact_match_before_model"] = True
            security = await env.exec(command="python -c " + shlex.quote(SECURITY_PROGRAM), timeout_sec=10)
            privileges = await env.exec(command="python -c " + shlex.quote(SOCKET_PRIVILEGES_PROGRAM), timeout_sec=10)
            if security.return_code or privileges.return_code:
                raise RuntimeError("Could not inspect actual research privileges")
            result["research_security"] = state = json.loads(security.stdout)
            result["socket_privileges"] = sockets = json.loads(privileges.stdout)
            if not (state["uid"] == 1000 and state["cap_eff"] == "0000000000000000" and state["no_new_privs"] == "1"
                    and not state["cap_net_admin"] and not state["cap_net_raw"] and not state["docker_socket_present"]
                    and not state["docker_host_env_present"] and not state["host_mount_paths_present"]
                    and state["cgroup"] == {"cpu.max": "100000 100000", "memory.max": "1073741824", "memory.swap.max": "0", "pids.max": "128"}
                    and all(sockets[key]["permission_denied"] for key in ("marked_socket", "raw_socket"))):
                raise RuntimeError("Research process privilege/resource admission failed")
            agent = Pi(logs_dir=paths.agent_dir, logger=logger, model_name="anthropic/deepseek-flash", version="0.84.1",
                model_base_url=endpoint, model_api_key_name="BENCH_MODEL_API_KEY", model_api_format="anthropic_messages",
                extra_env={"BENCH_MODEL_API_KEY": secret, "ANTHROPIC_OAUTH_TOKEN": ""}, reasoning_effort="off", max_turns=12, mcp_servers=[])
            event("native_pi_setup_start")
            await asyncio.wait_for(agent.setup(env), 600)
            # Exercise Harbor's own config writers before admitting any model
            # call, including the root chown/chmod path for a nonroot agent.
            config = agent._build_custom_models_json(agent.model_connection, "deepseek-flash")
            await agent._write_custom_models_json(env, config)
            await agent._write_max_turns_extension(env, 12)
            version = await env.exec(command=". ~/.nvm/nvm.sh; pi --version; node --version", timeout_sec=15)
            if version.return_code:
                raise RuntimeError("Native Pi version verification failed")
            result["installed_versions"] = version.stdout.strip().splitlines()
            event("native_pi_setup_and_config_write_passed", versions=result["installed_versions"])
            await asyncio.wait_for(env.set_network_policy(allowlist), 30)
            policy = await env.service_exec("network-policy rules", service="harbor-docker-egress-control-sidecar", timeout_sec=10)
            rules = policy.stdout or ""
            (output / "sidecar-nft-rules.txt").write_text(rules)
            if policy.return_code or "gost_egress" not in rules or "redirect to :12345" not in rules:
                raise RuntimeError("Native egress rules not installed")
            result["network_checks"] = []
            for url in ("https://api.deepseek.com", "https://example.com", "https://1.1.1.1"):
                check = await env.exec(command="python -c " + shlex.quote(REACHABILITY_PROGRAM.replace("URL_PLACEHOLDER", repr(url))), timeout_sec=8)
                if check.return_code:
                    raise RuntimeError("Network probe command failed")
                result["network_checks"].append(json.loads(check.stdout))
            if not (result["network_checks"][0]["http_response"] and all(not row["http_response"] for row in result["network_checks"][1:])):
                raise RuntimeError("Network allowlist admission failed")
            imported = output / "imported-workspace"
            imported.mkdir()
            registry = Registry.create(output / "registry", imported, "heat", "g1-pilot", args.budget_seconds, 4)
            bridge = FileBridge(cid, registry, input_root, numeric["Id"], output / "file-bridge")
            def serve_bridge():
                try:
                    bridge.serve(stop_event=stop_bridge, interval=.4)
                except Exception as exc:
                    bridge_errors.append(redact(f"{type(exc).__name__}: {exc}"))
                    stop_bridge.set()
            bridge_thread = threading.Thread(target=serve_bridge, name="pilot-public-file-bridge", daemon=True)
            bridge_thread.start()
            deadline = read_json(registry.root / "state.json")["started_at"] + args.budget_seconds
            def deadline_stop():
                observed = {"fired_at": time.time()}
                watchdog_events.append(observed)
                try:
                    stopped = command(["docker", "stop", "--time", "0", cid], timeout=30, check=False)
                    observed["returncode"] = stopped.returncode
                except Exception as exc:
                    observed["error"] = redact(f"{type(exc).__name__}: {exc}")
                event("hard_wall_research_stop", **observed)
            watchdog = threading.Timer(max(.01, deadline - time.time()), deadline_stop)
            watchdog.daemon = True
            watchdog.start()
            context = AgentContext()
            result["model_run_started"] = True
            result["model_started_at"] = time.time()
            write_json(output / "result.json", result)
            event("model_run_start", budget_seconds=args.budget_seconds, max_evaluations=4, max_turns=12)
            task = asyncio.create_task(agent.run(prompt, env, context))
            try:
                while not task.done():
                    if bridge_errors:
                        raise RuntimeError("Host file bridge failed: " + bridge_errors[0])
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise TimeoutError("research wall budget exhausted")
                    await asyncio.wait({task}, timeout=min(.5, remaining))
                await task
                result["status"] = "model_returned"
                result["attempt_status"] = "research_timeout" if watchdog_events else "completed"
                result["attempt_reason"] = "host wall deadline reached" if watchdog_events else "native Pi run returned; turn budget may have stopped further turns"
            finally:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except BaseException:
                        pass
                result["model_wall_seconds"] = time.time() - result["model_started_at"]
    except asyncio.CancelledError:
        result.update(status="pilot_cancelled", attempt_status="cancelled", attempt_reason="host controller was cancelled")
    except Exception as exc:
        result["status"] = "pilot_failed"
        result["error"] = redact(f"{type(exc).__name__}: {exc}")
        at_deadline = result["model_run_started"] and deadline is not None and (bool(watchdog_events) or time.time() >= deadline)
        result["attempt_status"] = "research_timeout" if at_deadline else "infrastructure_failed"
        # Native CLI output is R-authored. Do not promote an error string in a
        # session to a trusted api_failed verdict; typed host transport evidence
        # would be needed for that narrower classification.
        result["attempt_reason"] = "host wall deadline reached" if at_deadline else result["error"]
        event("pilot_error", error=result["error"], attempt_status=result["attempt_status"])
    finally:
        stop_bridge.set()
        cleanup_errors = {}
        try:
            # Every cleanup stage is independent: one timed-out Docker command
            # must not suppress bridge drainage, native cleanup or result saving.
            if cid:
                try:
                    stopped = await asyncio.to_thread(command, ["docker", "stop", "--time", "0", cid], timeout=30, check=False)
                    result["research_stop_returncode"] = stopped.returncode
                    if stopped.returncode:
                        raise RuntimeError("research stop was not confirmed")
                except BaseException as exc:
                    cleanup_errors["research_stop"] = redact(f"{type(exc).__name__}: {exc}")
            if watchdog:
                try:
                    watchdog.cancel()
                    await asyncio.to_thread(watchdog.join, 35)
                    if watchdog.is_alive():
                        raise RuntimeError("deadline watchdog remains active")
                except BaseException as exc:
                    cleanup_errors["watchdog"] = redact(f"{type(exc).__name__}: {exc}")
            result["watchdog_events"] = watchdog_events
            if bridge_thread:
                try:
                    await asyncio.to_thread(bridge_thread.join, 150)
                    result["bridge_joined"] = not bridge_thread.is_alive()
                    if not result["bridge_joined"]:
                        raise RuntimeError("accepted evaluation remains active")
                except BaseException as exc:
                    cleanup_errors["bridge_join"] = redact(f"{type(exc).__name__}: {exc}")
            result["bridge_errors"] = bridge_errors
            if cid and result.get("research_stop_returncode") == 0:
                try:
                    result["auxiliary_logs"] = await asyncio.to_thread(retain_logs, cid, paths.agent_dir, secret)
                    if result["model_run_started"]:
                        result["model_usage_auxiliary"] = auxiliary_usage(paths.agent_dir)
                except BaseException as exc:
                    result["auxiliary_log_error"] = redact(f"{type(exc).__name__}: {exc}")
            if env:
                try:
                    await asyncio.wait_for(env.stop(delete=True), 90)
                except BaseException as exc:
                    cleanup_errors["environment_delete"] = redact(f"{type(exc).__name__}: {exc}")
            for resource, argv in (("containers", ["docker", "ps", "-aq"]), ("networks", ["docker", "network", "ls", "-q"]), ("volumes", ["docker", "volume", "ls", "-q"])):
                try:
                    check = command(argv + ["--filter", "label=com.docker.compose.project=" + session_id], check=False)
                    if check.returncode:
                        raise RuntimeError("Docker resource inspection failed")
                    result["remaining_own_" + resource] = check.stdout.split()
                except BaseException as exc:
                    result["remaining_own_" + resource] = ["inspection_failed"]
                    cleanup_errors[resource + "_inspection"] = redact(f"{type(exc).__name__}: {exc}")
            try:
                if bridge_thread and bridge_thread.is_alive():
                    raise RuntimeError("worker cleanup deferred because accepted evaluation remains active")
                workers = await asyncio.to_thread(cleanup_own_workers, output / "registry" / "evaluations")
                workers["errors"] = {key: redact(value) for key, value in workers["errors"].items()}
                result["own_worker_cleanup"] = workers
                if not workers["all_removed"]:
                    raise RuntimeError("recorded worker cleanup failed; see own_worker_cleanup")
            except BaseException as exc:
                cleanup_errors["worker_cleanup"] = redact(f"{type(exc).__name__}: {exc}")
            result["own_resources_removed"] = (not any(result.get("remaining_own_" + key, ["unknown"]) for key in ("containers", "networks", "volumes"))
                and result.get("own_worker_cleanup", {}).get("all_removed", False))
            if not result["own_resources_removed"]:
                cleanup_errors["resource_retention"] = "Own resources remain or could not be inspected"
            if cleanup_errors or bridge_errors:
                result["attempt_status"] = "infrastructure_failed"
                result["attempt_reason"] = "host cleanup or bridge failed; see retained evidence"
            outcome = {"attempt_status": result["attempt_status"], "reason": result["attempt_reason"][:2048],
                       "model_run_started": result["model_run_started"], "watchdog_events": watchdog_events,
                       "cleanup_errors": cleanup_errors, "bridge_errors": bridge_errors}
            write_json(output / "host-termination.json", outcome)
            if registry and (bridge_thread is None or not bridge_thread.is_alive()):
                try:
                    result["registry"] = registry.close(attempt_status=result["attempt_status"],
                        reason=outcome["reason"], evidence_sha256=file_hash(output / "host-termination.json"))
                    event("registry_closed", first_id=result["registry"]["first_id"], final_id=result["registry"]["final_id"])
                    result["registered_snapshot_hashes"] = {row["id"]: row["source_hash"] for row in result["registry"]["evaluations"]}
                except BaseException as exc:
                    cleanup_errors["registry_close"] = redact(f"{type(exc).__name__}: {exc}")
                    result["attempt_status"] = "infrastructure_failed"
            elif registry:
                cleanup_errors["registry_close"] = "bridge still active; registry left open rather than racing an accepted evaluation"
                result["attempt_status"] = "infrastructure_failed"
        except BaseException as exc:
            cleanup_errors["unexpected_cleanup_error"] = redact(f"{type(exc).__name__}: {exc}")
            result["attempt_status"] = "infrastructure_failed"
        finally:
            result["cleanup_errors"] = cleanup_errors
            result["finished_at"] = time.time()
            result["total_wall_seconds"] = result["finished_at"] - result["started_at"]
            result["cost_usd"] = None
            result["status"] = "pilot_" + result["attempt_status"]
            if result["attempt_status"] == "completed" and "registry" in result:
                explicit = result["registry"].get("selection_reason") == "explicit_finalize"
                result["status"] = ("pilot_registered_and_finalized" if explicit else "pilot_registered_with_fallback") if result["registry"]["evaluations"] else "pilot_no_registered_candidate"
            try:
                result["auxiliary_log_hashes"] = tree_hashes(paths.agent_dir)
            except BaseException as exc:
                result["auxiliary_log_hash_error"] = redact(f"{type(exc).__name__}: {exc}")
            try:
                write_json(output / "result.json", result)
            finally:
                logger.removeHandler(handler)
                handler.close()
    print(json.dumps({"output": str(output), "status": result["status"], "formal": False,
                      "model_run_started": result["model_run_started"], "error": result.get("error")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--image", default="sciresearch-heat-r:0.3.1")
    parser.add_argument("--expected-image-id", default="sha256:6619dd1526ec8d635d0e57d068dc3e750821ddd82443d44777fe847340944bdb")
    parser.add_argument("--worker-image", default="sciresearch-numeric:0.3.0")
    parser.add_argument("--budget-seconds", type=int, default=600)
    parser.add_argument("--parent-attempt")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
