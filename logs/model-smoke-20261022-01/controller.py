"""One real built-in Harbor/Pi pilot call; no final-test data or truth access.

This deliberately limited smoke does not certify formal research isolation,
resource limits, a guidance condition, or scientific ability. It stops after
retaining model-produced source for a separate trusted W/J replay.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import stat
import subprocess
import time
import uuid
from pathlib import Path

from harbor.agents.installed.pi import Pi
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths

from .artifact_gate import regular_tree, MAX_FILES, MAX_SOURCE
from .common import canonical, digest, file_hash, read_json, tree_hashes, write_json


PROMPT = """This is a small infrastructure smoke test, not a research study.
Only public pilot heat-task input is available at /input. Do not inspect
environment variables, credentials, other directories, or the network.

Read /input/manifest.json. Use Python to print the shapes of the target_grid.npy
and observations.csv data for each listed case. Then write /workspace/solve.py.
That program must accept --input DIR --output DIR --seed INT, read the input
manifest, and for EVERY listed case write cases/<id>/u0.npy under --output.
Each output must be exactly 256 zeros, little-endian float64, no pickle. Use
numpy and the Python standard library. This intentionally incorrect zero
solution is requested to test the execution and scoring path. Do not try to
solve the inverse problem and do not read private answers. Do not run the
solver after writing it; the trusted host will execute it separately.

After writing solve.py, briefly say what file you created and finish. Use at
most four tool calls. Do not create a reward or score file. Do not start any
background process. No other work is needed.
"""


class RedactingFormatter(logging.Formatter):
    def __init__(self, secret):
        super().__init__("%(asctime)s %(levelname)s %(message)s")
        self.secret = secret

    def format(self, record):
        return super().format(record).replace(self.secret, "[MODEL_CREDENTIAL_REDACTED]")


async def run(args):
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    input_root = args.input_root.resolve(strict=True)
    manifest = read_json(input_root / "manifest.json")
    if manifest.get("split") != "pilot-smoke" or manifest.get("task") != "heat":
        raise ValueError("This runner only accepts heat pilot-smoke public input")
    expected = {"manifest.json"}
    for case in manifest["cases"]:
        expected.update(f"{case['path']}/{name}" for name in ("metadata.json", "observations.csv", "target_grid.npy"))
    actual = {p.relative_to(input_root).as_posix() for p in regular_tree(input_root, MAX_SOURCE, MAX_FILES)}
    if actual != expected:
        raise ValueError("Pilot public input allowlist does not match")
    secret = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    if not secret:
        write_json(output / "result.json", {"attempt_status": "api_credentials_missing", "formal": False})
        return
    endpoint = os.environ.get("ANTHROPIC_BASE_URL", "")
    if endpoint != "https://api.deepseek.com/anthropic":
        raise ValueError("Smoke endpoint differs from the reviewed DeepSeek Anthropic endpoint")

    def redact(value):
        return str(value).replace(secret, "[MODEL_CREDENTIAL_REDACTED]")

    def command(argv, timeout=120):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(redact(f"Command {argv[:2]} failed ({result.returncode}): {result.stderr[-3000:]}"))
        return result.stdout

    events = []
    def event(kind, **payload):
        row = {"time": time.time(), "kind": kind, "payload": payload,
               "previous_hash": events[-1]["event_hash"] if events else "0" * 64}
        row["event_hash"] = digest(canonical(row))
        events.append(row)
        with (output / "host-events.jsonl").open("ab") as stream:
            stream.write(canonical(row) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())

    environment_dir = Path(__file__).resolve().parents[1] / "environment" / "research-smoke"
    logger = logging.getLogger("benchmark.model_smoke." + output.name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = logging.FileHandler(output / "harbor-host.log")
    handler.setFormatter(RedactingFormatter(secret))
    logger.addHandler(handler)
    paths = TrialPaths(output / "harbor-trial")
    paths.mkdir()
    session_id = "bench-model-smoke-" + uuid.uuid4().hex[:12]
    env = None
    result = {
        "formal": False, "study_phase": "pilot-smoke", "task": "heat",
        "network_status": "pilot_network_unrestricted", "resource_status": "resource_limits_diagnostic",
        "model_requested": "deepseek-v4-pro", "model_endpoint": endpoint,
        "model_api_format": "anthropic_messages", "pi_version_requested": "0.84.1",
        "reasoning_effort": "off", "max_turns": 5, "research_timeout_seconds": 300,
        "cpu_request": 2, "memory_request_mb": 2048, "cost_usd": None,
        "source": None, "attempt_status": "starting", "credential_values_recorded": False,
        "public_input_hashes": tree_hashes(input_root), "prompt_sha256": digest(PROMPT.encode()),
        "controller_sha256": file_hash(Path(__file__)), "build_context_hashes": tree_hashes(environment_dir),
        "started_at": time.time(), "harbor_commit": "38b9be0164a910015a0be9a37ba6e8e78c562dfe",
    }
    write_json(output / "prompt.json", {"prompt": PROMPT})
    write_json(output / "result.json", result)
    try:
        if args.build:
            event("image_build_start", context=str(environment_dir), tag=args.image)
            build = await asyncio.to_thread(subprocess.run,
                ["docker", "build", "--progress=plain", "-t", args.image, str(environment_dir)],
                capture_output=True, text=True, timeout=600)
            (output / "image-build.log").write_text(redact(build.stdout + build.stderr))
            if build.returncode:
                raise RuntimeError(f"research image build failed ({build.returncode})")
            event("image_build_complete")
        inspect = json.loads(command(["docker", "image", "inspect", args.image]))[0]
        result["research_image_id"] = inspect["Id"]
        result["research_image_repo_digests"] = inspect.get("RepoDigests", [])
        env = DockerEnvironment(
            environment_dir=environment_dir, environment_name="bench-model-smoke",
            session_id=session_id, trial_paths=paths,
            task_env_config=EnvironmentConfig(docker_image=args.image, cpus=2, memory_mb=2048),
            cpu_enforcement_policy="limit", memory_enforcement_policy="limit", logger=logger,
            auto_mounting=False, enable_environment_dir_upload=False)
        event("research_container_start", session_id=session_id)
        await asyncio.wait_for(env.start(force_build=False), 180)
        await env.upload_dir(input_root, "/input")
        await env.exec(command="chmod -R a-w /input && mkdir -p /workspace", user="root")
        container_ids = command(["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=" + session_id]).split()
        if len(container_ids) != 1:
            raise RuntimeError("Unable to identify exactly one research container")
        cid = container_ids[0]
        info = json.loads(command(["docker", "inspect", cid]))[0]
        result["container"] = {"id": cid, "image_id": info["Image"],
            "mounts": [{k: m.get(k) for k in ("Type", "Source", "Destination", "RW")} for m in info["Mounts"]],
            "memory_limit_bytes": info["HostConfig"]["Memory"],
            "cpu_nano_limit": info["HostConfig"]["NanoCpus"],
            "network_mode": info["HostConfig"]["NetworkMode"]}
        if result["container"]["mounts"]:
            raise RuntimeError("Pilot R unexpectedly has host or volume mounts")
        limits = await env.exec(command="python -c 'import json,pathlib; print(json.dumps({n:(pathlib.Path(\"/sys/fs/cgroup\")/n).read_text().strip() for n in (\"cpu.max\",\"memory.max\",\"memory.swap.max\")}))'")
        result["cgroup_limits"] = json.loads(limits.stdout)
        agent = Pi(
            logs_dir=paths.agent_dir, logger=logger, model_name="anthropic/deepseek-v4-pro",
            version="0.84.1", model_base_url=endpoint, model_api_key_name="BENCH_MODEL_API_KEY",
            model_api_format="anthropic_messages", extra_env={"BENCH_MODEL_API_KEY": secret},
            reasoning_effort="off", max_turns=5, mcp_servers=[])
        event("harbor_pi_setup_start", version="0.84.1")
        await asyncio.wait_for(agent.setup(env), 600)
        version = await env.exec(command=". ~/.nvm/nvm.sh; pi --version; node --version")
        result["installed_versions"] = version.stdout.strip().splitlines()
        event("harbor_pi_setup_complete", versions=result["installed_versions"])
        context = AgentContext()
        event("model_run_start", model=result["model_requested"], timeout=300)
        model_start = time.monotonic()
        try:
            await asyncio.wait_for(agent.run(PROMPT, env, context), 300)
            result["attempt_status"] = "model_run_returned"
        except asyncio.TimeoutError:
            result["attempt_status"] = "research_timeout"
        except Exception as exc:
            result["attempt_status"] = "model_or_harness_failed"
            result["model_error"] = redact(f"{type(exc).__name__}: {exc}")
        result["model_wall_seconds"] = time.monotonic() - model_start
        event("model_run_end", attempt_status=result["attempt_status"], wall_seconds=result["model_wall_seconds"])
        # Pause all R processes before retaining source; no mutable shared mount
        # or background process can change the copied snapshot.
        command(["docker", "pause", cid])
        event("research_container_paused")
        command(["docker", "cp", cid + ":/logs/agent/.", str(paths.agent_dir)])
        for path in paths.agent_dir.rglob("*"):
            if path.is_symlink():
                raise RuntimeError("Unexpected symlink in auxiliary model log transfer")
            if path.is_file():
                original = path.read_bytes()
                cleaned = original.replace(secret.encode(), b"[MODEL_CREDENTIAL_REDACTED]")
                if cleaned != original:
                    path.write_bytes(cleaned)
        agent.populate_context_post_run(context)
        result["model_usage"] = context.model_dump(mode="json")
        # Pi may default unknown custom-endpoint prices to zero. This is not a
        # verified bill, so retain reported usage separately and official cost null.
        result["cost_usd"] = None
        snapshot = output / "snapshot"
        snapshot.mkdir()
        try:
            command(["docker", "cp", cid + ":/workspace/solve.py", str(snapshot / "solve.py")])
            files = regular_tree(snapshot, MAX_SOURCE, MAX_FILES)
            if len(files) != 1 or files[0].name != "solve.py":
                raise ValueError("Expected exactly one ordinary solve.py")
            source_hashes = tree_hashes(snapshot)
            result["source"] = {"path": str(snapshot), "files": source_hashes,
                                "source_hash": digest(canonical(source_hashes))}
            for file in files:
                file.chmod(0o444)
            snapshot.chmod(0o555)
            event("source_snapshot_retained", source_hash=result["source"]["source_hash"])
        except Exception as exc:
            result["source_error"] = redact(f"{type(exc).__name__}: {exc}")
        if result["source"] and context.n_output_tokens:
            result["attempt_status"] = "model_source_retained"
        elif result["attempt_status"] == "model_run_returned":
            result["attempt_status"] = "no_model_source"
        command(["docker", "unpause", cid])
    except Exception as exc:
        result["attempt_status"] = "infrastructure_failed"
        result["error"] = redact(f"{type(exc).__name__}: {exc}")
        event("attempt_error", error=result["error"])
    finally:
        if env is not None:
            try:
                await asyncio.wait_for(env.stop(delete=True), 90)
                result["research_container_removed"] = True
                event("research_container_removed")
            except Exception as exc:
                result["cleanup_error"] = redact(f"{type(exc).__name__}: {exc}")
        result["finished_at"] = time.time()
        result["total_wall_seconds"] = result["finished_at"] - result["started_at"]
        result["auxiliary_log_hashes"] = tree_hashes(paths.agent_dir)
        write_json(output / "result.json", result)
        logger.removeHandler(handler)
        handler.close()
    print(json.dumps({"output": str(output), "attempt_status": result["attempt_status"],
                      "source": result["source"], "formal": False}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--image", default="sciresearch-research-smoke:0.3.0")
    parser.add_argument("--build", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
