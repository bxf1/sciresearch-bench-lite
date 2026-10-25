"""File bridge safety tests: synthetic local data and mocked Docker only."""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public import bridge_io, export_source, file_bench
from runner import file_bridge
from runner.artifact_gate import ArtifactError, extract_tar, snapshot_source
from runner.common import VERSION, canonical, digest, read_json, write_json
from runner.registry import Registry


def request(identifier, operation="evaluate", value="candidate"):
    return {"version": 1, "request_id": identifier, "operation": operation,
            "source" if operation == "evaluate" else "candidate_id": value}


class LocalTransport:
    """A local stand-in for the fixed root helpers; never executes Docker."""
    def __init__(self, workspace):
        self.workspace = workspace
        self.exported = []
        self.responses = []
        self.fail_delivery = False

    def poll(self):
        return bridge_io.read_requests(self.workspace)

    def respond(self, identifier, response):
        if self.fail_delivery:
            raise OSError("simulated Docker transport interruption")
        self.responses.append(response)
        bridge_io.write_response(identifier, response, self.workspace)

    def export_source(self, relative, destination, timeout):
        self.exported.append((relative, timeout))
        snapshot_source(self.workspace, relative, destination)


class FileBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS /var and /tmp may be symlinks; the real bridge uses /workspace.
        self.base = Path(self.temp.name).resolve()
        self.r_workspace = self.base / "r-workspace"
        for leaf in ("requests", "responses"):
            (self.r_workspace / ".bench" / leaf).mkdir(parents=True)
        (self.r_workspace / ".bench/responses").chmod(0o755)
        candidate = self.r_workspace / "candidate"
        candidate.mkdir()
        (candidate / "solve.py").write_text("print('synthetic candidate, never executed')\n")
        self.host_workspace = self.base / "host-workspace"
        self.host_workspace.mkdir()
        self.registry = Registry.create(self.base / "registry", self.host_workspace, "heat", "G1")
        self.inputs = self.base / "inputs/heat/pilot-smoke"
        cases = []
        for level in range(3):
            identifier = "case-" + str(level)
            (self.inputs / "cases" / identifier).mkdir(parents=True)
            cases.append({"id": identifier, "path": "cases/" + identifier, "level": level})
        write_json(self.inputs / "manifest.json", {"contract_version": VERSION, "task": "heat", "split": "pilot-smoke", "cases": cases})
        self.transport = LocalTransport(self.r_workspace)
        self.executions = []
        self.checks = []
        self.bridge = file_bridge.FileBridge("trusted-container", self.registry, self.inputs, "test-image",
                                             transport=self.transport, execute=self.execute, check=self.check)

    def execute(self, task, snapshot, inputs, run, image, timeout):
        self.executions.append((task, snapshot, inputs, image, timeout))
        (run / "artifacts").mkdir(parents=True)
        return {"artifact_valid": True, "attempt_status": "completed", "execution_wall_seconds": .1,
                "cpu_seconds": .2, "memory_peak_bytes": 4096, "private_do_not_return": "sentinel"}

    def check(self, task, inputs, artifacts):
        self.checks.append((task, inputs, artifacts))
        return [{"id": "case-" + str(level), "artifact_valid": True, "R_pub": 1.2} for level in range(3)]

    def publish(self, number, operation="evaluate", value="candidate"):
        identifier = f"{number:032x}"
        write_json(self.r_workspace / ".bench/requests" / (identifier + ".json"), request(identifier, operation, value))
        return identifier

    def response(self, identifier):
        return read_json(self.r_workspace / ".bench/responses" / (identifier + ".json"))

    def test_evaluate_finalize_preserves_original_path_and_hash(self):
        identifier = self.publish(1)
        self.assertEqual(self.bridge.poll_once(), 1)
        response = self.response(identifier)
        self.assertTrue(response["ok"])
        self.assertEqual(response["candidate_id"], "candidate-001")
        self.assertEqual(len(self.executions), 1)
        self.assertEqual(len(self.checks), 1)
        self.assertNotIn("private_do_not_return", json.dumps(response))
        record = read_json(self.bridge.root / "requests" / (identifier + ".json"))
        self.assertEqual(record["original_r_source"], "candidate")
        self.assertEqual(record["imported_source"], "imported-" + identifier)
        checksum = record.pop("record_sha256")
        self.assertEqual(checksum, digest(canonical(record)))
        self.registry.verified_snapshot("candidate-001")
        finalized = self.publish(2, "finalize", "candidate-001")
        self.bridge.poll_once()
        self.assertTrue(self.response(finalized)["ok"])
        self.assertEqual(read_json(self.registry.root / "state.json")["final_id"], "candidate-001")

    def test_duplicate_and_mutated_request_do_not_evaluate_twice(self):
        identifier = self.publish(1)
        self.bridge.poll_once()
        self.publish(1, value="different-source")
        self.assertEqual(self.bridge.poll_once(), 0)
        restarted = file_bridge.FileBridge("trusted", self.registry, self.inputs, "image", transport=self.transport,
                                          execute=self.execute, check=self.check)
        self.assertEqual(restarted.poll_once(), 0)
        self.assertEqual(len(self.executions), 1)
        self.assertEqual(len(self.transport.exported), 1)
        self.assertEqual(self.response(identifier)["candidate_id"], "candidate-001")

    def test_failed_publication_retries_the_saved_decision_only(self):
        identifier = self.publish(1)
        self.transport.fail_delivery = True
        self.bridge.poll_once()
        self.assertFalse((self.r_workspace / ".bench/responses" / (identifier + ".json")).exists())
        self.transport.fail_delivery = False
        self.bridge.poll_once()
        self.assertEqual(len(self.executions), 1)
        self.assertEqual(self.response(identifier)["candidate_id"], "candidate-001")

    def test_interruption_during_evaluation_cannot_reexecute_same_request(self):
        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt("synthetic host crash")
        self.bridge.execute = interrupted
        identifier = self.publish(1)
        with self.assertRaises(KeyboardInterrupt):
            self.bridge.poll_once()
        record_path = self.bridge.root / "requests" / (identifier + ".json")
        self.assertEqual(read_json(record_path)["status"], "processing")
        self.bridge.execute = self.execute
        self.bridge.poll_once()
        self.assertEqual(read_json(record_path)["status"], "interrupted")
        self.assertFalse(self.response(identifier)["ok"])
        self.assertIn("will not be executed again", self.response(identifier)["error"])
        self.assertEqual(self.executions, [])
        self.assertEqual(len(self.transport.exported), 1)
        self.assertEqual(len(read_json(self.registry.root / "state.json")["evaluations"]), 1)

    def test_source_export_escape_links_and_fifo_rejected_and_counted(self):
        outside = self.base / "outside-sentinel"
        outside.mkdir()
        (outside / "solve.py").write_text("synthetic private sentinel\n")
        (self.r_workspace / "linked").symlink_to(outside, target_is_directory=True)
        (self.r_workspace / "fifo").mkdir()
        os.mkfifo(self.r_workspace / "fifo/solve.py")
        values = [str(outside), "../outside-sentinel", "linked", "fifo"]
        for number, value in enumerate(values, 1):
            identifier = self.publish(number, value=value)
            self.bridge.poll_once()
            response = self.response(identifier)
            self.assertTrue(response["ok"])
            self.assertFalse(response["feedback"]["artifact_valid"])
            self.assertIn("source_export_error", response["feedback"])
        state = read_json(self.registry.root / "state.json")
        self.assertEqual(len(state["evaluations"]), 4)
        self.assertEqual(self.executions, [])
        self.assertTrue(all(row["source_hash"] is None for row in state["evaluations"]))

    def test_partial_export_cannot_run(self):
        def interrupted(relative, destination, timeout):
            destination.mkdir()
            (destination / "solve.py").write_text("partial export\n")
            raise OSError("truncated tar")
        self.transport.export_source = interrupted
        identifier = self.publish(1)
        self.bridge.poll_once()
        self.assertEqual(self.executions, [])
        self.assertFalse(self.response(identifier)["feedback"]["artifact_valid"])

    def test_evaluation_limit_rejects_before_export(self):
        state = read_json(self.registry.root / "state.json")
        state["max_evaluations"] = 1
        write_json(self.registry.root / "state.json", state)
        self.publish(1)
        self.bridge.poll_once()
        second = self.publish(2)
        self.bridge.poll_once()
        self.assertFalse(self.response(second)["ok"])
        self.assertIn("budget", self.response(second)["error"])
        self.assertEqual(len(self.transport.exported), 1)

    def test_expired_research_rejects_before_export(self):
        state = read_json(self.registry.root / "state.json")
        state["started_at"] -= 1801
        write_json(self.registry.root / "state.json", state)
        identifier = self.publish(1)
        self.bridge.poll_once()
        self.assertFalse(self.response(identifier)["ok"])
        self.assertEqual(self.transport.exported, [])

    def test_export_that_consumes_remaining_deadline_is_registered_failure(self):
        state = read_json(self.registry.root / "state.json")
        now = [state["started_at"] + 1799]
        original_export = self.transport.export_source
        def slow_export(relative, destination, timeout):
            self.assertEqual(len(read_json(self.registry.root / "state.json")["evaluations"]), 1)
            original_export(relative, destination, timeout)
            now[0] += 2
        self.transport.export_source = slow_export
        identifier = self.publish(1)
        with patch("runner.registry.time.time", side_effect=lambda: now[0]):
            self.bridge.poll_once()
        row = read_json(self.registry.root / "state.json")["evaluations"][0]
        self.assertEqual(row["result"]["attempt_status"], "submission_failed")
        self.assertIn("deadline", row["result"]["reason"])
        self.assertIsNone(row["source_hash"])
        self.assertEqual(self.executions, [])
        self.assertFalse(self.response(identifier)["feedback"]["artifact_valid"])

    def test_finalize_accepts_registered_id_only_and_remains_invalid(self):
        identifier = self.publish(1, "finalize", "../../outside")
        self.bridge.poll_once()
        self.assertFalse(self.response(identifier)["ok"])
        self.assertTrue(read_json(self.registry.root / "state.json")["finalization_invalid"])
        self.assertEqual(self.transport.exported, [])

    def test_private_input_split_is_rejected(self):
        manifest = read_json(self.inputs / "manifest.json")
        manifest["split"] = "author-calibration"
        write_json(self.inputs / "manifest.json", manifest)
        with self.assertRaises(ValueError):
            file_bridge.FileBridge("trusted", self.registry, self.inputs, "image", transport=self.transport)

    def test_request_files_are_bounded_regular_and_strict_json(self):
        bad = [b"{" + b" " * 4096, b'{"version":1,"version":1}', b'{"x":NaN}', b'{"x":1e999}']
        for number, payload in enumerate(bad, 1):
            (self.r_workspace / ".bench/requests" / (f"{number:032x}.json")).write_bytes(payload)
        os.mkfifo(self.r_workspace / ".bench/requests" / (f"{5:032x}.json"))
        sentinel = self.base / "private-sentinel.json"
        sentinel.write_text("synthetic secret")
        (self.r_workspace / ".bench/requests" / (f"{6:032x}.json")).symlink_to(sentinel)
        rows = bridge_io.read_requests(self.r_workspace)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all("error" in row for row in rows))
        self.assertNotIn("synthetic secret", json.dumps(rows))
        for payload in (b'{"x":NaN}', b'{"x":1e999}'):
            with self.assertRaises(ValueError):
                bridge_io.parse_json(payload)

    def test_protocol_parent_symlink_rejected(self):
        original = self.r_workspace / ".bench/requests"
        original.rename(self.base / "real-requests")
        original.symlink_to(self.base / "real-requests", target_is_directory=True)
        with self.assertRaises(OSError):
            bridge_io.read_requests(self.r_workspace)

    def test_responses_no_overwrite_or_symlink_or_untrusted_write_directory(self):
        identifier = "a" * 32
        response = {"request_id": identifier, "ok": True}
        bridge_io.write_response(identifier, response, self.r_workspace)
        bridge_io.write_response(identifier, response, self.r_workspace)
        with self.assertRaisesRegex(ValueError, "differs"):
            bridge_io.write_response(identifier, {**response, "ok": False}, self.r_workspace)
        sentinel = self.base / "outside-response"
        sentinel.write_text("unchanged")
        other = "b" * 32
        (self.r_workspace / ".bench/responses" / (other + ".json")).symlink_to(sentinel)
        with self.assertRaises(ValueError):
            bridge_io.write_response(other, {"request_id": other}, self.r_workspace)
        self.assertEqual(sentinel.read_text(), "unchanged")
        (self.r_workspace / ".bench/responses").chmod(0o777)
        with self.assertRaises(PermissionError):
            bridge_io.write_response("c" * 32, {"request_id": "c" * 32}, self.r_workspace)

    def test_response_size_bound_and_request_schema(self):
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            bridge_io.write_response("a" * 32, {"request_id": "a" * 32, "text": "x" * 65536}, self.r_workspace)
        valid = request("a" * 32)
        for value in ({**valid, "version": True}, {**valid, "operation": "shell"}, {**valid, "source": "/x\x00"},
                      {**valid, "extra": "ignored?"}, {**valid, "request_id": "../path"}):
            with self.assertRaises(ValueError):
                bridge_io.validate_request(value)

    def test_client_round_trip_uses_only_protocol_directory(self):
        errors, returned = [], []
        def submit():
            try:
                returned.append(file_bench.submit("evaluate", "candidate", root=self.r_workspace / ".bench", timeout=3, interval=.01))
            except Exception as exc:
                errors.append(exc)
        client = threading.Thread(target=submit)
        client.start()
        deadline = time.monotonic() + 3
        while client.is_alive() and time.monotonic() < deadline:
            self.bridge.poll_once()
            time.sleep(.01)
        client.join(timeout=1)
        self.assertFalse(client.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(returned[0]["ok"])
        self.assertEqual(len(self.executions), 1)

    def test_docker_command_has_fixed_root_helper_and_no_request_arguments(self):
        transport = file_bridge.DockerFileTransport("trusted-container")
        self.assertEqual(transport.command("export_source.py"),
                         ["docker", "exec", "--user", "0", "-i", "trusted-container", "python", "-I", "/opt/bench/export_source.py"])
        with self.assertRaises(ValueError):
            file_bridge.DockerFileTransport("--privileged")
        with self.assertRaises(ValueError):
            transport.command("../../bin/sh")
        mocked = SimpleNamespace(returncode=0, stdout=b"[]", stderr=b"")
        with patch.object(file_bridge.subprocess, "run", return_value=mocked) as run:
            self.assertEqual(transport.poll(), [])
            args, kwargs = run.call_args
            self.assertNotIn("shell", kwargs)
            self.assertEqual(args[0][-2:], ["/opt/bench/bridge_io.py", "poll"])

    def test_export_transport_places_untrusted_source_only_in_stdin(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            data = b"pass\n"
            info = tarfile.TarInfo("solve.py")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        class CapturedInput(io.BytesIO):
            def close(self):
                self.payload = self.getvalue()
                super().close()
        stdin = CapturedInput()
        process = SimpleNamespace(stdin=stdin, stdout=io.BytesIO(output.getvalue()), stderr=io.BytesIO(),
                                  wait=lambda **kwargs: 0, poll=lambda: 0, kill=lambda: None)
        source = "candidate; $(do-not-execute) --privileged"
        with patch.object(file_bridge.subprocess, "Popen", return_value=process) as popen:
            file_bridge.DockerFileTransport("trusted-container").export_source(source, self.base / "transport-import", 10)
        args, kwargs = popen.call_args
        self.assertNotIn(source, args[0])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(json.loads(stdin.payload), {"source": source})
        self.assertEqual((self.base / "transport-import/solve.py").read_text(), "pass\n")

    def test_exporter_requires_root_and_private_staging(self):
        with patch.object(export_source.os, "geteuid", return_value=12345):
            with self.assertRaises(PermissionError):
                export_source.export("candidate", io.BytesIO(), workspace=self.r_workspace, staging=self.base)
        with patch.object(export_source.os, "geteuid", return_value=0):
            with self.assertRaises(PermissionError):
                export_source.export("candidate", io.BytesIO(), workspace=self.r_workspace, staging=self.base)

    def test_exporter_tar_is_derived_from_snapshot_and_bounded_on_import(self):
        staging = self.base / "staging"
        staging.mkdir(mode=0o700)
        original_lstat = Path.lstat
        def owned_lstat(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if path == staging:
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0)
            return info
        expected = (self.r_workspace / "candidate/solve.py").read_bytes()
        original_snapshot = export_source.snapshot_source
        def mutate_after_snapshot(workspace, relative, destination):
            original_snapshot(workspace, relative, destination)
            (self.r_workspace / "candidate/solve.py").write_text("changed by R after trusted snapshot\n")
        output = io.BytesIO()
        with patch.object(export_source.os, "geteuid", return_value=0), patch.object(Path, "lstat", owned_lstat), \
                patch.object(export_source, "snapshot_source", side_effect=mutate_after_snapshot):
            export_source.export("candidate", output, workspace=self.r_workspace, staging=staging)
            for source in (str(self.r_workspace / "candidate"), "../candidate"):
                with self.assertRaises(ArtifactError):
                    export_source.export(source, io.BytesIO(), workspace=self.r_workspace, staging=staging)
        self.assertEqual(list(staging.iterdir()), [])
        output.seek(0)
        imported = self.base / "tar-import"
        extract_tar(output, imported, max_bytes=1024, max_files=1)
        self.assertEqual((imported / "solve.py").read_bytes(), expected)
        self.assertNotEqual((imported / "solve.py").read_bytes(), (self.r_workspace / "candidate/solve.py").read_bytes())
        output.seek(0)
        with self.assertRaises(ArtifactError):
            extract_tar(output, self.base / "too-small", max_bytes=1, max_files=1)


if __name__ == "__main__":
    unittest.main()
