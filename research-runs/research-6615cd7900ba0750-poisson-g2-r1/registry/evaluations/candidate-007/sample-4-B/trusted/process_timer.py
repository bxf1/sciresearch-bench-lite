"""Linux namespace-init timer; no capabilities, provider access, or candidate imports.

The container init runs as 65533, while the one trusted launcher and subsequent
submission run as 65534. Only that launcher exists before the single handshake.
The init owns the timing record and waits for the exec process and all adopted
descendants. The host still enforces deadlines and kills the entire container.
This establishes the timing interval, not formal hardware/exclusivity acceptance.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import select
import signal
import socket
import struct
import sys
import time

TIMER_UID = 65533
CANDIDATE_UID = 65534
CONTROL = Path("/tmp/.sciresearch-timer")
PRIVATE = Path("/tmp/.sciresearch-timer-private")
RECORD = PRIVATE / "result.json"
COMPLETE = PRIVATE / "complete"
RECORD_BYTES = 8192
SOCKET = CONTROL / "launch.sock"
SCOPE = "python_spawn_to_all_descendants_exit"


def validate_record(record):
    """Host-side structural validation; provenance is the protected W channel."""
    start, end = record.get("started_monotonic_ns"), record.get("finished_monotonic_ns")
    if (type(start) is not int or type(end) is not int or not 0 < start < end
            or record.get("schema_version") != 1 or record.get("timing_scope") != SCOPE
            or record.get("clock") != "CLOCK_MONOTONIC"
            or record.get("timer_uid") != TIMER_UID or record.get("candidate_uid") != CANDIDATE_UID
            or record.get("all_candidate_processes_terminated") is not True
            or record.get("formal_timing") is not False
            or not isinstance(record.get("machine_id"), str) or not record["machine_id"]):
        raise ValueError("invalid trusted process timing evidence")
    seconds = record.get("execution_wall_seconds")
    if (type(seconds) not in (int, float) or not math.isfinite(seconds)
            or not math.isclose(seconds, (end - start) / 1e9, rel_tol=1e-9, abs_tol=1e-12)):
        raise ValueError("trusted timer duration differs from its monotonic interval")
    return record


def receive_exact(connection, count):
    data = b""
    while len(data) < count:
        block = connection.recv(count - len(data))
        if not block:
            raise RuntimeError("launcher closed before its timing record")
        data += block
    return data


def wait_descendants(main_pidfd):
    """PIDFD exit follows reparenting; every remaining subtree is then ours.

    A setsid/double-fork or candidate subreaper cannot escape the PID namespace:
    its oldest surviving root is adopted by namespace init. ECHILD is checked
    only *after* the original exec process has exited, never by a /proc snapshot.
    """
    poller = select.poll()
    poller.register(main_pidfd, select.POLLIN)
    while not poller.poll():
        pass
    adopted = 0
    while True:
        try:
            os.waitpid(-1, 0)
            adopted += 1
        except InterruptedError:
            continue
        except ChildProcessError:
            return adopted


def candidate_pids():
    found = []
    for folder in Path("/proc").iterdir():
        if not folder.name.isdigit():
            continue
        try:
            status = (folder / "status").read_text()
        except FileNotFoundError:
            continue
        for line in status.splitlines():
            if line.startswith("Uid:") and int(line.split()[1]) == CANDIDATE_UID:
                found.append(int(folder.name))
    return found


def reserve_record():
    """Allocate actual tmpfs pages before the candidate can consume its quota."""
    record_fd = os.open(RECORD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    done_fd = os.open(COMPLETE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    write_all(record_fd, b" " * RECORD_BYTES)
    write_all(done_fd, b"0")
    return record_fd, done_fd


def write_all(fd, payload):
    while payload:
        count = os.write(fd, payload)
        if count <= 0:
            raise OSError("trusted timing record write did not progress")
        payload = payload[count:]


def commit_record(record, record_fd, done_fd):
    payload = json.dumps(record, sort_keys=True, allow_nan=False).encode()
    if len(payload) > RECORD_BYTES:
        raise RuntimeError("trusted timer record exceeds its preallocated capacity")
    os.lseek(record_fd, 0, os.SEEK_SET)
    write_all(record_fd, payload.ljust(RECORD_BYTES, b" "))
    # No creation/rename/truncation or new tmpfs pages after candidate execution.
    os.lseek(done_fd, 0, os.SEEK_SET)
    write_all(done_fd, b"1")
    os.close(record_fd)
    os.close(done_fd)


def supervise():
    if sys.platform != "linux" or os.getpid() != 1 or os.getuid() != TIMER_UID or os.getgid() != TIMER_UID:
        raise RuntimeError("timer must be Linux namespace PID 1 with its separate nonroot UID")
    # Defense in depth: even another process with our UID cannot read our memory.
    if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE=0
        raise OSError(ctypes.get_errno(), "cannot disable timer dumpability")
    for folder, mode in ((CONTROL, 0o711), (PRIVATE, 0o700)):
        folder.mkdir(mode=mode)
        folder.chmod(mode)
    record_fd, done_fd = reserve_record()
    if any(Path("/output").iterdir()):
        raise RuntimeError("output must initially be empty")
    if candidate_pids():
        raise RuntimeError("candidate UID already active before trusted launch")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(SOCKET))
        SOCKET.chmod(0o666)
        listener.listen(1)
        connection, _ = listener.accept()
        # Close before allowing exec; no second candidate-controlled connection.
        listener.close()
        SOCKET.unlink()
        with connection:
            connection.settimeout(10)
            pid, uid, gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if pid <= 1 or (uid, gid) != (CANDIDATE_UID, CANDIDATE_UID):
                raise RuntimeError("unexpected launcher peer credentials")
            if candidate_pids() != [pid]:
                raise RuntimeError("launcher is not the only candidate-UID process")
            main_pidfd = os.pidfd_open(pid)
            try:
                earliest = time.monotonic_ns()
                connection.sendall(b"GO")
                started = struct.unpack("!Q", receive_exact(connection, 8))[0]
                if not earliest <= started <= time.monotonic_ns():
                    raise RuntimeError("invalid trusted launcher start time")
                # Do not accept an end time or any candidate-supplied metadata.
                connection.close()
                adopted = wait_descendants(main_pidfd)
                finished = time.monotonic_ns()
            finally:
                os.close(main_pidfd)
    record = {"schema_version": 1, "timing_scope": SCOPE, "clock": "CLOCK_MONOTONIC",
              "started_monotonic_ns": started, "finished_monotonic_ns": finished,
              "execution_wall_seconds": (finished - started) / 1e9,
              "timer_uid": TIMER_UID, "candidate_uid": CANDIDATE_UID, "launcher_pid": pid,
              "all_candidate_processes_terminated": True, "adopted_processes_reaped": adopted,
              "output_initially_empty": True,
              "machine_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "formal_timing": False}
    commit_record(record, record_fd, done_fd)
    # Docker captures PID1's stream separately from docker-exec candidate logs.
    # Reading this channel needs no spare PID inside an exhausted candidate cgroup.
    print(json.dumps(record, sort_keys=True, allow_nan=False), flush=True)
    # Keep the existing tmpfs output alive for host extraction. Never execute R code.
    while True:
        signal.pause()


def launch(method=None):
    if os.getuid() != CANDIDATE_UID or os.getgid() != CANDIDATE_UID:
        raise RuntimeError("launcher requires the candidate nonroot UID")
    command = [sys.executable, "-B", "/submission/solve.py", "--input", "/input", "--output", "/output", "--seed", "0"]
    if method is not None:
        command.extend(("--method", method))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.set_inheritable(False)
        connection.settimeout(10)
        connection.connect(str(SOCKET))
        if receive_exact(connection, 2) != b"GO":
            raise RuntimeError("timer did not authorize trusted launch")
        connection.sendall(struct.pack("!Q", time.monotonic_ns()))
        # Fixed executable, argv and read-only launcher; no candidate code ran yet.
        # CLOEXEC prevents the submission from retaining the trusted connection.
        os.execv(sys.executable, command)


def read_record():
    if os.getuid() != TIMER_UID:
        raise RuntimeError("only the timer UID may retrieve timing evidence")
    while COMPLETE.read_bytes() != b"1":
        time.sleep(.01)
    print(RECORD.read_text(), end="", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("supervise", "launch", "read"))
    parser.add_argument("--method")
    args = parser.parse_args()
    {"supervise": supervise, "launch": lambda: launch(args.method), "read": read_record}[args.action]()


if __name__ == "__main__":
    main()
