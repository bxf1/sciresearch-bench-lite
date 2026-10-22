"""Protocol tests only; real Linux PID namespace probes are separately recorded."""
import copy
import socket
import struct
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from runner import process_timer as timer


class ProcessTimerTests(unittest.TestCase):
    def test_read_exact_handles_fragmentation_and_premature_eof(self):
        stream = MagicMock()
        stream.recv.side_effect = [b"a", b"bc"]
        self.assertEqual(timer.receive_exact(stream, 3), b"abc")
        stream.recv.side_effect = [b"a", b""]
        with self.assertRaises(RuntimeError):
            timer.receive_exact(stream, 2)

    def test_pidfd_exit_precedes_waiting_all_adopted_subtrees(self):
        calls = []
        poller = MagicMock()
        poller.poll.side_effect = lambda: calls.append("main_exited") or [(50, 1)]
        results = iter([(101, 0), InterruptedError(), (102, 0), ChildProcessError()])
        def wait(pid, flags):
            self.assertEqual((pid, flags), (-1, 0))
            self.assertEqual(calls[0], "main_exited")
            calls.append("wait_child")
            value = next(results)
            if isinstance(value, Exception):
                raise value
            return value
        with patch.object(timer.select, "poll", return_value=poller, create=True), patch.object(timer.os, "waitpid", side_effect=wait):
            self.assertEqual(timer.wait_descendants(50), 2)
        poller.register.assert_called_once_with(50, timer.select.POLLIN)
        self.assertEqual(calls.count("wait_child"), 4)

    def test_launcher_sends_one_start_and_execs_fixed_python_with_cloexec(self):
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.recv.return_value = b"GO"
        with patch.object(timer.os, "getuid", return_value=65534), patch.object(timer.os, "getgid", return_value=65534), \
                patch.object(timer.socket, "socket", return_value=stream), patch.object(timer.time, "monotonic_ns", return_value=42), \
                patch.object(timer.os, "execv") as execute:
            timer.launch("lu")
        stream.set_inheritable.assert_called_once_with(False)
        stream.sendall.assert_called_once_with(struct.pack("!Q", 42))
        self.assertEqual(execute.call_args.args, (timer.sys.executable, [timer.sys.executable, "-B", "/submission/solve.py",
                         "--input", "/input", "--output", "/output", "--seed", "0", "--method", "lu"]))

    def test_wrong_uid_or_missing_ready_cannot_launch_candidate(self):
        with patch.object(timer.os, "getuid", return_value=65533), patch.object(timer.os, "execv") as execute:
            with self.assertRaises(RuntimeError):
                timer.launch()
            execute.assert_not_called()
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.recv.return_value = b"NO"
        with patch.object(timer.os, "getuid", return_value=65534), patch.object(timer.os, "getgid", return_value=65534), \
                patch.object(timer.socket, "socket", return_value=stream), patch.object(timer.os, "execv") as execute:
            with self.assertRaises(RuntimeError):
                timer.launch()
            execute.assert_not_called()

    def test_only_private_timer_uid_can_read_record(self):
        with patch.object(timer.os, "getuid", return_value=65534):
            with self.assertRaises(RuntimeError):
                timer.read_record()

    def test_record_commit_reuses_preallocated_pages_and_publishes_marker_last(self):
        with tempfile.TemporaryDirectory() as temporary:
            record,done=Path(temporary)/"record",Path(temporary)/"done"
            with patch.object(timer,"RECORD",record),patch.object(timer,"COMPLETE",done):
                record_fd,done_fd=timer.reserve_record()
                inode=record.stat().st_ino
                self.assertEqual(record.stat().st_size,timer.RECORD_BYTES)
                self.assertEqual(done.read_bytes(),b"0")
                timer.commit_record({"test":"synthetic"},record_fd,done_fd)
                self.assertEqual(record.stat().st_ino,inode)
                self.assertEqual(record.stat().st_size,timer.RECORD_BYTES)
                self.assertEqual(done.read_bytes(),b"1")
                self.assertEqual(json.loads(record.read_text()),{"test":"synthetic"})

    def test_forged_or_promoted_timing_record_is_rejected(self):
        valid = {"schema_version": 1, "timing_scope": timer.SCOPE, "clock": "CLOCK_MONOTONIC",
                 "started_monotonic_ns": 1_000_000_000, "finished_monotonic_ns": 1_200_000_000,
                 "execution_wall_seconds": .2, "timer_uid": 65533, "candidate_uid": 65534,
                 "all_candidate_processes_terminated": True, "formal_timing": False, "machine_id": "synthetic"}
        self.assertEqual(timer.validate_record(valid), valid)
        for changes in ({"timer_uid": 65534}, {"formal_timing": True}, {"finished_monotonic_ns": 1},
                        {"started_monotonic_ns": True}, {"execution_wall_seconds": float("nan")},
                        {"execution_wall_seconds": .1}, {"all_candidate_processes_terminated": False}):
            record = copy.deepcopy(valid)
            record.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                timer.validate_record(record)


if __name__ == "__main__":
    unittest.main()
