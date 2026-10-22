"""Small public Harbor environment hook for the nonformal research pilot.

Native Docker start/exec/stop and native Pi are unchanged. The hook prevents
Harbor's phase unwind from reopening setup networking and keeps R-authored logs
and attachments out of Harbor's automatic host-side trajectory parser.
"""
from __future__ import annotations

from pathlib import Path
import time

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import NetworkMode, NetworkPolicy

from .common import write_json


class ResearchDockerEnvironment(DockerEnvironment):
    def __init__(self, *args, pilot_audit_root: str, **kwargs):
        policy = kwargs.get("network_policy")
        if policy is None or policy.network_mode not in (NetworkMode.PUBLIC, NetworkMode.NO_NETWORK):
            raise ValueError("pilot environment must start PUBLIC for setup or NO_NETWORK for verification")
        self.pilot_is_research = policy.network_mode == NetworkMode.PUBLIC
        self.pilot_audit_root = Path(pilot_audit_root)
        self.pilot_events = []
        self.pilot_sealed_policy = None
        if kwargs.get("auto_mounting") is not False or kwargs.get("stream", False):
            raise ValueError("pilot requires auto_mounting=False and stream=False")
        if not self.pilot_is_research:
            # Harbor deliberately strips agent overlays from the separate
            # verifier. Supply its own host-owned diagnostic limits here.
            overlay = self.pilot_audit_root / "verifier-security-compose.json"
            write_json(overlay, {"services": {
                "main": {"cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                         "pids_limit": 128, "mem_limit": "512m", "memswap_limit": "512m"},
                "harbor-docker-egress-control-sidecar": {"cpus": .25, "mem_limit": "128m", "memswap_limit": "128m"}}})
            kwargs["extra_docker_compose"] = [overlay]
        super().__init__(*args, **kwargs)
        self._pilot_record("created", role="research" if self.pilot_is_research else "verifier")

    def _pilot_record(self, kind, **fields):
        self.pilot_events.append({"time": time.time(), "kind": kind, **fields})
        write_json(self.pilot_audit_root / (self.session_id + ".json"),
                   {"session_id": self.session_id, "formal": False, "events": self.pilot_events})

    async def seal_research_network(self, policy: NetworkPolicy):
        if not self.pilot_is_research or policy.network_mode != NetworkMode.ALLOWLIST or not policy.allowed_hosts:
            raise ValueError("research seal requires a nonempty model-relay allowlist")
        if self.pilot_sealed_policy is not None and policy != self.pilot_sealed_policy:
            raise ValueError("research network seal is immutable")
        await super().set_network_policy(policy)
        self.pilot_sealed_policy = policy.model_copy(deep=True)
        self._pilot_record("research_network_sealed", policy=policy.model_dump(mode="json"))

    async def set_network_policy(self, policy: NetworkPolicy):
        if self.pilot_sealed_policy is not None and policy != self.pilot_sealed_policy:
            if policy.network_mode == NetworkMode.PUBLIC:
                self._pilot_record("setup_network_restore_blocked",
                                   requested=policy.model_dump(mode="json"),
                                   retained=self.pilot_sealed_policy.model_dump(mode="json"))
                return
            raise ValueError("cannot replace a sealed research policy")
        await super().set_network_policy(policy)

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        if self.pilot_is_research and "pi --print --mode json " in command:
            # Native Pi's tee still writes its R-local session/output. Its
            # stdout is otherwise buffered without a bound by DockerEnvironment
            # and later copied into native host logs. Only the process status
            # crosses here; bounded text retention happens after R is stopped.
            command = "(" + command + ") >/dev/null 2>&1"
            self._pilot_record("native_pi_stdout_suppressed")
        return await super().exec(command, cwd=cwd, env=env, timeout_sec=timeout_sec, user=user)

    async def download_dir_filtered(self, *, source_dir, target_dir, include=None, exclude=None, protect=None):
        if self.pilot_is_research:
            if source_dir != "/logs/agent" or protect:
                raise ValueError("automatic research file download is forbidden")
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            self._pilot_record("native_agent_log_download_suppressed")
            return
        await super().download_dir_filtered(source_dir=source_dir, target_dir=target_dir,
                                            include=include, exclude=exclude, protect=protect)

    async def download_dir(self, source_dir, target_dir):
        if self.pilot_is_research:
            raise ValueError("unbounded research directory download is forbidden")
        await super().download_dir(source_dir, target_dir)

    async def download_file(self, source_path, target_path):
        if self.pilot_is_research:
            raise ValueError("automatic research file download is forbidden")
        await super().download_file(source_path, target_path)

    async def service_is_dir(self, path, *, service=None, user=None):
        if self.pilot_is_research and self.is_main_service(service) and path == "/logs/artifacts":
            return True  # The convention entry is explicitly excluded in full.
        return await super().service_is_dir(path, service=service, user=user)

    async def service_download_dir_with_exclusions(self, *, source_dir, target_dir, exclude, service=None):
        if self.pilot_is_research:
            if not (self.is_main_service(service) and source_dir == "/logs/artifacts"
                    and set(exclude) >= {"*", "**/*"}):
                raise ValueError("automatic research artifacts must be entirely excluded")
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            self._pilot_record("native_artifacts_excluded")
            return
        await super().service_download_dir_with_exclusions(source_dir=source_dir, target_dir=target_dir,
                                                           exclude=exclude, service=service)

    async def upload_dir(self, source_dir, target_dir):
        if self.pilot_is_research and target_dir == "/logs/agent":
            if any(path.is_file() or path.is_symlink() for path in Path(source_dir).rglob("*")):
                raise ValueError("native agent log directory must stay empty")
            self._pilot_record("empty_native_agent_log_upload_suppressed")
            return
        await super().upload_dir(source_dir, target_dir)
