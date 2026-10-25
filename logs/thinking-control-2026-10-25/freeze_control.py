"""Freeze a fresh, matched 15-session thinking/max control; retain prior study."""
import copy
import datetime
import json
from pathlib import Path
import shutil
import subprocess

from runner import phase, run_plan
from runner.common import canonical, digest, file_hash, read_json, write_json
from runner.model_relay import Limits
from runner.study import session_spec

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / 'freezes/research-run-plan-formal-003.json'
NEW = ROOT / 'freezes/research-run-plan-thinking-max-2026-10-25.json'


def ref(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': file_hash(path)}


def evidence(name, value):
    path = OUT / (name + '.json')
    assert not path.exists(), path
    write_json(path, value)
    return ref(path)


def main():
    assert not NEW.exists()
    old = read_json(PRIOR)
    live = read_json(OUT / 'live-smoke-result.json')
    reasoning = read_json(OUT / 'live-reasoning-roundtrip/result.json')
    assert live['status'] == reasoning['status'] == 'passed'
    assert reasoning['cleanup']['all_removed'] and reasoning['native']['records'][0]['thinkingChars'] > 0
    assert '363 passed' in (OUT / 'unit-tests-final.txt').read_text()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    authorization = ref(OUT / 'authorization.json')
    draft = run_plan.create_draft(ROOT, order_entropy=old['order']['entropy_hex'], identity_revision='thinking-max-200k-001')
    assert draft['tasks'] == old['tasks'] and draft['resources'] == old['resources']
    plan = copy.deepcopy(old)
    for key in ('plan_id', 'runs', 'run_matrix_sha256', 'created_at', 'identity_revision'):
        plan[key] = draft[key]
    for key in ('previous_attempts', 'predecessor_close', 'previous_failed_attempts'):
        plan.pop(key, None)
    plan.update(previous_plan=ref(PRIOR), revision_authorization=authorization, study_kind='matched_thinking_max_control')
    plan['tool_config']['files'] = draft['tool_config']['files']
    plan['tool_config_sha256'] = digest(canonical(plan['tool_config']))
    changed = {p: {'old': h, 'new': plan['tool_config']['files'].get(p)} for p, h in old['tool_config']['files'].items()
               if plan['tool_config']['files'].get(p) != h}
    assert set(changed) == {'runner/file_bridge.py', 'runner/harbor_pilot.py', 'runner/model_relay.py',
                            'runner/registry.py', 'runner/relay_transport.py', 'runner/run_plan.py', 'runner/study.py'}
    scientific = [p for p in old['tool_config']['files'] if p.startswith(('judge/', 'baselines/', 'public/'))
                  or p in ('runner/worker.py', 'runner/common.py', 'runner/artifact_gate.py', 'runner/phase.py',
                           'runner/replay.py', 'runner/performance.py', 'runner/process_timer.py')]
    assert all(file_hash(ROOT / p) == old['tool_config']['files'][p] for p in scientific)
    impact = evidence('revision-impact', {'status': 'passed', 'changed_trusted_files': changed,
        'added_trusted_files': sorted(set(plan['tool_config']['files']) - set(old['tool_config']['files'])),
        'numerical_and_public_sources_unchanged': scientific,
        'historical_nullable_budget_support': 'Prior file_bridge/registry/supplemental changes retained; this control uses original non-null 1800s/20-evaluation limits.',
        'new_changes': 'Thinking/max wire enforcement, allowed thinking/signature SSE, and verified native-session policy. Default disabled mode unchanged.',
        'same': ['15 conditions/order', '200000 total output tokens', '4096 output tokens/request', '1800 research seconds',
                 '20 public evaluations', 'data', 'prompts', 'images', 'resources', 'scientific scores'],
        'temperature': 'Original effective 0; thinking mode unsupported, omitted and recorded as null.',
        'scope': 'Post-hoc matched comparison on previously used hidden data, not randomized causal identification or fresh held-out validation.'})
    provider = ref(OUT / 'provider-documentation.json')
    enforcement = evidence('model-enforcement', {'status': 'verified', 'thinking': {'type': 'enabled'},
        'output_config': {'effort': 'max'}, 'temperature': None, 'top_p': 1.0,
        'request_output_limit': 4096, 'session_output_limit': 200000, 'max_requests': 3125,
        'native_live': ref(OUT / 'live-smoke-result.json'), 'nonempty_thinking_and_tool_continuation': ref(OUT / 'live-reasoning-roundtrip/result.json'),
        'tests': ref(OUT / 'unit-tests-final.txt'), 'provider_documentation': provider,
        'evidence_scope': 'Actual normalized request policy and returned thinking. Provider internal effort is not independently measurable.',
        'accounting': 'All provider-reported output tokens including thinking and native compaction share the session limit; failed requests reserve their full effective allowance.'})
    model = plan['model']
    model.update(thinking={'type': 'enabled'}, output_config={'effort': 'max'}, temperature=None)
    model['enforcement'] = {k: {'status': 'verified', 'evidence': enforcement} for k in (*run_plan.PARAMETERS, 'output_config')}
    model['enforcement']['temperature'] = {'status': 'unsupported', 'reason': 'DeepSeek documents temperature as ineffective in thinking mode; omit the field.', 'evidence': provider}
    model['version_resolution'] = {'status': 'verified', 'evidence': provider,
        'scope': 'Provider-declared alias mapping rechecked for this control; not an immutable backend identity.',
        'on_documented_alias_drift': 'Stop before further sessions and create a new protocol.'}
    policy = read_json(ROOT / plan['tool_config']['runtime_enforcement']['path'])
    plan['runtime_policy'] = Limits(session_seconds=2700, session_output_limit=200000, max_requests=3125, thinking_effort='max',
        expected_system_sha256=policy['wire_system_sha256'], expected_tools_sha256=policy['wire_tools_sha256'],
        expected_compaction_system_sha256=policy['native_compaction']['wire_system_sha256']).public()
    scorer = evidence('scorer-tests', {'status': 'passed', 'unit_tests_passed': 363, 'unit_test_log': ref(OUT / 'unit-tests-final.txt'),
        'trusted_source_hashes': plan['tool_config']['files'],
        'test_source_hashes': {p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted((ROOT / 'tests').glob('test_*.py'))}})
    resource = read_json(ROOT / 'logs/resource-acceptance-local-002/summary.json')
    machine = subprocess.check_output(['colima', 'ssh', '--', 'cat', '/proc/sys/kernel/random/boot_id'], text=True).strip()
    info = json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .}}'], text=True))
    assert machine == resource['machine_id'] and info['NCPU'] >= 6 and info['MemTotal'] >= 8.5 * 1024**3
    assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip()
    for image in (resource['numeric_image_id'], *(r['image_id'] for r in old['research_images'].values())):
        assert subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip() == image
    environment = evidence('environment-inspection', {'status': 'verified', 'observed_at_utc': now, 'vm_boot_id': machine,
        'docker': {k: info[k] for k in ('NCPU', 'MemTotal', 'CgroupVersion', 'KernelVersion', 'Architecture')},
        'running_containers': [], 'power': subprocess.check_output(['pmset', '-g', 'batt'], text=True)})
    resources = evidence('resources', {'status': 'passed', 'formal_resources_accepted': True, 'resources': phase.RESOURCES,
        'prior_acceptance': ref('logs/resource-acceptance-local-002/summary.json'), 'current_environment': environment,
        'scope': 'Same VM, images and resource contract; prior stress probes retained. Poisson still needs a fresh observed timing window.'})
    for task in phase.TASKS:
        prior = read_json(ROOT / old['freezes'][task]['path'])
        frozen = copy.deepcopy(prior)
        frozen.update(frozen_at=now, previous_freeze=old['freezes'][task], revision_authorization=authorization)
        checks = copy.deepcopy(old['acceptance_evidence'][task])
        checks.update(scorer_tests=scorer, resources=resources)
        checks['model_smoke'] = evidence(task + '-model-smoke', {'status': 'passed', 'live_smoke': ref(OUT / 'live-smoke-result.json'),
            'nonempty_thinking': ref(OUT / 'live-reasoning-roundtrip/result.json'),
            'unchanged_task_wire_policy': ref('logs/model-policy-capture-compaction-local-003/' + task + '/policy.json'),
            'research_image_unchanged': old['research_images'][task], 'revision_impact': impact})
        frozen['acceptance'] = {k: {'status': 'passed', 'evidence_sha256': v['sha256']} for k, v in checks.items()}
        frozen['research'].update(temperature=None, reasoning_configuration=model['thinking'], output_config=model['output_config'],
            model_version_resolution=model['version_resolution'], model_parameter_enforcement=model['enforcement'],
            tool_config_sha256=plan['tool_config_sha256'], run_matrix_sha256=plan['run_matrix_sha256'])
        frozen['limitations'] = ['Fresh thinking/max control, same 200k output and original time/evaluation limits.',
            'Previously used hidden data; prior outcome is retained, not replaced.', 'Fresh observed timing is required for Poisson.']
        for key in ('data', 'data_sha256', 'thresholds', 'resources', 'dependencies', 'profile', 'image_id', 'judge_source_hashes', 'judge_sha256'):
            assert frozen[key] == prior[key]
        phase.validate_freeze_document(frozen, task)
        path = ROOT / f'freezes/{task}-thinking-max-2026-10-25.json'
        assert not path.exists()
        write_json(path, frozen)
        plan['freezes'][task] = ref(path)
        plan['acceptance_evidence'][task] = checks
    plan.update(frozen_at=now, revision_impact=impact, prior_result_handling='Preserve original results; report new control separately and pair task/group/repeat.')
    plan['limitations'] = ['Same already-used hidden set and sequential rather than randomized condition execution.',
        'Thinking and max effort change together; temperature is unsupported in thinking mode.',
        'Native Pi defaults remain off; the trusted relay enforces enabled/max on every upstream request, including compaction.',
        'Provider alias mapping is not immutable backend identity. Invalid timing and failed attempts remain visible.']
    run_plan.validate_start(plan, ROOT)
    write_json(NEW, plan)
    for row in plan['runs']:
        settings = session_spec(ROOT, NEW, row['run_id'], row['run_id'] + '-a001')['settings']
        assert settings['thinking_effort'] == 'max' and settings['session_output_limit'] == 200000
    paths = set(plan['tool_config']['files']) | {p.relative_to(ROOT).as_posix() for p in (ROOT / 'tests').glob('test_*.py')}
    snapshot = {}
    for name in sorted(paths):
        target = OUT / 'source-snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        snapshot[name] = file_hash(target)
    evidence('source-snapshot-manifest', {'files': snapshot})
    evidence('validation', {'status': 'passed', 'formal_ready': True, 'blockers': [], 'plan': ref(NEW),
        'all_15_specs_validated': True, 'formal_sessions_started': 0, 'final_test_scores_accessed': False})
    print(json.dumps({'status': 'frozen', 'plan_id': plan['plan_id'], 'sessions': 15, 'plan': ref(NEW)}))


if __name__ == '__main__':
    main()
