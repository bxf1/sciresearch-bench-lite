import json
import unittest

from runner.preflight import inspect_prerequisites


class PreflightTest(unittest.TestCase):
    def fake(self, cpus=4, containers=(), credential="DO_NOT_LEAK", available=True):
        calls = []

        def execute(command):
            calls.append(command)
            if command[:2] == ["docker", "version"]:
                data = {"Client": {"Version": "29.3.0"}, "Server": {"Version": "29.3.0", "Os": "linux", "Arch": "aarch64"}}
            elif command[:2] == ["docker", "info"]:
                if not available:
                    return {"returncode": 1, "stdout": "", "error": "command_failed"}
                data = {"NCPU": cpus, "MemTotal": 8*1024**3, "CgroupVersion": "2", "SwapLimit": True,
                        "SecurityOptions": ["name=seccomp,profile=builtin"], "Secrets": credential}
            elif command[:2] == ["docker", "ps"]:
                return {"returncode": 0, "stdout": "\n".join(json.dumps(v) for v in containers)}
            elif command[:3] == ["docker", "image", "inspect"]:
                data = {"Id": "sha256:numeric", "Os": "linux", "Architecture": "arm64",
                        "Config": {"Env": ["API_KEY=" + credential]}}
            elif command == ["gh", "auth", "status"]:
                return {"returncode": 0, "stdout": "auth token: " + credential}
            elif command == ["pi", "--version"]:
                return {"returncode": 0, "stdout": "0.84.1\n"}
            else:
                raise AssertionError(command)
            return {"returncode": 0, "stdout": json.dumps(data)}
        return execute, calls

    def test_read_only_and_no_credentials_in_report(self):
        execute, calls = self.fake()
        result = inspect_prerequisites(execute=execute, environ={"OPENAI_API_KEY": "DO_NOT_LEAK"})
        self.assertNotIn("DO_NOT_LEAK", json.dumps(result))
        self.assertTrue(result["functional_prerequisites_present"])
        self.assertFalse(result["formal"])
        self.assertFalse(result["formal_ready"])
        self.assertEqual(result["service_mutations"], [])
        self.assertFalse(any("run" in c or "start" in c or "stop" in c or "rm" in c for c in calls))

    def test_shared_two_cpu_machine_reports_blockers_without_mutation(self):
        execute, calls = self.fake(cpus=2, containers=[{"ID": "existing", "Names": "user-service", "Image": "user:image", "Status": "Up"}])
        result = inspect_prerequisites(execute=execute, environ={})
        codes = {row["code"] for row in result["blockers"]}
        self.assertTrue({"research_cpu_shortfall", "shared_daemon_workloads", "model_endpoint_not_verified"} <= codes)
        self.assertTrue(result["functional_prerequisites_present"])
        self.assertFalse(result["formal_ready"])

    def test_docker_unavailable_is_not_a_scientific_failure(self):
        execute, calls = self.fake(available=False)
        result = inspect_prerequisites(execute=execute, environ={})
        self.assertFalse(result["functional_prerequisites_present"])
        self.assertIn("docker_unavailable", [r["code"] for r in result["blockers"]])
        self.assertNotIn("scientific_pass", result)


if __name__ == "__main__":
    unittest.main()
