"""Host-polled file bridge: no HTTP listener, R bind mount, or Docker socket in R."""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess
import threading
import time

from public.bridge_io import MAX_PENDING, REQUEST_ID, validate_request
from .artifact_gate import MAX_FILES, MAX_SOURCE, extract_tar, regular_tree
from .common import canonical, digest, read_json, write_json
from .phase import validate_manifest
from .registry import Registry, remaining_seconds
from .public_evaluation import run_public_evaluation


class BridgeTransportError(RuntimeError):
    pass


class DockerFileTransport:
    """Every Docker argument is fixed or comes from trusted host configuration."""
    def __init__(self, container_id):
        if not isinstance(container_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container_id) is None:
            raise ValueError("invalid trusted container ID/name")
        self.container_id = container_id

    def command(self, helper, *args):
        if helper not in ("bridge_io.py", "export_source.py"):
            raise ValueError("unknown trusted helper")
        return ["docker", "exec", "--user", "0", "-i", self.container_id, "python", "-I", "/opt/bench/" + helper, *args]

    def poll(self):
        result = subprocess.run(self.command("bridge_io.py", "poll"), input=b"", capture_output=True, timeout=15)
        if result.returncode or len(result.stdout) > 512 * 1024:
            raise BridgeTransportError("R request polling failed: " + result.stderr[-1024:].decode(errors="replace"))
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or len(rows) > MAX_PENDING:
            raise BridgeTransportError("invalid trusted poll response")
        return rows

    def respond(self, request_id, response):
        payload = canonical({"request_id": request_id, "response": response})
        if len(payload) > 65536 + 4096:
            raise BridgeTransportError("response envelope exceeds bound")
        result = subprocess.run(self.command("bridge_io.py", "respond"), input=payload, capture_output=True, timeout=15)
        if result.returncode:
            raise BridgeTransportError("R response publication failed: " + result.stderr[-1024:].decode(errors="replace"))

    def export_source(self, relative_source, destination, timeout):
        payload = canonical({"source": relative_source})
        if len(payload) > 4096:
            raise BridgeTransportError("source export request exceeds bound")
        process = subprocess.Popen(self.command("export_source.py"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        expired = threading.Event()
        def kill_on_deadline():
            expired.set()
            try:
                process.kill()
            except ProcessLookupError:
                pass
        timer = threading.Timer(max(.01, timeout), kill_on_deadline)
        timer.daemon = True
        timer.start()
        try:
            process.stdin.write(payload)
            process.stdin.close()
            extract_tar(process.stdout, destination, max_bytes=MAX_SOURCE, max_files=MAX_FILES)
            code = process.wait(timeout=max(.01, timeout))
            stderr = process.stderr.read(4097)
            if expired.is_set() or code != 0:
                raise BridgeTransportError("R source export failed: " + stderr[:1024].decode(errors="replace"))
            regular_tree(destination, MAX_SOURCE, MAX_FILES)
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()


class FileBridge:
    def __init__(self, container_id, registry, input_root, image, run_root=None, *, transport=None, execute=None, check=None):
        self.registry = registry if isinstance(registry, Registry) else Registry(registry)
        self.state = read_json(self.registry.root / "state.json")
        self.task = self.state["task"]
        self.input_root = Path(input_root)
        manifest = validate_manifest(self.task, self.input_root)
        if manifest["split"] not in ("public-dev", "pilot-smoke"):
            raise ValueError("file bridge may expose only dev or explicit pilot inputs")
        self.image = image
        self.workspace = Path(self.state["workspace"])
        self.root = Path(run_root) if run_root else self.registry.root / "file-bridge"
        if self.root.resolve().is_relative_to(self.workspace.resolve()):
            raise ValueError("trusted bridge records must be outside the imported-source workspace")
        (self.root / "requests").mkdir(parents=True, exist_ok=True)
        self.transport = transport or DockerFileTransport(container_id)
        self.execute = execute
        self.check = check

    def _evaluate(self, request):
        imported = "imported-" + request["request_id"]
        destination = self.workspace / imported
        evidence = {"original_r_source": request["source"], "imported_source": imported}

        def prepare(relative_source, candidate_id, remaining):
            evidence["export_started_at"] = time.time()
            evidence["candidate_id"] = candidate_id
            try:
                self.transport.export_source(request["source"], destination, min(120, remaining))
            except Exception as exc:
                evidence["export_error"] = type(exc).__name__ + ": " + str(exc)[:1024]
                raise
            finally:
                evidence["export_finished_at"] = time.time()
            return imported

        def execute(snapshot, candidate_id, remaining):
            run = self.registry.root / "evaluations" / candidate_id
            # A single evaluation retains its worker/checker protection even
            # when the research session has no aggregate wall-clock limit.
            return run_public_evaluation(self.task, snapshot, self.input_root, run, self.image, min(1800, remaining),
                                         execute=self.execute, check=self.check)

        # Registry accepts and persists the slot before reading any R source.
        # A failed/slow export therefore cannot evade the evaluation budget.
        row = self.registry.evaluate(imported, execute, prepare_source=prepare)
        feedback = dict(row["result"])
        if "export_error" in evidence:
            feedback["source_export_error"] = evidence["export_error"]
        response = {"candidate_id": row["id"], "source_hash": row["source_hash"], "feedback": feedback}
        return response, evidence

    def poll_once(self):
        with (self.root / ".poll.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._poll_once()

    def _deliver(self, identifier, response):
        delivery = self.root / "requests" / (identifier + ".delivery.json")
        try:
            self.transport.respond(identifier, response)
            write_json(delivery, {"request_id": identifier, "status": "delivered"})
        except Exception as exc:
            write_json(delivery, {"request_id": identifier, "status": "failed", "error": type(exc).__name__ + ": " + str(exc)[:1024]})

    @staticmethod
    def _save_record(path, record):
        record.pop("record_sha256", None)
        record["record_sha256"] = digest(canonical(record))
        write_json(path, record)

    def _poll_once(self):
        processed = 0
        for item in self.transport.poll():
            identifier = item.get("request_id") if isinstance(item, dict) else None
            if not isinstance(identifier, str) or REQUEST_ID.fullmatch(identifier) is None:
                raise BridgeTransportError("poll helper returned an unsafe request ID")
            record_path = self.root / "requests" / (identifier + ".json")
            if record_path.exists():
                record = read_json(record_path)
                if record.get("status") == "processing":
                    # A previous host process stopped between acceptance and its
                    # final record. Never repeat a potentially executed request.
                    record.update(status="interrupted", completed_at=time.time())
                    self._save_record(record_path, record)
                delivery = record_path.with_suffix(".delivery.json")
                if not delivery.exists() or read_json(delivery).get("status") != "delivered":
                    self._deliver(identifier, record["response"])
                continue  # Durable host idempotency does not trust R's response files.
            received = time.time()
            evidence = {}
            self._save_record(record_path, {"request_id": identifier, "received_at": received,
                                           "status": "processing", "request": item.get("request"),
                                           "response": {"request_id": identifier, "ok": False,
                                                        "error": "host interrupted while processing; this request ID will not be executed again"}})
            try:
                if "error" in item:
                    raise ValueError(item["error"])
                request = validate_request(item["request"], identifier)
                if request["operation"] == "evaluate":
                    value, evidence = self._evaluate(request)
                else:
                    self.registry.finalize(request["candidate_id"])
                    value = {"finalized": request["candidate_id"]}
                response = {"request_id": identifier, "ok": True, **value}
            except Exception as exc:
                response = {"request_id": identifier, "ok": False, "error": type(exc).__name__ + ": " + str(exc)[:1024]}
            record = {"request_id": identifier, "received_at": received, "completed_at": time.time(),
                      "status": "completed", "request": item.get("request"), "response": response, **evidence}
            # Persist the trusted decision before publishing any feedback to R.
            self._save_record(record_path, record)
            self._deliver(identifier, response)
            processed += 1
        return processed

    def serve(self, stop_event=None, interval=.2):
        while stop_event is None or not stop_event.is_set():
            state = read_json(self.registry.root / "state.json")
            if state["closed"] or remaining_seconds(state) <= 0:
                break
            self.poll_once()
            if stop_event is None:
                time.sleep(interval)
            else:
                stop_event.wait(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--run-root", type=Path)
    args = parser.parse_args()
    FileBridge(args.container, args.registry, args.input, args.image, args.run_root).serve()
