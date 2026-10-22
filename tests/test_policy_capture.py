"""Offline tests: receipt guards and the actual terminal capture extension."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from runner.model_relay import encoded
from runner.policy_capture import (CAPTURE_EXTENSION, DUMMY_KEY, EXPECTED_TOOLS, MARKER,
                                   capture_task, parse_capture, validate_container)


IMAGE = "sha256:" + "a" * 64


def payload():
    return {"schema_version": 1, "stage": "before_provider_request", "model": "deepseek-v4-pro",
            "stream": True, "requested_max_tokens": 16384,
            "system": [{"type": "text", "text": "中文", "cache_control": {"type": "ephemeral"}}],
            "tools": [{"name": name, "description": name, "input_schema": {"type": "object"}}
                      for name in EXPECTED_TOOLS]}


def container():
    return {"Id": "b" * 64, "Image": IMAGE, "Mounts": [],
            "Config": {"User": "1000:1000", "WorkingDir": "/workspace", "Env": ["BENCH_RELAY_KEY=" + DUMMY_KEY]},
            "HostConfig": {"NetworkMode": "none", "NanoCpus": 1_000_000_000,
                           "Memory": 1024 ** 3, "MemorySwap": 1024 ** 3, "PidsLimit": 128,
                           "Privileged": False, "CapDrop": ["ALL"], "CapAdd": None,
                           "SecurityOpt": ["no-new-privileges"]}}


class PolicyCaptureTests(unittest.TestCase):
    def test_receipt_preserves_native_key_order_for_relay_hash(self):
        value = parse_capture(MARKER + json.dumps(payload()))
        self.assertEqual(list(value["system"][0]), ["type", "text", "cache_control"])
        self.assertIn(b"\\u4e2d\\u6587", encoded(value["system"]))
        self.assertNotEqual(encoded(value["system"]), json.dumps(value["system"], sort_keys=True).encode())

    def test_missing_duplicate_and_malformed_receipts_are_rejected(self):
        line = MARKER + json.dumps(payload())
        for value in ("", line + "\n" + line, MARKER + '{"schema_version":1,"schema_version":1}'):
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                parse_capture(value)

    def test_turn_cap_and_nondefault_tool_schema_are_rejected(self):
        value = payload()
        value["system"][0]["text"] = "You have a hard budget of 12 model turns."
        with self.assertRaisesRegex(ValueError, "max-turns"):
            parse_capture(MARKER + json.dumps(value))
        value = payload()
        value["tools"].append({"name": "extra"})
        with self.assertRaisesRegex(ValueError, "tools"):
            parse_capture(MARKER + json.dumps(value))

    def test_actual_extension_exits_before_continuation_without_mutation(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "local Node is required for the executable hook test")
        value = payload()
        native_payload = {key: value[key] for key in ("model", "stream", "system", "tools")}
        native_payload["max_tokens"] = 16384
        script = CAPTURE_EXTENSION.replace("export default function (pi)", "function capture(pi)")
        script += "\nlet handler; capture({on: (name, callback) => {handler=callback;}});\n"
        script += "handler({payload:" + json.dumps(native_payload) + "}); throw Error('HTTP continuation reached');"
        result = subprocess.run([node, "--input-type=module"], input=script, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parse_capture(result.stdout), value)

    def test_actual_extension_failure_also_exits_instead_of_throwing_to_pi(self):
        script = CAPTURE_EXTENSION.replace("export default function (pi)", "function capture(pi)")
        script += "\nlet handler; capture({on: (_, callback) => {handler=callback;}});\n"
        script += "try {handler({payload:{}});} catch (_) {process.exit(99);} process.exit(98);"
        result = subprocess.run([shutil.which("node"), "--input-type=module"], input=script,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 71)
        self.assertNotIn(MARKER, result.stdout)

    def test_network_mount_and_credential_guards(self):
        self.assertTrue(validate_container(container(), IMAGE)["network_disabled"])
        for change in ("network", "mount", "credential", "root"):
            value = container()
            if change == "network": value["HostConfig"]["NetworkMode"] = "bridge"
            if change == "mount": value["Mounts"] = [{"Source": "/private"}]
            if change == "credential": value["Config"]["Env"].append("ANTHROPIC_AUTH_TOKEN=not-dummy")
            if change == "root": value["Config"]["User"] = "0"
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_container(value, IMAGE)

    def test_missing_image_preserves_failure_and_checks_own_cleanup(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command[1:3] == ["image", "inspect"]:
                return subprocess.CompletedProcess(command, 1, "", "image unavailable")
            return subprocess.CompletedProcess(command, 0, "", "")
        with tempfile.TemporaryDirectory() as root, patch("runner.policy_capture.subprocess.run", side_effect=run):
            result = capture_task("heat", IMAGE, Path(root) / "capture")
            self.assertEqual(result["status"], "capture_failed")
            self.assertTrue(result["cleanup"]["removed"])
            self.assertEqual(result["model_calls"], 0)
            self.assertTrue((Path(root) / "capture/result.json").exists())
        self.assertEqual(calls[1][1:3], ["rm", "-f"])
        self.assertTrue(calls[1][3].startswith("sciresearch-policy-capture-"))


if __name__ == "__main__":
    unittest.main()
