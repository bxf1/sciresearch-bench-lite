"""Host-only qualification of raw timer intervals under a verified timing lease.

A frozen timing contract contains resources, image_id and two {path, sha256}
references: resource_evidence and exclusivity_evidence. The latter explicitly
attests the non-Docker host workload window; Docker availability is checked live.
This small resource contract can precede T3 profile calibration. It never unlocks
final-test: the independent full task freeze guard still applies there.
"""
from __future__ import annotations

import copy
import fcntl
import json
import math
from pathlib import Path
import time
import uuid

from .common import canonical, digest, file_hash, read_json
from .phase import IMAGE_ID, RESOURCES
from .performance import EXECUTION_FAILURES
from .worker import docker

LOCK_PATH = Path(__file__).resolve().parents[1] / "build/t3-measurement.lock"


class TimingLease:
    def __init__(self, contract_path, *, execute=None, lock_path=None):
        self.path = Path(contract_path).resolve(strict=True)
        self.execute = execute or docker
        self.lock_path = Path(lock_path) if lock_path is not None else LOCK_PATH
        self.handle = None
        self.references = {}

    def _reference(self, reference):
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            raise ValueError("timing evidence requires an exact path and sha256")
        path = (self.path.parent / reference["path"]).resolve(strict=True)
        if file_hash(path) != reference["sha256"]:
            raise ValueError("timing acceptance evidence hash mismatch")
        self.references[path] = reference["sha256"]
        return read_json(path)

    def _check_host(self):
        now = time.time()
        if not self.window[0] <= now < self.window[1]:
            raise ValueError("outside the independently accepted exclusive host window")
        for path, expected in self.references.items():
            if file_hash(path) != expected:
                raise ValueError("timing evidence changed while the lease was active")
        info = json.loads(self.execute("info", "--format", "{{json .}}").stdout)
        if (int(info.get("NCPU", 0)) < 4 or int(info.get("MemTotal", 0)) < 4 * 1024**3
                or str(info.get("CgroupVersion")) != "2" or info.get("SwapLimit") is False):
            raise ValueError("live Docker resources do not meet the frozen contract")
        if self.execute("ps", "-q").stdout.strip():
            raise ValueError("another container is running in the exclusive timing window")

    def __enter__(self):
        contract = read_json(self.path)
        if (contract.get("status") != "frozen" or contract.get("resources") != RESOURCES
                or not isinstance(contract.get("image_id"), str) or not IMAGE_ID.fullmatch(contract["image_id"])):
            raise ValueError("a frozen, exact resource and image contract is required")
        self.references[self.path] = file_hash(self.path)
        resource = self._reference(contract.get("resource_evidence"))
        exclusive = self._reference(contract.get("exclusivity_evidence"))
        self.machine = resource.get("machine_id")
        if (resource.get("status") != "passed" or resource.get("formal_resources_accepted") is not True
                or resource.get("resources") != RESOURCES or not isinstance(self.machine, str) or not self.machine
                or exclusive.get("status") != "passed" or exclusive.get("machine_exclusive_verified") is not True
                or exclusive.get("machine_id") != self.machine or exclusive.get("other_host_workloads") != []
                or not isinstance(exclusive.get("cache_state"), str) or not exclusive["cache_state"].strip()):
            raise ValueError("resource or exclusive-host acceptance is incomplete")
        self.window = exclusive.get("measurement_window_unix", [])
        if (not isinstance(self.window, list) or len(self.window) != 2
                or any(type(value) not in (float, int) or not math.isfinite(value) for value in self.window)
                or not self.window[0] < self.window[1]):
            raise ValueError("exclusive host evidence requires its accepted time window")
        self.image = contract["image_id"]
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.lock_path.open("a+")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._check_host()
        except Exception:
            self.__exit__(None, None, None)
            raise
        self.started = time.time()
        self.evidence = {"machine_exclusive_verified": True, "machine_id": self.machine,
                         "other_workloads": [], "cache_state": exclusive["cache_state"],
                         "exclusive_lock_id": uuid.uuid4().hex,
                         "timing_contract_sha256": self.references[self.path]}
        return self

    def qualify(self, samples):
        """Return new group records; never rewrite raw worker/timer evidence."""
        if self.handle is None or self.handle.closed:
            raise ValueError("timing lease is not active")
        self._check_host()
        worker_ids = [row["worker"].get("container_id") for row in samples]
        if not all(worker_ids) or len(set(worker_ids)) != len(worker_ids):
            raise ValueError("each timing sample requires a distinct fresh worker container")
        allowed = set(worker_ids)
        allowed.update(row.get("judge_container_id") for row in samples)
        events = self.execute("events", "--since", str(self.started), "--until", str(time.time()),
                              "--filter", "type=container", "--filter", "event=start", "--format", "{{json .}}").stdout
        observed = []
        for line in events.splitlines():
            event = json.loads(line)
            identifier = (event.get("Actor") or {}).get("ID", event.get("id"))
            if identifier not in allowed:
                raise ValueError("unrelated container started during the timing window")
            observed.append(identifier)
        if any(observed.count(identifier) != 1 for identifier in worker_ids):
            raise ValueError("historical or missing worker: every W must start once inside this lease")
        self.evidence.update(window_started_unix=self.started,window_finished_unix=time.time(),
                             observed_container_start_ids=observed,worker_start_ids=worker_ids)
        output = copy.deepcopy(samples)
        expected_timer = file_hash(Path(__file__).with_name("process_timer.py"))
        inputs = {row["worker"].get("input_sha256") for row in output}
        if len(inputs) != 1 or not next(iter(inputs)):
            raise ValueError("batch inputs differ or lack a host hash")
        for row in output:
            worker = row["worker"]
            if (worker.get("image") != self.image or worker.get("machine_id") != self.machine
                    or worker.get("timer_source_sha256") != expected_timer
                    or worker.get("source_hash") != row.get("source_hash")
                    or worker.get("resource_contract_sha256") != digest(canonical(RESOURCES))
                    or worker.get("resource_limits_verified") is not True
                    or worker.get("all_processes_terminated") is not True):
                raise ValueError("worker provenance does not qualify for the accepted timing environment")
            if worker.get("attempt_status") in EXECUTION_FAILURES:
                worker.update(resource_qualified=True, failure_in_qualified_environment=True,
                              formal_timing=worker.get("timing_complete") is True and worker.get("output_initially_empty") is True,
                              timing_contract_sha256=self.references[self.path])
                continue
            if worker.get("timing_complete") is not True or worker.get("output_initially_empty") is not True:
                raise ValueError("successful worker lacks a complete trusted interval")
            worker.update(formal_timing=True, resource_qualified=True,
                          timing_acceptance="host_qualified_under_exclusive_resource_lease",
                          timing_contract_sha256=self.references[self.path])
        return output

    def __exit__(self, *unused):
        if self.handle is not None and not self.handle.closed:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
