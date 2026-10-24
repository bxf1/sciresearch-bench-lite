"""Read-only host prerequisite inspection; never starts/stops services or exposes keys."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from .common import write_json

MODEL_CREDENTIAL_VARIABLES = (
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "AZURE_OPENAI_API_KEY", "XAI_API_KEY",
)
EXPECTED_DEPENDENCIES = {"python": "3.12.12", "numpy": "2.2.6", "scipy": "1.15.3"}


def _run(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        return {"returncode": result.returncode, "stdout": result.stdout}
    except FileNotFoundError:
        return {"returncode": None, "error": "command_not_installed", "stdout": ""}
    except subprocess.TimeoutExpired:
        return {"returncode": None, "error": "command_timeout", "stdout": ""}
    except OSError:
        return {"returncode": None, "error": "command_unavailable", "stdout": ""}


def inspect_prerequisites(image="sciresearch-numeric:0.3.0", *, execute=None, environ=None):
    execute = execute or _run
    environ = os.environ if environ is None else environ
    blockers, checks = [], {}

    def block(code, scope, reason):
        blockers.append({"code": code, "scope": scope, "reason": reason})

    def inspect_json(name, command):
        response = execute(command)
        if response.get("returncode") != 0:
            checks[name] = {"available": False, "returncode": response.get("returncode"),
                            "reason": response.get("error", "command_failed")}
            return None
        try:
            return json.loads(response["stdout"])
        except (json.JSONDecodeError, KeyError):
            checks[name] = {"available": False, "reason": "unexpected_command_response"}
            return None

    versions = inspect_json("docker_version", ["docker", "version", "--format", "{{json .}}"])
    if versions is not None:
        checks["docker_version"] = {
            "available": bool(versions.get("Server")),
            "client_version": (versions.get("Client") or {}).get("Version"),
            "server_version": (versions.get("Server") or {}).get("Version"),
            "server_os": (versions.get("Server") or {}).get("Os"),
            "server_arch": (versions.get("Server") or {}).get("Arch"),
        }
    info = inspect_json("docker_info", ["docker", "info", "--format", "{{json .}}"])
    if info is None:
        block("docker_unavailable", "functional", "Docker daemon is unavailable to this process; no container probe ran.")
    else:
        checks["docker_info"] = {
            "available": True, "cpus": info.get("NCPU"), "memory_bytes": info.get("MemTotal"),
            "operating_system": info.get("OperatingSystem"), "kernel": info.get("KernelVersion"),
            "architecture": info.get("Architecture"), "cgroup_driver": info.get("CgroupDriver"),
            "cgroup_version": info.get("CgroupVersion"), "security_options": info.get("SecurityOptions"),
            "swap_limit_supported": info.get("SwapLimit"),
        }
        if int(info.get("NCPU") or 0) < 4:
            block("research_cpu_shortfall", "formal", "Research contract requires 4 vCPU; this Docker daemon exposes fewer.")
        if int(info.get("MemTotal") or 0) < 4*1024**3:
            block("research_memory_shortfall", "formal", "Research contract requires at least 4 GiB; daemon total memory is smaller.")
        if str(info.get("CgroupVersion")) != "2":
            block("cgroup_v2_missing", "functional", "Current worker reads cgroup v2 resource files; this daemon does not report v2.")
        if info.get("SwapLimit") is False:
            block("swap_limit_unavailable", "formal", "Docker reports swap limits unsupported; no-swap contract cannot be assumed.")

    running = execute(["docker", "ps", "--format", "{{json .}}"])
    if running.get("returncode") == 0:
        try:
            containers = [json.loads(line) for line in running["stdout"].splitlines() if line.strip()]
            checks["running_containers"] = {"available": True, "count": len(containers), "containers": [
                {key: row.get(key) for key in ("ID", "Names", "Image", "Status")} for row in containers]}
            if containers:
                block("shared_daemon_workloads", "formal_performance", "Other containers are running; exclusive T3 timing has not been established. Existing services are left unchanged.")
        except (json.JSONDecodeError, KeyError):
            checks["running_containers"] = {"available": False, "reason": "unexpected_command_response"}
            block("workload_inventory_unknown", "formal_performance", "Could not inventory concurrent Docker workloads.")
    else:
        checks["running_containers"] = {"available": False, "reason": running.get("error", "command_failed")}

    image_info = inspect_json("numeric_image", ["docker", "image", "inspect", image, "--format", "{{json .}}"])
    if image_info is None:
        block("numeric_image_unavailable", "functional", "The requested numeric image is not inspectable locally.")
    else:
        checks["numeric_image"] = {"available": True, "reference": image, "id": image_info.get("Id"),
                                   "repo_digests": image_info.get("RepoDigests", []),
                                   "os": image_info.get("Os"), "architecture": image_info.get("Architecture"),
                                   "expected_dependencies": EXPECTED_DEPENDENCIES,
                                   "runtime_versions_verified": False}
        if image_info.get("Os") != "linux":
            block("numeric_image_not_linux", "functional", "Candidate execution requires a Linux image.")
    checks["host_python"] = {"version": platform.python_version(), "executable_name": Path(sys.executable).name}
    credential_presence = {name: bool(environ.get(name)) for name in MODEL_CREDENTIAL_VARIABLES}
    checks["model_credentials"] = {"environment_presence": credential_presence,
                                    "credential_values_recorded": False,
                                    "oauth_or_external_proxy_inspected": False}
    if not any(credential_presence.values()):
        block("model_endpoint_not_verified", "model_execution", "No supported model-key environment variable is set. OAuth or an external proxy may exist but was not inspected; a real Pi request remains required.")
    gh = execute(["gh", "auth", "status"])
    checks["github_auth"] = {"authenticated": gh.get("returncode") == 0,
                              "reason": "authenticated" if gh.get("returncode") == 0 else gh.get("error", "not_authenticated_or_unavailable")}
    if gh.get("returncode") != 0:
        block("github_auth_unverified", "publication", "GitHub CLI authentication is not available; publication has not been validated.")
    for name in ("pi",):
        response = execute([name, "--version"])
        version = response.get("stdout", "").strip()
        safe_version = version if len(version) <= 80 and all(c.isalnum() or c in ".-_+ " for c in version) else None
        checks[name] = {"available": response.get("returncode") == 0, "version": safe_version}
    return {
        "schema_version": "0.3", "inspection_mode": "read_only", "formal": False,
        "formal_ready": False, "formal_status": "not_accepted_by_prerequisite_inspection",
        "host": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "checks": checks, "blockers": blockers,
        "functional_prerequisites_present": not any(item["scope"] == "functional" for item in blockers),
        "unverified_acceptance": ["numeric image runtime versions", "R/W/J isolation attack probes",
                                   "live model request", "exact model and harness freeze", "exclusive timing and calibrated profile"],
        "service_mutations": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="sciresearch-numeric:0.3.0")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect_prerequisites(args.image)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output), "formal": False,
                      "functional_prerequisites_present": result["functional_prerequisites_present"],
                      "blockers": result["blockers"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
