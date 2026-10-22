"""Actual Harbor research allowlist probe, isolated from existing services.

No model call or credential forwarding occurs. Only the unique probe Compose
project is started/stopped. This is functional evidence, not formal acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig, NetworkMode, NetworkPolicy
from harbor.models.trial.paths import TrialPaths
from harbor.utils.container_cache import docker_build_context_hash

from .common import file_hash, tree_hashes, write_json


REACHABILITY_PROGRAM = r'''
import json, ssl, time, urllib.request, urllib.error
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
    urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
url = URL_PLACEHOLDER
start = time.monotonic()
try:
    response = opener.open(url, timeout=3)
    result = {"http_response": True, "status": response.status}
    response.close()
except urllib.error.HTTPError as exc:
    result = {"http_response": True, "status": exc.code}
except Exception as exc:
    result = {"http_response": False, "error": type(exc).__name__ + ": " + str(exc)}
result.update(url=url, wall_seconds=time.monotonic()-start, timeout_seconds=3,
              tls_certificate_verification=False, redirects_followed=False, proxy_environment_used=False)
print(json.dumps(result))
'''

SECURITY_PROGRAM = r'''
import gzip,json,os,pathlib
status={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in pathlib.Path('/proc/self/status').read_text().splitlines() if ':' in line}
cap=int(status['CapEff'],16)
p=pathlib.Path('/sys/fs/cgroup')
kernel_config=pathlib.Path('/proc/config.gz')
kernel=None
if kernel_config.exists():
    kernel=[line for line in gzip.decompress(kernel_config.read_bytes()).decode().splitlines() if 'CONFIG_NFT_FIB_INET=' in line]
print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'cap_eff':status['CapEff'],
 'cap_net_admin':bool(cap & (1<<12)), 'cap_net_raw':bool(cap & (1<<13)),
 'docker_socket_present':any(pathlib.Path(x).exists() for x in ['/var/run/docker.sock','/run/docker.sock']),
 'docker_host_env_present':bool(os.environ.get('DOCKER_HOST')),
 'host_mount_paths_present':[x for x in ['/host','/host_mnt','/run/host'] if pathlib.Path(x).exists()],
 'kernel_nft_fib_inet_config':kernel,
 'network_namespace':os.readlink('/proc/self/ns/net'),'pid_namespace':os.readlink('/proc/self/ns/pid'),
 'cgroup':{name:(p/name).read_text().strip() for name in ['cpu.max','memory.max','memory.swap.max']}}))
'''


def docker(*args, check=True, timeout=30):
    process = subprocess.run(["docker", *map(str, args)], capture_output=True, text=True, timeout=timeout)
    if check and process.returncode:
        raise RuntimeError(process.stderr[-3000:] or process.stdout[-3000:])
    return process


async def probe(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "controller.py").write_bytes(Path(__file__).read_bytes())
    logger = logging.getLogger("benchmark.network_probe." + output.name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = logging.FileHandler(output / "harbor-host.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    paths = TrialPaths(output / "harbor-trial")
    paths.mkdir()
    session_id = "bench-network-probe-" + uuid.uuid4().hex[:12]
    result = {"formal": False, "kind": "research_network_functional_probe", "model_calls": 0,
              "credentials_forwarded": False, "host_network_configuration_modified": False,
              "parent_attempt": args.parent_attempt,
              "session_id": session_id, "started_at": time.time(), "controller_sha256": file_hash(Path(__file__)),
              "requested_research_resources": {"cpus": 1, "memory_mb": 1024}, "status": "starting",
              "requested_allowlist": ["api.deepseek.com"], "before": [], "after": []}
    env = None
    allowlist = NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=["api.deepseek.com"])
    try:
        image = json.loads(docker("image", "inspect", args.image).stdout)[0]
        result["research_image"] = {"reference": args.image, "id": image["Id"], "repo_digests": image.get("RepoDigests", [])}
        info = json.loads(docker("info", "--format", "{{json .}}").stdout)
        result["daemon_kernel"] = {key: info.get(key) for key in ("KernelVersion", "OperatingSystem", "Architecture", "CgroupVersion")}
        if args.prebuild_sidecar:
            context = DockerEnvironment._EGRESS_CONTROL_SIDECAR_CONTEXT_PATH
            platform = docker("version", "--format", "{{.Server.Os}}/{{.Server.Arch}}").stdout.strip()
            context_hash = docker_build_context_hash(context=context, dockerfile_path=context / "Dockerfile",
                                                     build_args={}, platform=platform)
            tag = DockerEnvironment._EGRESS_CONTROL_SIDECAR_DOCKER_NAME + "--" + context_hash
            result["sidecar_prebuild"] = {"context": str(context), "context_hash": context_hash,
                "context_files_sha256": tree_hashes(context), "platform": platform, "tag": tag,
                "builder": "legacy docker build; unchanged Harbor Dockerfile/context"}
            build = await asyncio.to_thread(docker, "build", "--platform", platform, "--file", context / "Dockerfile",
                                           "--tag", tag, context, check=False, timeout=360)
            (output / "sidecar-build.log").write_text(build.stdout + build.stderr)
            result["sidecar_prebuild"]["returncode"] = build.returncode
            if build.returncode:
                raise RuntimeError("Unchanged Harbor sidecar legacy build failed; see sidecar-build.log")
            built = json.loads(docker("image", "inspect", tag).stdout)[0]
            result["sidecar_prebuild"]["image_id"] = built["Id"]
        env = DockerEnvironment(
            environment_dir=Path(__file__).resolve().parents[1] / "environment" / "research-smoke",
            environment_name="bench-network-probe", session_id=session_id, trial_paths=paths,
            task_env_config=EnvironmentConfig(docker_image=args.image, cpus=1, memory_mb=1024),
            network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC), phase_network_policies=[allowlist],
            cpu_enforcement_policy="limit", memory_enforcement_policy="limit", auto_mounting=False,
            enable_environment_dir_upload=False, logger=logger)
        result["harbor_egress_control_enabled"] = bool(env._enable_egress_control)
        write_json(output / "result.json", result)
        await asyncio.wait_for(env.start(force_build=False), 360)
        ids = docker("ps", "-q", "--filter", "label=com.docker.compose.project=" + session_id).stdout.split()
        containers = json.loads(docker("inspect", *ids).stdout)
        result["containers"] = []
        for container in containers:
            hc = container["HostConfig"]
            result["containers"].append({"id": container["Id"], "image_id": container["Image"],
                "service": container["Config"].get("Labels", {}).get("com.docker.compose.service"),
                "mounts": [{key: mount.get(key) for key in ("Type", "Source", "Destination", "RW")} for mount in container["Mounts"]],
                "network_mode": hc["NetworkMode"], "pid_mode": hc["PidMode"], "ipc_mode": hc["IpcMode"],
                "privileged": hc["Privileged"], "cap_add": hc["CapAdd"], "cap_drop": hc["CapDrop"],
                "memory_limit_bytes": hc["Memory"], "cpu_nano_limit": hc["NanoCpus"]})
        security = await env.exec(command="python -c " + shlex.quote(SECURITY_PROGRAM), timeout_sec=10)
        if security.return_code:
            raise RuntimeError("Could not read actual R security state: " + (security.stderr or ""))
        result["research_security"] = json.loads(security.stdout)
        urls = ("https://api.deepseek.com", "https://example.com", "https://1.1.1.1")
        async def request(url):
            program = REACHABILITY_PROGRAM.replace("URL_PLACEHOLDER", repr(url))
            try:
                response = await env.exec(command="python -c " + shlex.quote(program), timeout_sec=8)
                if response.return_code:
                    return {"url": url, "http_response": False, "probe_error": response.stderr or response.stdout}
                return json.loads(response.stdout)
            except Exception as exc:
                return {"url": url, "http_response": False, "probe_error": f"{type(exc).__name__}: {exc}"}
        for url in urls:
            result["before"].append(await request(url))
        await asyncio.wait_for(env.set_network_policy(allowlist), 30)
        result["policy_apply_completed"] = True
        for command, filename in (("network-policy show", "sidecar-policy.txt"),
                                  ("network-policy rules", "sidecar-nft-rules.txt")):
            response = await env.service_exec(command, service="harbor-docker-egress-control-sidecar", timeout_sec=10)
            (output / filename).write_text((response.stdout or "") + (response.stderr or ""))
            if response.return_code:
                raise RuntimeError("Could not verify sidecar policy/rules")
        rules = (output / "sidecar-nft-rules.txt").read_text()
        result["nft_rules_installed"] = "gost_egress" in rules and "redirect to :12345" in rules
        for url in urls:
            result["after"].append(await request(url))
        allowed = result["after"][0].get("http_response") is True
        denied = all(row.get("http_response") is False and not row.get("probe_error") for row in result["after"][1:])
        reachability_control = all(row.get("http_response") is True for row in result["before"])
        r = result["research_security"]
        main = [row for row in result["containers"] if row["service"] != "harbor-docker-egress-control-sidecar"]
        boundary = (len(main) == 1 and not main[0]["mounts"] and not main[0]["privileged"]
                    and main[0]["network_mode"] != "host" and main[0]["pid_mode"] != "host"
                    and not r["cap_net_admin"] and not r["docker_socket_present"]
                    and not r["docker_host_env_present"] and not r["host_mount_paths_present"])
        result.update(model_endpoint_reachable=allowed, forbidden_http_requests_rejected=denied,
                      public_phase_control_reachable=reachability_control, research_host_boundary_checks_pass=boundary,
                      cap_net_raw_present=r["cap_net_raw"],
                      scope_note="HTTP/TLS URL probes and recorded nft rules; not a complete adversarial network audit")
        result["status"] = "functional_probe_passed" if allowed and denied and reachability_control and boundary and result["nft_rules_installed"] else "functional_probe_incomplete_or_failed"
        if r["cap_net_raw"]:
            result["unresolved_risk"] = "R retains NET_RAW; URL probes do not rule out raw-packet bypass. Formal isolation not accepted."
    except Exception as exc:
        result["status"] = "probe_failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if env is not None:
            try:
                await asyncio.wait_for(env.stop(delete=True), 90)
                result["cleanup_api_returned"] = True
            except Exception as exc:
                result["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        result["remaining_own_containers"] = docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + session_id, check=False).stdout.split()
        result["remaining_own_networks"] = docker("network", "ls", "-q", "--filter", "label=com.docker.compose.project=" + session_id, check=False).stdout.split()
        result["remaining_own_volumes"] = docker("volume", "ls", "-q", "--filter", "label=com.docker.compose.project=" + session_id, check=False).stdout.split()
        result["own_resources_removed"] = not any(result[name] for name in ("remaining_own_containers", "remaining_own_networks", "remaining_own_volumes"))
        result["finished_at"] = time.time()
        result["total_wall_seconds"] = result["finished_at"] - result["started_at"]
        write_json(output / "result.json", result)
        logger.removeHandler(handler)
        handler.close()
    print(json.dumps({key: result.get(key) for key in ("status", "harbor_egress_control_enabled", "model_endpoint_reachable",
        "forbidden_http_requests_rejected", "research_host_boundary_checks_pass", "unresolved_risk", "error", "own_resources_removed")}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="sciresearch-research-smoke:0.3.0")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prebuild-sidecar", action="store_true")
    parser.add_argument("--parent-attempt", default=None)
    asyncio.run(probe(parser.parse_args()))


if __name__ == "__main__":
    main()
