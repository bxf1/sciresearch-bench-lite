"""Capture pinned native Pi request policy offline, before any provider request.

This is a setup precheck, never a scientific run or a formal resource acceptance.
Capture installs nothing. An explicit optional preparation step runs Harbor's
native Pi.setup in a separate installer and exports its tools to a local cache.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid

from .common import canonical, digest, file_hash, read_json, tree_hashes, write_json
from .model_relay import encoded, strict_json


TASKS = ("heat", "ode", "poisson")
MODEL = "deepseek-flash"
MARKER = "BENCH_POLICY_CAPTURE_V1 "
DUMMY_KEY = "offline-policy-capture-dummy-not-a-credential"
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_CAPTURE_BYTES = 1024 * 1024
EXPECTED_TOOLS = ["read", "bash", "edit", "write"]
COMPACTION_SOURCES = (
    "dist/core/compaction/compaction.js", "dist/core/compaction/branch-summarization.js",
    "dist/core/compaction/utils.js", "dist/core/compaction/index.js",
    "dist/core/agent-session.js", "dist/core/provider-composer.js",
    "node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js",
    "node_modules/@earendil-works/pi-ai/dist/api/simple-options.js",
)
MODELS = {"providers": {"harbor-endpoint": {
    "baseUrl": "http://127.0.0.1:9", "apiKey": "$BENCH_RELAY_KEY",
    "api": "anthropic-messages", "models": [{"id": MODEL}],
}}}

# In Pi 0.84.1 sdk.js this extension event is the native onPayload callback.
# anthropic-messages.js awaits it after buildParams and before messages.create.
# Throwing is unsafe: ExtensionRunner catches exceptions and continues. Both
# success and failure here terminate synchronously, before returning to Pi.
CAPTURE_EXTENSION = r'''import { writeSync } from "node:fs";
function emit(fd, text) {
  const bytes = Buffer.from(text);
  let position = 0;
  while (position < bytes.length) position += writeSync(fd, bytes, position);
}
export default function (pi) {
  pi.on("before_provider_request", (event) => {
    try {
      const p = event.payload;
      if (p.model !== "deepseek-flash" || p.stream !== true ||
          !Array.isArray(p.system) || !Array.isArray(p.tools)) {
        process.exit(71);
      }
      const record = {schema_version: 1, stage: "before_provider_request",
        model: p.model, stream: p.stream, requested_max_tokens: p.max_tokens,
        system: p.system, tools: p.tools};
      const text = JSON.stringify(record);
      if (Buffer.byteLength(text) > 1048576) process.exit(72);
      emit(1, "BENCH_POLICY_CAPTURE_V1 " + text + "\n");
      process.exit(0);
    } catch (_) {
      process.exit(73);
    }
  });
}
'''

# Invoke the installed native summarizer and its actual SDK serializer. The hook
# exits synchronously before HTTP. Both initial and updated summaries are checked.
COMPACTION_CAPTURE = r'''import { writeSync, realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { dirname } from 'node:path';
const root = dirname(dirname(realpathSync(process.argv[2])));
const { generateSummaryWithUsage } = await import(pathToFileURL(root + '/dist/core/compaction/compaction.js'));
const { streamSimple } = await import(pathToFileURL(root + '/node_modules/@earendil-works/pi-ai/dist/compat.js'));
const model = {id:'deepseek-flash', name:'offline capture', api:'anthropic-messages',
  provider:'harbor-endpoint', baseUrl:'http://127.0.0.1:9', reasoning:false,
  input:['text'], contextWindow:128000, maxTokens:16384,
  cost:{input:0, output:0, cacheRead:0, cacheWrite:0}};
const messages = [{role:'user',content:[{type:'text',text:'Synthetic offline policy capture.'}],timestamp:0}];
const capture = (model, context, options) => streamSimple(model, context, {...options,
  onPayload(p) {
    if ('tools' in p || p.model !== 'deepseek-flash' || p.stream !== true) process.exit(74);
    const data = Buffer.from('BENCH_COMPACTION_CAPTURE_V1 ' + JSON.stringify({
      schema_version:1, stage:'native_compaction_before_http', model:p.model,
      stream:p.stream, requested_max_tokens:p.max_tokens, system:p.system, tools_absent:true}) + '\n');
    let offset=0; while(offset<data.length) offset+=writeSync(1,data,offset);
    process.exit(0);
  }});
await generateSummaryWithUsage(messages, model, 16384, 'offline-dummy-key',
  undefined, undefined, undefined, process.argv[3]==='update' ? 'Synthetic earlier summary.' : undefined,
  'off', capture, undefined, {enabled:false});
process.exit(75);
'''

# Only immutable installed code and the public manifest are read. No case arrays
# or hidden truth paths are accessed. Source contents are retained for replay.
AUDIT_PROGRAM = r'''import hashlib,json,os,pathlib,shutil,subprocess
executable=shutil.which('pi')
assert executable, 'preinstalled Pi is missing; offline capture never installs packages'
root=pathlib.Path(executable).resolve().parent.parent
package=json.loads((root/'package.json').read_text())
assert package['name']=='@earendil-works/pi-coding-agent' and package['version']=='0.84.1', 'wrong Pi package/version'
version=subprocess.run(['pi','--version'],capture_output=True,text=True,timeout=15,check=True).stdout.strip()
assert version=='0.84.1', 'Pi executable version mismatch'
assert os.getuid()==1000 and os.getgid()==1000 and os.getcwd()=='/workspace'
manifest=json.loads(pathlib.Path('/input/manifest.json').read_text())
assert manifest['split']=='public-dev', 'capture image must contain public-dev only'
# With default native flags, any discovery source could change the wire policy.
# Fail closed instead of adding no-discovery flags that native Pi does not use.
discovery=[pathlib.Path('/tmp/harbor-pi-agent'),pathlib.Path('/workspace/.pi'),pathlib.Path('/.pi')]
assert not any(p.exists() for p in discovery), 'unexpected Pi discovery/config directory in fresh image'
contexts=[pathlib.Path('/AGENTS.md'),pathlib.Path('/workspace/AGENTS.md')]
assert not any(p.exists() for p in contexts), 'unexpected project context in fresh research image'
names=['package.json','dist/config.js','dist/core/system-prompt.js','dist/core/sdk.js',
 'dist/core/agent-session.js','dist/core/resource-loader.js','dist/core/extensions/runner.js',
 'dist/core/provider-composer.js','node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js',
 'node_modules/@earendil-works/pi-ai/dist/api/simple-options.js']
names+=sorted(p.relative_to(root).as_posix() for p in (root/'dist/core/tools').rglob('*.js'))
names+=sorted(p.relative_to(root).as_posix() for p in (root/'dist/core/compaction').glob('*.js'))
sources={name:(root/name).read_text() for name in names}
api=sources['node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js']
start=api.index('let params = buildParams(model, context, isOAuth, options);')
hook=api.index('await options?.onPayload?.(params, model)',start)
request=api.index('client.messages.create(',hook)
assert start<hook<request
assert 'return runner.emitBeforeProviderRequest(payload)' in sources['dist/core/sdk.js']
print(json.dumps({'version':version,'package_root':str(root),'uid':os.getuid(),'gid':os.getgid(),
 'cwd':os.getcwd(),'public_manifest':{k:manifest[k] for k in ('task','split')},
 'no_discovered_extensions_or_context':True,'native_hook_before_http':True,
 'source_sha256':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()},
 'sources':sources},ensure_ascii=True))
'''


def parse_capture(stdout: str) -> dict:
    records = [line[len(MARKER):] for line in stdout.splitlines() if line.startswith(MARKER)]
    if len(records) != 1 or len(records[0].encode()) > MAX_CAPTURE_BYTES:
        raise ValueError("expected one bounded native pre-request capture")
    record = strict_json(records[0].encode())
    if (record.get("schema_version") != 1 or record.get("stage") != "before_provider_request"
            or record.get("model") != MODEL or record.get("stream") is not True
            or type(record.get("requested_max_tokens")) is not int or record["requested_max_tokens"] <= 0):
        raise ValueError("invalid native policy capture receipt")
    system, tools = record.get("system"), record.get("tools")
    if not isinstance(system, list) or not system or not all(
        isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        for block in system
    ):
        raise ValueError("invalid native system JSON")
    if (not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools)
            or [tool.get("name") for tool in tools] != EXPECTED_TOOLS
            or any(not isinstance(tool.get("description"), str) or not isinstance(tool.get("input_schema"), dict)
                   for tool in tools)):
        raise ValueError("native tools differ from the default four tools")
    if any("You have a hard budget of" in block["text"] for block in system):
        raise ValueError("unexpected max-turns system extension")
    return record


def parse_compaction_capture(stdout: str) -> dict:
    marker = "BENCH_COMPACTION_CAPTURE_V1 "
    records = [line[len(marker):] for line in stdout.splitlines() if line.startswith(marker)]
    if len(records) != 1 or len(records[0].encode()) > MAX_CAPTURE_BYTES:
        raise ValueError("expected one bounded native compaction capture")
    record = strict_json(records[0].encode())
    if (record.get("schema_version") != 1 or record.get("stage") != "native_compaction_before_http"
            or record.get("model") != MODEL or record.get("stream") is not True
            or record.get("tools_absent") is not True or "tools" in record
            or type(record.get("requested_max_tokens")) is not int or record["requested_max_tokens"] <= 0
            or not isinstance(record.get("system"), list) or not record["system"]
            or any(not isinstance(block, dict) or block.get("type") != "text"
                   or not isinstance(block.get("text"), str) for block in record["system"])):
        raise ValueError("invalid native compaction capture")
    return record


def validate_container(info: dict, image: str, pi_cache: Path | None = None) -> dict:
    host, config = info["HostConfig"], info["Config"]
    expected = {"NetworkMode": "none", "NanoCpus": 1_000_000_000,
                "Memory": 1024 ** 3, "MemorySwap": 1024 ** 3, "PidsLimit": 128}
    if any(host.get(key) != value for key, value in expected.items()):
        raise ValueError("capture isolation/resource configuration mismatch")
    mounts = info.get("Mounts", [])
    expected_mounts = ([] if pi_cache is None else
                       [{"Source": str(pi_cache / "nvm"), "Destination": "/home/researcher/.nvm", "RW": False}])
    actual_mounts = [{key: item.get(key) for key in ("Source", "Destination", "RW")} for item in mounts]
    if (info.get("Image") != image or actual_mounts != expected_mounts or config.get("User") != "1000:1000"
            or config.get("WorkingDir") != "/workspace" or host.get("Privileged")
            or host.get("CapDrop") != ["ALL"] or host.get("CapAdd")
            or "no-new-privileges" not in host.get("SecurityOpt", [])):
        raise ValueError("capture container must be unprivileged, nonroot, with only the optional read-only Pi cache")
    env = dict(value.split("=", 1) for value in config.get("Env", []))
    if (env.get("BENCH_RELAY_KEY") != DUMMY_KEY
            or any(env.get(name) for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN"))):
        raise ValueError("capture container has an unexpected credential")
    return {"container_id": info["Id"], "image_id": image, "user": config["User"],
            "cwd": config["WorkingDir"], "mounts": actual_mounts, "limits": expected,
            "cap_drop": host["CapDrop"], "security_opt": host["SecurityOpt"],
            "network_disabled": True, "credentials": "dummy_only"}


async def prepare_pi_cache(image: str, cache: Path, output: Path) -> dict:
    """Run the existing Harbor Pi.setup once; no agent.run or model credentials."""
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    from harbor.agents.installed.pi import Pi
    from harbor.environments.docker.docker import DockerEnvironment
    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths
    import harbor.agents.installed.base as native_base
    import harbor.agents.installed.pi as native_pi
    import harbor.agents.installed.node_install as native_node

    cache.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    paths = TrialPaths(output / "harbor-trial")
    paths.mkdir()
    logger = logging.getLogger("benchmark.policy-capture.setup." + uuid.uuid4().hex)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = logging.FileHandler(output / "harbor-host.log")
    logger.addHandler(handler)
    session = "bench-policy-setup-" + uuid.uuid4().hex[:12]
    result = {"status": "setup_failed", "formal": False, "model_calls": 0,
              "base_image_id": image, "cache": str(cache), "session_id": session,
              "network_phase": "native installation only; no model request", "sources": {}}
    for name, module in (("pi.py", native_pi), ("base.py", native_base), ("node_install.py", native_node)):
        source = Path(module.__file__)
        (output / name).write_bytes(source.read_bytes())
        result["sources"][name] = file_hash(source)
    environment = DockerEnvironment(
        environment_dir=Path(__file__).resolve().parents[1] / "tasks/heat/environment",
        environment_name="bench-policy-setup", session_id=session, trial_paths=paths,
        task_env_config=EnvironmentConfig(docker_image=image, cpus=1, memory_mb=2048),
        cpu_enforcement_policy="limit", memory_enforcement_policy="limit", logger=logger,
        auto_mounting=False, enable_environment_dir_upload=False)
    try:
        await asyncio.wait_for(environment.start(force_build=False), 120)
        previous = await environment.exec(command="test -r /home/researcher/.nvm/nvm.sh", timeout_sec=10)
        result["base_image_has_nvm"] = previous.return_code == 0
        agent = Pi(logs_dir=paths.agent_dir, logger=logger, model_name="anthropic/deepseek-flash",
                   version="0.84.1", model_base_url="http://127.0.0.1:9",
                   model_api_key_name="BENCH_RELAY_KEY", model_api_format="anthropic_messages",
                   extra_env={"BENCH_RELAY_KEY": DUMMY_KEY, "ANTHROPIC_OAUTH_TOKEN": ""},
                   reasoning_effort="off", max_turns=None, mcp_servers=[])
        await asyncio.wait_for(agent.setup(environment), 600)
        observed = await environment.exec(command=". ~/.nvm/nvm.sh; pi --version; node --version", timeout_sec=15)
        if observed.return_code or observed.stdout.strip().splitlines()[0] != "0.84.1":
            raise RuntimeError("native Pi.setup version verification failed")
        result["versions"] = observed.stdout.strip().splitlines()
        await environment.download_dir("/home/researcher/.nvm", cache / "nvm")
        result["cache_tree_sha256"] = digest(canonical(tree_hashes(cache / "nvm")))
        result["status"] = "installed"
    except Exception as exc:
        result["error"] = str(exc)[:4096]
    finally:
        try:
            await asyncio.wait_for(environment.stop(delete=True), 60)
            result["cleanup"] = {"completed": True}
        except Exception as exc:
            result["cleanup"] = {"completed": False, "error": str(exc)[:2048]}
            result["status"] = "setup_failed"
        write_json(output / "result.json", result)
        write_json(cache / "provenance.json", result)
        logger.removeHandler(handler)
        handler.close()
    if result["status"] != "installed":
        raise RuntimeError("native Pi cache preparation failed; inspect setup/result.json")
    return result


def capture_task(task: str, image: str, output: Path, *, pi_cache: Path | None = None,
                 project: Path | None = None) -> dict:
    if task not in TASKS or not IMAGE_ID.fullmatch(image):
        raise ValueError("capture requires a known task and immutable local image ID")
    output.mkdir(parents=True, exist_ok=False)
    staging = output / "capture-source"
    staging.mkdir()
    (staging / "capture.mjs").write_text(CAPTURE_EXTENSION)
    (staging / "compaction.mjs").write_text(COMPACTION_CAPTURE)
    (staging / "models.json").write_text(json.dumps(MODELS, indent=2) + "\n")
    (staging / "audit.py").write_text(AUDIT_PROGRAM)
    name = "sciresearch-policy-capture-" + uuid.uuid4().hex[:12]
    record = {"schema_version": 1, "formal": False, "task": task, "status": "capture_failed",
              "image_id": image, "container_name": name, "model_calls": 0,
              "max_turns": None, "upstream_base_url": "http://127.0.0.1:9",
              "capture_extension_sha256": file_hash(staging / "capture.mjs"),
              "models_json_sha256": file_hash(staging / "models.json"),
              "command_evidence": "commands.json", "resource_limits_diagnostic": True}
    commands = []

    def docker(*args, timeout=30, check=True):
        command = ["docker", *map(str, args)]
        entry = {"argv": command, "timeout_seconds": timeout}
        commands.append(entry)
        write_json(output / "commands.json", commands)
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        entry.update(return_code=result.returncode,
                     stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
                     stderr_sha256=hashlib.sha256(result.stderr.encode()).hexdigest())
        write_json(output / "commands.json", commands)
        if check and result.returncode:
            raise RuntimeError("Docker command failed: " + result.stderr[-2048:])
        return result

    created = False
    started = time.monotonic()
    try:
        image_info = json.loads(docker("image", "inspect", image).stdout)[0]
        if image_info["Id"] != image:
            raise ValueError("local image ID changed")
        record["image_repo_tags"] = image_info.get("RepoTags", [])
        mount_args = [] if pi_cache is None else ["--mount", "type=bind,src=" + str(pi_cache / "nvm") + ",dst=/home/researcher/.nvm,readonly"]
        docker("create", "--name", name, "--label", "sciresearch.project=benchmark-v0.3",
               "--network", "none", "--cpus", "1", "--memory", "1g", "--memory-swap", "1g",
               "--pids-limit", "128", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--user", "1000:1000", "--workdir", "/workspace",
               "--env", "BENCH_RELAY_KEY=" + DUMMY_KEY,
               "--env", "ANTHROPIC_AUTH_TOKEN=", "--env", "ANTHROPIC_API_KEY=", "--env", "ANTHROPIC_OAUTH_TOKEN=",
               "--env", "PI_CODING_AGENT_DIR=/tmp/harbor-pi-agent", *mount_args, image, "sleep", "infinity")
        created = True
        docker("start", name)
        record["isolation"] = validate_container(json.loads(docker("inspect", name).stdout)[0], image, pi_cache)
        docker("cp", str(staging), name + ":/tmp/policy-capture-source")
        nvm = 'if [ -r "$HOME/.nvm/nvm.sh" ]; then . "$HOME/.nvm/nvm.sh"; fi; '
        audit_command = "set -e; " + nvm + "python -I /tmp/policy-capture-source/audit.py"
        audited = docker("exec", name, "bash", "-c", audit_command, timeout=30, check=False)
        (output / "audit.stdout.txt").write_text(audited.stdout)
        (output / "audit.stderr.txt").write_text(audited.stderr)
        if audited.returncode:
            raise RuntimeError("offline installed Pi audit failed: " + audited.stderr[-2048:])
        audit = strict_json(audited.stdout.encode())
        if audit["public_manifest"] != {"task": task, "split": "public-dev"}:
            raise ValueError("image public task manifest mismatch")
        for relative, source in audit.pop("sources").items():
            target = output / "installed-source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
            if file_hash(target) != audit["source_sha256"][relative]:
                raise ValueError("installed source retention hash mismatch")
        write_json(output / "installed-audit.json", audit)
        command = ("set -e; " + nvm + "mkdir /tmp/harbor-pi-agent; "
                   "cp /tmp/policy-capture-source/models.json /tmp/harbor-pi-agent/models.json; "
                   "exec pi --print --mode json --no-session --provider harbor-endpoint "
                   "--model deepseek-flash --thinking off "
                   "--extension /tmp/policy-capture-source/capture.mjs "
                   + shlex.quote("Offline policy capture only. Do not execute tools."))
        capture = docker("exec", name, "bash", "-c", command, timeout=45, check=False)
        (output / "capture.stdout.txt").write_text(capture.stdout)
        (output / "capture.stderr.txt").write_text(capture.stderr)
        if capture.returncode:
            raise RuntimeError("native policy hook exited unsuccessfully: " + str(capture.returncode))
        payload = parse_capture(capture.stdout)
        summaries = []
        for mode in ("initial", "update"):
            command = ("set -e; " + nvm + "node /tmp/policy-capture-source/compaction.mjs "
                       '"$(command -v pi)" ' + mode)
            summary = docker("exec", name, "bash", "-c", command, timeout=30, check=False)
            (output / ("compaction-" + mode + ".stdout.txt")).write_text(summary.stdout)
            (output / ("compaction-" + mode + ".stderr.txt")).write_text(summary.stderr)
            if summary.returncode:
                raise RuntimeError("native compaction capture failed: " + str(summary.returncode))
            summaries.append(parse_compaction_capture(summary.stdout))
        if summaries[0]["system"] != summaries[1]["system"]:
            raise ValueError("native initial/update compaction system differs")
        (output / "compaction-system.json").write_bytes(encoded(summaries[0]["system"]))
        record["compaction_system_sha256"] = file_hash(output / "compaction-system.json")
        for field in ("system", "tools"):
            # Exactly relay.encoded: preserve object order; do not use write_json,
            # whose sorted keys would change the frozen wire-policy hash.
            data = encoded(payload[field])
            (output / (field + ".json")).write_bytes(data)
            record[field + "_sha256"] = hashlib.sha256(data).hexdigest()
        record.update(status="captured", native_hook_before_http=audit["native_hook_before_http"],
                      hook_process_exit_code=capture.returncode, pi_version=audit["version"],
                      requested_max_tokens=payload["requested_max_tokens"], tool_names=EXPECTED_TOOLS,
                      system_json="system.json", tools_json="tools.json", provider_http_requests=0,
                      hash_serialization="runner.model_relay.encoded; ASCII compact JSON, insertion order")
    except Exception as exc:
        record["error"] = str(exc)[:4096]
    finally:
        # Only this exact fresh name is removed, including ambiguous create errors.
        try:
            removed = docker("rm", "-f", name, check=False)
            verify = docker("ps", "-aq", "--filter", "name=^/" + name + "$", check=False)
            record["cleanup"] = {"remove_return_code": removed.returncode,
                                 "absence_check_return_code": verify.returncode,
                                 "removed": verify.returncode == 0 and not verify.stdout.strip()}
            if not record["cleanup"]["removed"] or (created and removed.returncode != 0):
                record["status"] = "capture_failed"
        except Exception as exc:
            record["cleanup"] = {"removed": False, "error": str(exc)[:2048]}
            record["status"] = "capture_failed"
        record["wall_seconds"] = time.monotonic() - started
        if record["status"] == "captured":
            project = (project or Path(__file__).resolve().parents[1]).resolve()
            policy = {"schema_version": 1, "status": "verified", "formal": False,
                      "verification": "offline native policy capture before HTTP", "task": task,
                      "wire_system_sha256": record["system_sha256"], "wire_tools_sha256": record["tools_sha256"],
                      "system": {"path": (output / "system.json").resolve().relative_to(project).as_posix(),
                                 "sha256": file_hash(output / "system.json")},
                      "tools": {"path": (output / "tools.json").resolve().relative_to(project).as_posix(),
                                "sha256": file_hash(output / "tools.json")},
                      "runtime_tools": EXPECTED_TOOLS, "model_calls": 0, "max_turns": None,
                      "pi_version": "0.84.1", "image_id": image, "capture_extension_sha256": record["capture_extension_sha256"]}
            policy["native_compaction"] = {
                "status": "verified", "tools": "absent", "model_calls": 0,
                "wire_system_sha256": record["compaction_system_sha256"],
                "system": {"path": (output / "compaction-system.json").resolve().relative_to(project).as_posix(),
                           "sha256": file_hash(output / "compaction-system.json")},
                "installed_audit": {"path": (output / "installed-audit.json").resolve().relative_to(project).as_posix(),
                                    "sha256": file_hash(output / "installed-audit.json")},
                "source_sha256": {name: audit["source_sha256"][name] for name in COMPACTION_SOURCES},
                "capture_script_sha256": file_hash(staging / "compaction.mjs"),
                "modes": ["initial", "update"],
            }
            write_json(output / "policy.json", policy)
        write_json(output / "result.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--pi-cache", type=Path, help="Prepared native NVM/Pi cache; mounted read-only only")
    parser.add_argument("--prepare-pi-cache", action="store_true", help="Explicitly perform native Pi.setup in a separate temporary installer")
    for task in TASKS:
        parser.add_argument("--" + task + "-image", required=True)
    args = parser.parse_args()
    images = {task: getattr(args, task + "_image") for task in TASKS}
    if not all(IMAGE_ID.fullmatch(image) for image in images.values()):
        parser.error("all images must be immutable sha256 image IDs")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "policy_capture.py").write_bytes(Path(__file__).read_bytes())
    setup = None
    if args.pi_cache:
        args.pi_cache = args.pi_cache.resolve()
        if "," in str(args.pi_cache):
            parser.error("cache path must not contain commas")
        if args.prepare_pi_cache:
            try:
                setup = asyncio.run(prepare_pi_cache(images["heat"], args.pi_cache, args.output / "setup"))
            except Exception as exc:
                write_json(args.output / "result.json", {"schema_version": 1, "formal": False,
                           "status": "capture_failed", "model_calls": 0, "tasks": [],
                           "error": str(exc)[:2048], "setup_evidence": "setup/result.json"})
                raise
        else:
            setup = read_json(args.pi_cache / "provenance.json")
        if (setup.get("status") != "installed" or setup.get("model_calls") != 0
                or setup.get("cache_tree_sha256") != digest(canonical(tree_hashes(args.pi_cache / "nvm")))):
            raise ValueError("native Pi cache provenance mismatch")
    elif args.prepare_pi_cache:
        parser.error("--prepare-pi-cache requires --pi-cache")
    records = [capture_task(task, images[task], args.output / task, pi_cache=args.pi_cache, project=args.project) for task in TASKS]
    result = {"schema_version": 1, "formal": False, "model_calls": 0,
              "status": "captured" if all(row["status"] == "captured" for row in records) else "capture_failed",
              "purpose": "offline native wire-policy precheck; no scientific scoring or resource acceptance",
              "source_sha256": file_hash(Path(__file__)), "tasks": records,
              "native_installation": setup}
    write_json(args.output / "result.json", result)
    print(json.dumps({"status": result["status"], "formal": False, "model_calls": 0}))
    if result["status"] != "captured":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
