"""No-container/no-model tests of the full native Trial pilot wiring."""
import asyncio
import json
import os
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from harbor.models.task.config import NetworkMode, NetworkPolicy
from harbor.models.verifier.result import VerifierResult
from harbor.trial.hooks import TrialEvent
from harbor.trial.single_step import SingleStepTrial
from harbor.trial.trial import Trial

from runner.common import digest, read_json, write_json
from runner.harbor_environment import ResearchDockerEnvironment
from runner.harbor_pilot import (PilotController, build_task, container_records, native_setup_evidence, relay_outcome, retain_safe_records,
                                 trial_config, validate_admission, verify_model_credential, pilot_settings, require_host_capacity)
from runner.registry import Registry


IMAGE = "sha256:" + "b" * 64


def admission(root):
    return {"schema_version": 1, "model": "deepseek-v4-pro", "token": "a" * 64,
            "base_url": "http://172.31.0.2:8787", "relay_ip": "172.31.0.2", "relay_port": 8787,
            "container_name": "sciresearch-relay-" + "c" * 12, "container_id": "d" * 64,
            "network_name": "sciresearch-relay-" + "c" * 12, "image_id": IMAGE,
            "output_root": str(root / "relay-private"), "admission_path": str(root / "relay-private/admission.json")}


def public_cases(root, split="public-dev"):
    root.mkdir(parents=True)
    rows = []
    for level in range(3):
        for number in range(2):
            identifier = f"c{level}{number}"
            case = root / "cases" / identifier
            case.mkdir(parents=True)
            for name in ("metadata.json", "observations.csv", "target_grid.npy"):
                (case / name).write_bytes(b"public-fixture")
            rows.append({"id": identifier, "path": "cases/" + identifier, "level": level})
    write_json(root / "manifest.json", {"contract_version": "0.3.0", "task": "heat", "split": split, "cases": rows})
    return root


def status(**changes):
    result = {"schema_version": 1, "model": "deepseek-v4-pro", "request_count": 1,
              "successful_requests": 1, "failed_requests": 0, "inflight": 0,
              "protocol_violation": False, "evidence_error": False, "state": "ready",
              "last_request_outcome": "success", "budget_exhausted": False}
    result.update(changes)
    return result


def bare_environment():
    env = ResearchDockerEnvironment.__new__(ResearchDockerEnvironment)
    env.pilot_is_research = True
    env.pilot_sealed_policy = None
    env._pilot_record = Mock()
    return env


class EnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_pi_keeps_exit_status_without_unbounded_host_stdout(self):
        env=bare_environment()
        returned=SimpleNamespace(return_code=17,stdout="",stderr="")
        with patch.object(ResearchDockerEnvironment.__bases__[0],"exec",new_callable=AsyncMock,return_value=returned) as native:
            result=await env.exec("set -o pipefail; pi --print --mode json --model test | tee /logs/agent/pi.txt")
        self.assertEqual(result.return_code,17)
        self.assertTrue(native.call_args.args[0].endswith(") >/dev/null 2>&1"))

    async def test_network_stays_sealed_when_native_trial_restores_public(self):
        env = bare_environment()
        allowed = NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=["172.31.0.2"])
        with patch.object(ResearchDockerEnvironment.__bases__[0], "set_network_policy", new_callable=AsyncMock) as native:
            await env.seal_research_network(allowed)
            await env.set_network_policy(NetworkPolicy(network_mode=NetworkMode.PUBLIC))
            self.assertEqual(native.await_count, 1)
            self.assertEqual(env.pilot_sealed_policy, allowed)
            self.assertEqual(env._pilot_record.call_args.args[0], "setup_network_restore_blocked")
            with self.assertRaisesRegex(ValueError, "sealed"):
                await env.set_network_policy(NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=["example.com"]))

    async def test_native_logs_and_artifacts_cannot_leave_research_environment(self):
        env = bare_environment()
        env.exec = AsyncMock(side_effect=AssertionError("must not list R files"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            await env.download_dir_filtered(source_dir="/logs/agent", target_dir=target, exclude=["*"])
            await env.service_download_dir_with_exclusions(source_dir="/logs/artifacts", target_dir=target, exclude=["*", "**/*"])
            await env.upload_dir(target, "/logs/agent")
            self.assertEqual(list(target.iterdir()), [])
            for source in ("/logs/agent", "/workspace"):
                with self.assertRaises(ValueError):
                    await env.download_dir(source, target)
            with self.assertRaises(ValueError):
                await env.download_file("/logs/agent/secret", target / "secret")
            with self.assertRaises(ValueError):
                await env.service_download_dir_with_exclusions(source_dir="/workspace", target_dir=target, exclude=["*"])
            env.exec.assert_not_awaited()


class ConfigurationTests(unittest.TestCase):
    def test_formal_configuration_uses_fixed_resources_no_turn_cap_and_registration_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = public_cases(root / "public-dev")
            relay = admission(root)
            settings = dict(pilot_settings(), formal=True, group="g2", research_seconds=1800, max_evaluations=20,
                            max_turns=None, research_vcpu=4, research_memory_bytes=4 * 1024**3,
                            prompt="frozen prompt", prompt_hashes={}, attempt_id="planned-attempt")
            task = root / "build/task"
            build_task(task, public, IMAGE, IMAGE, relay["relay_ip"], settings=settings)
            config = trial_config(root, task, relay, root / "overlay.json", None, settings=settings)
            self.assertIsNone(config.agent.kwargs["max_turns"])
            self.assertEqual(config.agent.override_timeout_sec, 1800)
            self.assertEqual(config.verifier.import_path, "runner.study:RegistrationVerifier")
            self.assertEqual(config.verifier.kwargs["task_name"], "heat")
            self.assertNotIn("replay_config", config.verifier.kwargs)
            self.assertIn("cpus = 4", (task / "task.toml").read_text())
            self.assertIn("memory_mb = 4096", (task / "task.toml").read_text())

    def test_formal_actual_daemon_capacity_is_not_downscaled(self):
        settings = dict(pilot_settings(), research_vcpu=4, research_memory_bytes=4 * 1024**3)
        with patch("runner.harbor_pilot.command", return_value=SimpleNamespace(stdout=json.dumps({"NCPU": 2, "MemTotal": 4 * 1024**3}))):
            with self.assertRaisesRegex(RuntimeError, "physical capacity"):
                require_host_capacity(settings)
        self.assertEqual(settings["research_vcpu"], 4)
        with patch("runner.harbor_pilot.command", return_value=SimpleNamespace(stdout=json.dumps({"NCPU": 8, "MemTotal": 16 * 1024**3}))):
            self.assertEqual(require_host_capacity(settings)["actual_vcpu"], 8)

    def test_unverified_direct_provider_endpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            value = admission(Path(directory))
            value["base_url"] = "https://api.deepseek.com/anthropic"
            with self.assertRaises(ValueError):
                validate_admission(value)

    def test_fresh_task_preserves_public_only_pinned_contract_and_config_has_no_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = public_cases(root / "public-dev")
            relay = admission(root)
            build_task(root / "build/task", public, IMAGE, IMAGE, relay["relay_ip"])
            config = trial_config(root, root / "build/task", relay, root / "overlay.json", {})
            serialized = config.model_dump_json()
            self.assertNotIn(relay["token"], serialized)
            self.assertIn("BENCH_RELAY_KEY", serialized)
            self.assertEqual(config.agent.kwargs["max_turns"], 12)
            self.assertEqual(config.environment.kwargs["auto_mounting"], False)
            self.assertEqual(read_json(root / "build/task/environment/public-dev/manifest.json")["split"], "public-dev")
            self.assertFalse((root / "build/task/private").exists())

    def test_nonpublic_task_build_is_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = public_cases(root / "invalid", split="final-test")
            with self.assertRaisesRegex(ValueError, "split"):
                build_task(root / "build/task", public, IMAGE, IMAGE, "172.31.0.2")
            self.assertFalse((root / "build/task").exists())

    def test_native_credential_must_be_only_temporary_relay_key(self):
        with tempfile.TemporaryDirectory() as directory:
            value = admission(Path(directory))
            agent = SimpleNamespace(model_connection=SimpleNamespace(api_key=value["token"], env={"BENCH_RELAY_KEY": value["token"]}), extra_env={})
            with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "fake-provider-key"}):
                self.assertTrue(verify_model_credential(agent, value)["provider_credential_absent_from_native_env"])
                agent.extra_env["ANTHROPIC_AUTH_TOKEN"] = "fake-provider-key"
                with self.assertRaisesRegex(RuntimeError, "provider credential"):
                    verify_model_credential(agent, value)
                agent.extra_env.clear()
                agent.model_connection.api_key = "fake-provider-key"
                with self.assertRaisesRegex(RuntimeError, "temporary"):
                    verify_model_credential(agent, value)


class OutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_formal_setup_hashes_models_without_installing_a_turn_extension(self):
        settings = dict(pilot_settings(), formal=True, max_turns=None,
                        expected_system_sha256="a" * 64, expected_tools_sha256="b" * 64)
        config = {"providers": {"custom": {"apiKey": "$BENCH_RELAY_KEY"}}}
        expected = {"models.json": digest((json.dumps(config, indent=2) + "\n").encode())}
        observed = {"version": "0.84.1", "configuration_sha256": expected, "installed_source_sha256": {"dist/core/tools/bash.js": "f" * 64}}
        env = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(return_code=0, stdout=json.dumps(observed))))
        fresh = status(request_count=0, successful_requests=0, last_request_outcome=None,
                       limits={"thinking": {"type": "disabled"}, "temperature": 0.0, "top_p": 1.0,
                               "request_output_limit": 4096, "session_output_limit": 32768,
                               "expected_system_sha256": "a" * 64, "expected_tools_sha256": "b" * 64})
        # An agent without _build_max_turns_extension is sufficient in formal mode.
        result = await native_setup_evidence(SimpleNamespace(), env, config, fresh, settings=settings)
        self.assertIsNone(result["max_turns"])
        self.assertIn("unexpected turn cap extension", env.exec.call_args.kwargs["command"])
        fresh["limits"]["expected_system_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "wire system/tools"):
            await native_setup_evidence(SimpleNamespace(), env, config, fresh, settings=settings)

    async def test_setup_records_actual_native_hashes_and_trusted_policy(self):
        agent=SimpleNamespace(_build_max_turns_extension=lambda turns:"native turn extension")
        config={"providers":{"custom":{"apiKey":"$BENCH_RELAY_KEY"}}}
        expected={"models.json":digest((json.dumps(config,indent=2)+"\n").encode()),
                  "max-turns.ts":digest(b"native turn extension")}
        observed={"version":"0.84.1","configuration_sha256":expected,
                  "installed_source_sha256":{"dist/core/tools/bash.js":"f"*64}}
        env=SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(return_code=0,stdout=json.dumps(observed))))
        fresh=status(request_count=0,successful_requests=0,last_request_outcome=None,
                     limits={"thinking":{"type":"disabled"},"temperature":0.0,"top_p":1.0,
                             "request_output_limit":4096,"session_output_limit":32768})
        record=await native_setup_evidence(agent,env,config,fresh)
        self.assertEqual(record["configuration_sha256"],expected)
        self.assertEqual(record["native_requested_reasoning_effort"],"off")
        self.assertEqual(record["relay_enforced_policy"]["thinking"],{"type":"disabled"})
        fresh["limits"]["thinking"]={"type":"enabled"}
        with self.assertRaisesRegex(RuntimeError,"relay policy"):
            await native_setup_evidence(agent,env,config,fresh)
        fresh["limits"]["thinking"]={"type":"disabled"}
        observed["configuration_sha256"]["max-turns.ts"]="0"*64
        env.exec.return_value.stdout=json.dumps(observed)
        with self.assertRaisesRegex(RuntimeError,"hash mismatch"):
            await native_setup_evidence(agent,env,config,fresh)

    def test_sticky_relay_evidence_failure_dominates_success_budget_and_timeout(self):
        # Concurrent B may finish successfully after A failed to append evidence.
        for changes in ({"evidence_error":True}, {"evidence_error":None}, {"state":"failed_closed"}):
            broken=status(last_request_outcome="success",budget_exhausted=True,**changes)
            self.assertEqual(relay_outcome(broken)[0],"infrastructure_failed")
            self.assertEqual(relay_outcome(broken,interrupted=True)[0],"infrastructure_failed")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            controller=PilotController(root,root,IMAGE,admission(root))
            controller.record.update(model_run_started=True,relay_status=status(evidence_error=True,budget_exhausted=True))
            controller.deadline_fired=True
            self.assertEqual(controller.outcome(SimpleNamespace(exception_info=None))[0],"infrastructure_failed")

    def test_relay_token_quota_is_normal_fallback_but_upstream_429_remains_api_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            controller=PilotController(root,root,IMAGE,admission(root))
            controller.record.update(model_run_started=True,relay_status=status(budget_exhausted=True))
            native=SimpleNamespace(exception_info=SimpleNamespace(exception_type="NonZeroAgentExitCodeError"))
            outcome,reason=controller.outcome(native)
            self.assertEqual(outcome,"research_timeout")
            self.assertIn("token quota",reason)
            self.assertNotIn("wall",reason)
            controller.record["relay_status"]=status(budget_exhausted=True,last_request_outcome="upstream_http_error",last_upstream_status=429)
            self.assertEqual(controller.outcome(native)[0],"api_failed")

    def test_host_relay_proves_terminal_api_failure_not_recovered_history(self):
        self.assertIsNone(relay_outcome(status(failed_requests=2)))
        self.assertEqual(relay_outcome(status(last_request_outcome="upstream_http_error"))[0], "api_failed")
        for bad in (status(inflight=1), status(protocol_violation=True), status(request_count=0), {}):
            self.assertEqual(relay_outcome(bad)[0], "infrastructure_failed")
        self.assertIsNone(relay_outcome(status(last_request_outcome="client_disconnected"), interrupted=True))
        for outcome in ("upstream_http_error", "upstream_transport_error", "upstream_timeout", "stream_error"):
            self.assertEqual(relay_outcome(status(last_request_outcome=outcome), interrupted=True)[0], "api_failed")

    async def test_agent_end_does_not_close_before_native_timeout_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = PilotController(root, root, IMAGE, admission(root))
            controller.stop_research = AsyncMock()
            controller.close_registry = AsyncMock()
            result = SimpleNamespace(exception_info=None)
            await controller.hook(SimpleNamespace(event=TrialEvent.AGENT_END, result=result))
            controller.close_registry.assert_not_awaited()
            result.exception_info = SimpleNamespace(exception_type="AgentTimeoutError")
            controller.trial = SimpleNamespace(agent_environment=SimpleNamespace(session_id="test"))
            controller.inspect_session = AsyncMock()
            await controller.hook(SimpleNamespace(event=TrialEvent.VERIFICATION_START, result=result))
            controller.close_registry.assert_awaited_once_with(result)

    async def test_close_records_trusted_api_error_and_wall_timeout_separately(self):
        for timed_out in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); workspace = root / "workspace"; workspace.mkdir()
                controller = PilotController(root, root, IMAGE, admission(root))
                controller.registry = Registry.create(root / "registry", workspace, "heat", "g1-pilot", 600, 4)
                controller.record["model_run_started"] = True
                native = SimpleNamespace(exception_info=SimpleNamespace(exception_type="AgentTimeoutError") if timed_out else None)
                observed = status(last_request_outcome="client_disconnected" if timed_out else "upstream_http_error")
                with patch("runner.harbor_pilot.transport", return_value=SimpleNamespace(read_status=Mock(return_value=observed))):
                    await controller.close_registry(native)
                state = read_json(root / "registry/state.json")
                self.assertEqual(state["attempt_status"], "research_timeout" if timed_out else "api_failed")
                self.assertTrue(state["closed"])

    async def test_active_bridge_prevents_registry_close(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            controller=PilotController(root,root,IMAGE,admission(root))
            controller.registry=Mock()
            controller.bridge_thread=SimpleNamespace(is_alive=lambda:True)
            with self.assertRaisesRegex(RuntimeError,"active"):
                await controller.close_registry(SimpleNamespace(exception_info=None))
            controller.registry.close.assert_not_called()

    async def test_cleanup_failure_still_stops_environment_relay_and_saves_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            controller=PilotController(root,root,IMAGE,admission(root))
            controller.cid="c"*64
            controller.record.update(evaluation_status="valid",score=100,reward=1,attempt_status="completed")
            env=SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError("native stop failed")))
            controller.trial=SimpleNamespace(agent_environment=env,paths=SimpleNamespace(trial_dir=root/"native"))
            fake=SimpleNamespace(cleanup_relay=Mock(return_value={"all_removed":True,"errors":{}}))
            with patch("runner.harbor_pilot.command",side_effect=subprocess.TimeoutExpired("docker",1)), patch("runner.harbor_pilot.transport",return_value=fake),patch("runner.harbor_pilot.retain_safe_records",return_value={}):
                await controller.finish()
            env.stop.assert_awaited_once()
            fake.cleanup_relay.assert_called_once()
            result=read_json(root/"result.json")
            self.assertEqual(result["status"],"pilot_invalid")
            self.assertIsNone(result["reward"])
            self.assertIn("research_stop",result["cleanup_errors"])
            self.assertIn("environment_stop",result["cleanup_errors"])

    async def test_unexpected_research_stop_failure_does_not_skip_environment_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            controller=PilotController(root,root,IMAGE,admission(root))
            controller.stop_research=AsyncMock(side_effect=OSError("event log failed"))
            env=SimpleNamespace(stop=AsyncMock())
            controller.trial=SimpleNamespace(agent_environment=env,paths=SimpleNamespace(trial_dir=root/"native"))
            fake=SimpleNamespace(cleanup_relay=Mock(return_value={"all_removed":True,"errors":{}}))
            with patch("runner.harbor_pilot.transport",return_value=fake),patch("runner.harbor_pilot.retain_safe_records",return_value={}):
                await controller.finish()
            env.stop.assert_awaited_once()
            fake.cleanup_relay.assert_called_once()
            self.assertIn("research_stop_unexpected",read_json(root/"result.json")["cleanup_errors"])


class RetentionTests(unittest.TestCase):
    def test_container_evidence_keeps_only_env_names_and_rejects_provider_key(self):
        item={"Id":"a"*64,"Image":IMAGE,"HostConfig":{},"Mounts":[],"Config":{"User":"1000","Labels":{},"Env":["BENCH_RELAY_KEY=temporary-relay-value"]}}
        with patch.dict(os.environ,{"ANTHROPIC_AUTH_TOKEN":"fake-provider-key"}):
            result=container_records([item],"temporary-relay-value")
            self.assertEqual(result[0]["Config"]["environment_variable_names"],["BENCH_RELAY_KEY"])
            self.assertNotIn("temporary-relay-value",json.dumps(result))
            item["Config"]["Env"].append("UNEXPECTED=fake-provider-key")
            with self.assertRaisesRegex(RuntimeError,"provider credential"):
                container_records([item],"temporary-relay-value")

    def test_decoded_token_redacted_but_private_admission_never_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); native=root/"native"; native.mkdir()
            value=admission(root); private=Path(value["output_root"]); private.mkdir()
            write_json(private/"admission.json",value)
            write_json(private/"startup.json",{"status":"ready"})
            (native/"result.json").write_text(json.dumps({"x":"".join("\\u%04x"%ord(c) for c in value["token"])}))
            retain_safe_records(root,native,value)
            self.assertNotIn(value["token"],(native/"result.json").read_text())
            self.assertFalse((root/"relay-evidence/admission.json").exists())
            self.assertTrue(read_json(root/"record-retention.json")["token_redactions"])


class NativeTrialTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_trial_factory_and_lifecycle_hooks_without_container_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); public=public_cases(root/"public-dev"); relay=admission(root)
            task=root/"build/task"; build_task(task,public,IMAGE,IMAGE,relay["relay_ip"])
            overlay=root/"overlay.json"; write_json(overlay,{"services":{}})
            config=trial_config(root,task,relay,overlay,{})
            # Fail the test if any subprocess is accidentally attempted.
            with patch("subprocess.run",side_effect=AssertionError("no subprocess allowed")), patch("runner.harbor_environment.DockerEnvironment._egress_control_kernel_support",return_value=True):
                trial=await Trial.create(config)
                self.assertIs(type(trial),SingleStepTrial)
                verify_model_credential(trial.agent,relay)
                self.assertNotIn(relay["token"],trial.paths.lock_path.read_text())
                order=[]
                async def capture(event): order.append(event.event)
                for event in TrialEvent: trial.add_hook(event,capture)
                trial._prepare=AsyncMock()
                trial.agent.run=AsyncMock()
                trial.agent_environment.set_network_policy=AsyncMock()
                trial.agent_environment.stop=AsyncMock()
                trial._configure_web_tools=AsyncMock()
                trial._run_separate_verifier=AsyncMock(return_value=VerifierResult(rewards={"reward":0}))
                result=await trial.run()
            self.assertEqual(order,[TrialEvent.START,TrialEvent.AGENT_START,TrialEvent.AGENT_END,TrialEvent.VERIFICATION_START,TrialEvent.END])
            self.assertEqual(result.verifier_result.rewards,{"reward":0})
            self.assertNotIn(relay["token"],trial.paths.config_path.read_text())
            self.assertEqual(list(trial.paths.agent_dir.iterdir()),[])

    async def test_native_admission_failure_cannot_reach_agent_or_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); public=public_cases(root/"public-dev"); relay=admission(root)
            task=root/"build/task"; build_task(task,public,IMAGE,IMAGE,relay["relay_ip"])
            overlay=root/"overlay.json"; write_json(overlay,{"services":{}})
            config=trial_config(root,task,relay,overlay,{})
            with patch("subprocess.run",side_effect=AssertionError("no subprocess allowed")), patch("runner.harbor_environment.DockerEnvironment._egress_control_kernel_support",return_value=True):
                trial=await Trial.create(config)
                trial._prepare=AsyncMock()
                trial.agent.run=AsyncMock()
                trial.agent_environment.stop=AsyncMock()
                trial._run_separate_verifier=AsyncMock()
                async def reject(event): raise RuntimeError("actual R relay probe rejected")
                trial.add_hook(TrialEvent.AGENT_START,reject)
                result=await trial.run()
                trial.agent.run.assert_not_awaited()
                trial._run_separate_verifier.assert_not_awaited()
                trial.agent_environment.stop.assert_awaited_once()
                self.assertEqual(result.exception_info.exception_type,"RuntimeError")
                self.assertTrue(trial.paths.result_path.is_file())


if __name__ == "__main__":
    unittest.main()
