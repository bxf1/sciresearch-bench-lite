"""Authorized truncation retries retain original outcomes and frozen budgets."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from runner import study, study_report
from runner.common import file_hash, read_json, write_json
from runner.harbor_pilot import install_thinking_continuation
from runner.run_plan import thinking_truncation_retry
import test_study


class ContinuationRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fx = test_study.StudyTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.project = self.fx.project
        self.row = self.fx.plan['runs'][0]

    def authorize(self, parent, *, truncated=True):
        root = self.project
        transcript = root / 'truncated.jsonl'
        transcript.write_text(json.dumps({'message': {'role': 'assistant',
            'stopReason': 'length' if truncated else 'stop',
            'rawStopReason': 'max_tokens' if truncated else 'end_turn',
            'usage': {'output': 4096}, 'content': [{'type': 'thinking', 'thinking': 'synthetic partial'}]}})+'\n')
        source = root / 'runner/harbor_pilot.py'
        before = file_hash(source)
        source.write_text('# synthetic continuation repair\n')
        ref = self.fx.fixture.ref
        evidence = ref(root / 'evidence.txt')
        value = {'schema_version': 1, 'kind': 'pi_thinking_continuation',
            'run_plan': ref(self.fx.plan_path), 'previous_repair': None,
            'files': {'runner/harbor_pilot.py': {'before_sha256': before, 'after_sha256': file_hash(source)}},
            'evidence': {name: evidence for name in ['authorization', 'regression_tests', 'synthetic_probe',
                                                    'patch', 'native_patch', 'native_tests', 'original_evidence']},
            'authorized_retry': {'parent_attempt': parent['attempt_id'], 'parent_result': parent['result'],
                                 'transcript': ref(transcript)}}
        path = root / 'freezes' / (self.fx.plan['plan_id'] + '-pi-thinking-repair.json')
        write_json(path, value)
        return ref(path)

    async def test_explicit_retry_and_export_keep_parent_bytes_and_parameters(self):
        await study.start(self.project, self.fx.plan_path, self.row['run_id'], launch=self.fx.launch)
        parent = self.fx.manifest()['attempts'][0]
        before = (self.project / parent['result']['path']).read_bytes()
        authorization = self.authorize(parent)
        result = await study.start(self.project, self.fx.plan_path, self.row['run_id'],
                                   retry_of=parent['attempt_id'], launch=self.fx.launch)
        self.assertEqual((self.project / parent['result']['path']).read_bytes(), before)
        self.assertEqual(result['retry_authorization'], authorization)
        entries = self.fx.manifest()['attempts']
        self.assertEqual(entries[1]['parent_attempt'], parent['attempt_id'])
        self.assertEqual(entries[1]['retry_authorization'], authorization)
        old, new = [launch['settings'] for launch in self.fx.launches]
        self.assertEqual({key for key in old if old[key] != new[key]}, {'attempt_id', 'parent_attempt', 'session_id'})
        manifest = self.project / 'research-runs' / self.fx.plan['plan_id'] / 'manifest.json'
        summary = study_report.export_study(self.project, self.fx.plan_path, manifest, self.project / 'report')
        self.assertEqual(summary['attempts'], 2)
        with self.assertRaisesRegex(ValueError, 'explicit linked retry'):
            await study.start(self.project, self.fx.plan_path, self.row['run_id'],
                              retry_of=entries[1]['attempt_id'], launch=self.fx.launch)

    async def test_registered_candidate_cannot_use_truncation_exception(self):
        self.fx.candidate_tasks = {self.row['task']}
        await study.start(self.project, self.fx.plan_path, self.row['run_id'], launch=self.fx.launch)
        parent = self.fx.manifest()['attempts'][0]
        self.authorize(parent)
        with self.assertRaisesRegex(ValueError, 'unsubmitted'):
            await study.start(self.project, self.fx.plan_path, self.row['run_id'],
                              retry_of=parent['attempt_id'], launch=self.fx.launch)
        self.assertEqual(len(self.fx.manifest()['attempts']), 1)

    async def test_completed_answer_and_changed_parent_cannot_retry(self):
        await study.start(self.project, self.fx.plan_path, self.row['run_id'], launch=self.fx.launch)
        parent = self.fx.manifest()['attempts'][0]
        self.authorize(parent, truncated=False)
        with self.assertRaisesRegex(ValueError, 'thinking-only truncation'):
            thinking_truncation_retry(self.project, self.fx.plan, parent)
        altered = {**parent, 'result': {**parent['result'], 'sha256': '0'*64}}
        with self.assertRaisesRegex(ValueError, 'parent evidence changed'):
            thinking_truncation_retry(self.project, self.fx.plan, altered)

    async def test_context_repair_requires_exact_prior_chain_and_does_not_add_retry(self):
        await study.start(self.project, self.fx.plan_path, self.row['run_id'], launch=self.fx.launch)
        parent = self.fx.manifest()['attempts'][0]
        prior = self.authorize(parent)
        root = self.project
        source = root / 'runner/harbor_pilot.py'
        before = file_hash(source)
        source.write_text('# synthetic context handoff repair\n')
        value = read_json(root / prior['path'])
        value.update(kind='pi_context_compaction_handoff', previous_repair=prior,
                     files={'runner/harbor_pilot.py': {'before_sha256': before, 'after_sha256': file_hash(source)}})
        value.pop('authorized_retry')
        path = root / 'freezes' / (self.fx.plan['plan_id'] + '-pi-context-repair.json')
        write_json(path, value)
        study.frozen_plan(root, self.fx.plan_path)
        self.assertEqual(thinking_truncation_retry(root, self.fx.plan, parent), prior)
        value['previous_repair'] = {**prior, 'sha256': '0'*64}
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, 'repair chain changed'):
            study.frozen_plan(root, self.fx.plan_path)


class NativeContinuationInstallTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_source_patch_and_mismatched_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / 'package'
            (package / 'dist').mkdir(parents=True)
            executable = package / 'dist/cli.js'
            executable.write_text('#!/usr/bin/env node\n')
            executable.chmod(0o755)
            (root / 'bin').mkdir()
            (root / 'bin/pi').symlink_to(executable)
            relative = 'node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js'
            target = package / relative
            target.parent.mkdir(parents=True)
            target.write_text('before-anchor')
            before = file_hash(target)
            target.write_text('after-anchor')
            after = file_hash(target)
            target.write_text('before-anchor')
            write_json(root / 'plan.json', {})
            write_json(root / 'patch.json', {'path': relative, 'before_sha256': before, 'after_sha256': after,
                                          'replace_before': 'before-anchor', 'replace_after': 'after-anchor'})
            async def execute(command, **kwargs):
                program = shlex.split(command)[-1]
                env = {**os.environ, 'PATH': str(root / 'bin') + os.pathsep + os.environ['PATH']}
                result = subprocess.run([sys.executable, '-I', '-c', program], env=env, capture_output=True, text=True)
                return SimpleNamespace(return_code=result.returncode, stdout=result.stdout)
            environment = SimpleNamespace(exec=AsyncMock(side_effect=execute))
            repair = ({'path': 'repair.json', 'sha256': 'a'*64},
                      {'kind': 'pi_thinking_continuation', 'evidence': {'native_patch': {'path': 'patch.json'}}})
            with patch('runner.run_plan._file_ref', side_effect=lambda project, ref: root / ref['path']), \
                 patch('runner.run_plan.tool_repair_records', return_value=[repair]):
                receipt = await install_thinking_continuation(environment, {'formal': True, 'plan_ref': {'path': 'plan.json'}})
                self.assertEqual(receipt['after_sha256'], after)
                self.assertEqual(target.read_text(), 'after-anchor')
                target.write_text('unexpected installed source')
                with self.assertRaisesRegex(RuntimeError, 'source checks'):
                    await install_thinking_continuation(environment, {'formal': True, 'plan_ref': {'path': 'plan.json'}})

    async def test_multiple_native_transitions_are_applied_and_audited_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / 'package'
            (package / 'dist').mkdir(parents=True)
            executable = package / 'dist/cli.js'
            executable.write_text('#!/usr/bin/env node\n')
            executable.chmod(0o755)
            (root / 'bin').mkdir()
            (root / 'bin/pi').symlink_to(executable)
            loop = 'node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js'
            agent = 'node_modules/@earendil-works/pi-agent-core/dist/agent.js'
            def transition(relative, before, after):
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(after)
                after_sha = file_hash(target)
                target.write_text(before)
                return {'path': relative, 'before_sha256': file_hash(target), 'after_sha256': after_sha,
                        'replace_before': before, 'replace_after': after}
            second = transition(loop, 'middle', 'final')
            first = transition(loop, 'original', 'middle')
            third = transition(agent, 'before', 'after')
            write_json(root / 'plan.json', {})
            write_json(root / 'first.json', first)
            write_json(root / 'second.json', {'patches': [second, third]})
            async def execute(command, **kwargs):
                env = {**os.environ, 'PATH': str(root / 'bin') + os.pathsep + os.environ['PATH']}
                result = subprocess.run([sys.executable, '-I', '-c', shlex.split(command)[-1]],
                                        env=env, capture_output=True, text=True)
                return SimpleNamespace(return_code=result.returncode, stdout=result.stdout)
            environment = SimpleNamespace(exec=AsyncMock(side_effect=execute))
            records = [({'path': name}, {'kind': kind, 'evidence': {'native_patch': {'path': filename}}})
                       for name, kind, filename in [('prior', 'pi_thinking_continuation', 'first.json'),
                                                    ('next', 'pi_context_compaction_handoff', 'second.json')]]
            with patch('runner.run_plan._file_ref', side_effect=lambda project, ref: root / ref['path']), \
                 patch('runner.run_plan.tool_repair_records', return_value=records):
                result = await install_thinking_continuation(environment, {'formal': True, 'plan_ref': {'path': 'plan.json'}})
            self.assertEqual((package / loop).read_text(), 'final')
            self.assertEqual((package / agent).read_text(), 'after')
            self.assertEqual([r['path'] for r in result['patch_chain']], [loop, loop, agent])
            self.assertEqual([r['authorization']['path'] for r in result['patch_chain']], ['prior', 'next', 'next'])

    async def test_context_patch_cannot_target_other_native_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'plan.json', {})
            write_json(root / 'patch.json', {'patches': [{'path': 'dist/core/agent-session.js'}]})
            record = ({'path': 'repair.json'}, {'kind': 'pi_context_compaction_handoff',
                                              'evidence': {'native_patch': {'path': 'patch.json'}}})
            environment = SimpleNamespace(exec=AsyncMock())
            with patch('runner.run_plan._file_ref', side_effect=lambda project, ref: root / ref['path']), \
                 patch('runner.run_plan.tool_repair_records', return_value=[record]):
                with self.assertRaisesRegex(RuntimeError, 'unexpected native continuation patch target'):
                    await install_thinking_continuation(environment, {'formal': True, 'plan_ref': {'path': 'plan.json'}})
            environment.exec.assert_not_awaited()
