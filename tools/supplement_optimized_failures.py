"""User-requested post-hoc supplement; never rewrites the original nine sessions."""
import argparse
import asyncio
import copy
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runner import phase, run_plan
from runner.common import canonical, digest, file_hash, read_json, write_json
from runner.exploration import attempt_timeline
from runner.observed import observed_bccbbc
from runner.replay import prepare_judge, replay_single
from runner.study import (closed_research, completed_task, frozen_plan, ledger,
                          read_attempt, reference, score_checkpoints, session_spec,
                          start, validate_session)

TAG = 'optimized-r1-supplement-20261101'
OUT = ROOT / 'logs' / TAG
RESULTS = ROOT / 'results' / TAG
OLD = ROOT / 'freezes/research-run-plan-optimized-r1-20261101.json'
PLAN = ROOT / 'freezes' / ('research-run-plan-' + TAG + '.json')
DATA = ROOT / 'authoring/data/optimized-r1-20261101'
RESOURCE = ROOT / 'logs/optimized-r1-20261101/resource-acceptance/summary.json'
NAME = 'dcomp-demo-postgres'


def ref(path):
    return reference(ROOT, path)


def verify_original():
    manifest = ROOT / 'results/optimized-r1-20261101/delivery-manifest.json'
    rows = read_json(manifest)['files']
    for row in rows:
        path = ROOT / row['path']
        assert path.stat().st_size == row['bytes'] and file_hash(path) == row['sha256'], row['path']
    return {'status': 'passed', 'files_verified': len(rows), 'manifest': ref(manifest)}


def freeze():
    assert not OUT.exists() and not RESULTS.exists() and not PLAN.exists()
    prior, prior_ref = frozen_plan(ROOT, OLD)
    preservation = verify_original()
    original_ledger = read_json(ROOT / 'research-runs' / prior['plan_id'] / 'manifest.json')
    completed_task(ROOT, prior, original_ledger, 'ode')
    OUT.mkdir()
    RESULTS.mkdir()
    write_json(OUT / 'original-preservation-before.json', preservation)
    authorization = {
        'request': '有两组未成功，去补测一下',
        'targets': ['ODE G1 r1: new independent research', 'Poisson G2 r1: sealed-candidate timing recheck'],
        'new_scientific_sessions': 1, 'kind': 'user_requested_post_hoc_supplement',
        'original_nine_preserved': True, 'replaces_original_outcomes': False,
        'budgets': {'research_seconds': 1800, 'public_evaluations': 20, 'output_tokens': 200000, 'response_tokens': 16384},
        'native_context_compaction_retained': True,
        'blinding': 'Fresh ODE context and workspace; no previous solution, test results or failure diagnosis passed to the model.',
        'retry_policy': 'At most one linked API/infrastructure retry; no automatic rerun of legitimate failure.',
        'timing_policy': 'Frozen observer; at most 12 preflight windows and 3 BCCBBC measurements; first valid result.',
        'existing_service_authorization': 'Temporarily stop dcomp-demo-postgres and restore; ToDesk log child may be paused and restored if needed.',
        'limitation': 'Post-hoc supplement on the same frozen data, not a tenth sample of the original nine-session design.'}
    write_json(OUT / 'authorization.json', authorization)
    plan = copy.deepcopy(prior)
    # Only G1 is authorized. Reuse the previously validated G1-first template
    # ordering; dormant G2/G3 rows are never research samples in this supplement.
    template_entropy = '6530211a39e76371d187c67c2fd5f1a94ed2f44dc96d2cdee632cbdcaaa094ac'
    draft = run_plan.create_draft(ROOT, order_entropy=template_entropy,
        identity_revision='optimized-r1-posthoc-supplement-20261101', run_scope=[{'task': 'ode', 'repeat': 1}])
    order_draft = run_plan.create_draft(ROOT, order_entropy=template_entropy)
    write_json(OUT / 'unexecuted-order-draft.json', order_draft)
    for key in ('plan_id', 'runs', 'run_matrix_sha256', 'created_at', 'identity_revision', 'run_scope', 'order'):
        plan[key] = draft[key]
    assert plan['tool_config']['files'] == draft['tool_config']['files']
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    plan.update(study_kind='execution_template_for_single_ode_g1_posthoc_supplement',
                previous_plan=ref(OUT / 'unexecuted-order-draft.json'),
                revision_authorization=ref(OUT / 'authorization.json'), frozen_at=now)
    for task in phase.TASKS:
        frozen = copy.deepcopy(read_json(ROOT / prior['freezes'][task]['path']))
        frozen['research']['run_matrix_sha256'] = plan['run_matrix_sha256']
        frozen.update(frozen_at=now, previous_freeze=prior['freezes'][task],
                      revision_authorization=plan['revision_authorization'])
        frozen['limitations'] += ['Only ODE G1 is authorized in this supplemental template; other rows must remain dormant.']
        phase.validate_freeze_document(frozen, task)
        path = OUT / (task + '-freeze.json')
        write_json(path, frozen)
        plan['freezes'][task] = ref(path)
    plan['limitations'] = ['Unchanged executor validates a complete three-group template; the independent protocol authorizes only ODE G1.',
                          'Single-session closure adapter uses unchanged replay guards and scoring.',
                          'Original nine outcomes remain unchanged; this is explicitly post-hoc.']
    run_plan.validate_start(plan, ROOT)
    write_json(PLAN, plan)
    row = next(r for r in plan['runs'] if r['group'] == 'g1')
    assert row == plan['runs'][0], 'Single authorized session must be first in the template'
    spec = session_spec(ROOT, PLAN, row['run_id'], row['run_id'] + '-a001')
    validate_session(spec)
    for key in ('model', 'runtime_policy', 'tool_config', 'resources', 'tasks', 'research_images', 'execution_policy'):
        assert plan[key] == prior[key], key
    assert spec['settings']['request_output_limit'] == 16384 and spec['settings']['budget_reminders']
    p_row = next(r for r in prior['runs'] if (r['task'], r['group']) == ('poisson', 'g2'))
    p_entry = next(e for e in original_ledger['attempts'] if e['run_id'] == p_row['run_id'])
    registry, state = closed_research(ROOT, p_entry, p_row)
    assert state['first_id'] == state['final_id'] == 'candidate-001'
    source = registry.verified_snapshot(state['final_id'])
    source_hash = digest(canonical(phase.checked_hashes(source)))
    assert source_hash == '7b2f4b5d137f147ff2551a5c0679a825d3098aae1d411b788836f20b227894fa'
    protocol = {'status': 'frozen', 'kind': 'post_hoc_two_failure_supplement', 'frozen_at': now,
                'authorization': ref(OUT / 'authorization.json'), 'template': ref(PLAN),
                'authorized_runs': [row], 'dormant_template_run_ids': [r['run_id'] for r in plan['runs'] if r != row],
                'original_plan': prior_ref, 'original_delivery': preservation['manifest'],
                'prelaunch_validation_refusal': ref(ROOT / 'archives/pre-supplement-launch-fix-20261101/failure.json'),
                'controller': ref(Path(__file__)), 'new_scientific_sessions': 1,
                'poisson': {'row': p_row, 'entry': p_entry, 'source_hash': source_hash,
                            'parent_replay': p_entry['replay'], 'new_model_calls': 0},
                'scoring_order': ['close authorized ODE research', 'ODE first/final main replay 3x',
                                  'ODE final diagnostic replay', 'Poisson fixed-candidate BCCBBC'],
                'max_timing_attempts': 3, 'max_admission_windows': 12}
    write_json(OUT / 'protocol.json', protocol)
    write_json(OUT / 'validation.json', {'status': 'passed', 'protocol': ref(OUT / 'protocol.json'),
                'identical_frozen_settings': True, 'only_one_authorized_session': True,
                'original_files_verified': preservation['files_verified']})
    print(json.dumps({'status': 'frozen', 'run_id': row['run_id'], 'sessions': 1}))


def record(stage, **details):
    row = {'stage': stage, 'updated_at': time.time(), 'pid': os.getpid(), **details}
    write_json(OUT / 'state.json', row)
    print(json.dumps(row), flush=True)


def idle():
    assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip(), 'Unexpected running container'


def service_state():
    value = json.loads(subprocess.check_output(['docker', 'inspect', '--format', '{{json .State}}', NAME], text=True))
    return {k: value.get(k) for k in ('Status', 'Running', 'StartedAt', 'FinishedAt')} | {'health': value.get('Health', {}).get('Status')}


def resource_reuse(plan):
    resource = read_json(RESOURCE)
    machine = subprocess.check_output(['colima', 'ssh', '--', 'cat', '/proc/sys/kernel/random/boot_id'], text=True).strip()
    info = json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .}}'], text=True))
    assert machine == resource['machine_id'] and resource['formal_resources_accepted']
    assert info['NCPU'] == resource['capacity']['actual_vcpu'] and info['MemTotal'] == resource['capacity']['actual_memory_bytes']
    assert info['CgroupVersion'] == '2' and info['SwapLimit']
    for image in (resource['numeric_image_id'], plan['research_images']['ode']['image_id']):
        assert subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True).strip() == image
    write_json(OUT / 'resource-reuse.json', {'status': 'verified_same_boot', 'resource_evidence': ref(RESOURCE),
               'machine_id': machine, 'live_docker': {k: info[k] for k in ('NCPU', 'MemTotal', 'CgroupVersion', 'KernelVersion', 'Architecture', 'SwapLimit')}})


def score_ode(protocol, plan, row):
    with ledger(ROOT, plan, protocol['template']) as (manifest_path, manifest):
        assert manifest['attempts'] and all(e['run_id'] == row['run_id'] for e in manifest['attempts'])
        entry = manifest['attempts'][-1]
        assert not manifest['finalized_tasks'] and not entry.get('replay_started_at')
        registry, state = closed_research(ROOT, entry, row)
        write_json(OUT / 'research-closure.json', {'status': 'passed', 'authorized_sessions': 1,
            'all_authorized_sessions_closed': True, 'dormant_sessions_launched': 0, 'closed_at': time.time(),
            'hidden_scoring_started': False, 'protocol': ref(OUT / 'protocol.json'), 'entry': entry})
        frozen = run_plan._file_ref(ROOT, plan['freezes']['ode'])
        freeze_doc = read_json(frozen)
        output = RESULTS / 'ode'
        judge = prepare_judge(ROOT, output / 'judge-source')
        assert phase.checked_hashes(judge) == freeze_doc['judge_source_hashes']
        manifest.update(finalized_tasks=['ode'], single_session_protocol=ref(OUT / 'protocol.json'),
                        dormant_template_run_ids=protocol['dormant_template_run_ids'])
        entry['replay_started_at'] = time.time()
        write_json(manifest_path, manifest)
        config = dict(task='ode', input_root=DATA / 'inputs/ode/final-test', truth_root=DATA / 'private/ode/final-test',
            output_root=output / 'main', image=freeze_doc['image_id'], judge_source_root=judge,
            freeze_path=frozen, profile=freeze_doc['profile'])
        phase.guard_replay('ode', config['input_root'], config['truth_root'], config['image'], judge,
                           freeze_path=frozen, profile=freeze_doc['profile'])
        wrapper = {'formal': True, 'split': 'final-test', 'scope': 'post_hoc_single_session_supplement',
                   'run_id': row['run_id'], 'attempt_id': entry['attempt_id'], 'protocol': ref(OUT / 'protocol.json'),
                   'registry': entry['registry'], 'freeze': plan['freezes']['ode'],
                   'diagnostics': score_checkpoints(registry, state, config)}
        write_json(output / 'main-result.json', wrapper)
        entry['replay'] = ref(output / 'main-result.json')
        write_json(manifest_path, manifest)
        registered = next((r for r in state['evaluations'] if r['id'] == state['final_id']), None)
        diag = {'diagnostic_only': True, 'excluded_from_main_score': True, 'candidate_id': state['final_id']}
        if not registered or not registered.get('artifact_valid'):
            diag.update(status='no_valid_candidate', passed=0, total=12)
        else:
            source = registry.verified_snapshot(state['final_id'])
            diag.update(status='evaluated', source_hash=registered['source_hash'], result=replay_single(source,
                task='ode', input_root=DATA / 'inputs/ode/diagnostic-test', truth_root=DATA / 'private/ode/diagnostic-test',
                output_root=output / 'diagnostic', image=freeze_doc['image_id'], judge_source_root=judge, freeze_path=frozen))
            registry.verified_snapshot(state['final_id'])
        write_json(output / 'diagnostic-result.json', diag)
        run_plan._file_ref(ROOT, entry['registry'])
        run_plan.validate_start(plan, ROOT)
        timeline = attempt_timeline((ROOT / entry['registry']['path']).parent.parent)
        write_json(RESULTS / 'exploration-timeline.json', {'scientific_sessions': 1, 'run_id': row['run_id'], **timeline})
        return {'main': ref(output / 'main-result.json'), 'diagnostic': ref(output / 'diagnostic-result.json'),
                'score': wrapper['diagnostics']['score'], 'reward': wrapper['diagnostics']['reward']}


def score_poisson(protocol):
    prior, _ = frozen_plan(ROOT, OLD)
    old_ledger = read_json(ROOT / 'research-runs' / prior['plan_id'] / 'manifest.json')
    completed_task(ROOT, prior, old_ledger, 'poisson')
    item = protocol['poisson']
    registry, state = closed_research(ROOT, item['entry'], item['row'])
    source = registry.verified_snapshot(state['final_id'])
    assert digest(canonical(phase.checked_hashes(source))) == item['source_hash']
    frozen = run_plan._file_ref(ROOT, prior['freezes']['poisson'])
    freeze_doc = read_json(frozen)
    output = RESULTS / 'poisson'
    judge = prepare_judge(ROOT, output / 'judge-source')
    assert phase.checked_hashes(judge) == freeze_doc['judge_source_hashes']
    value = observed_bccbbc(source, resource_path=RESOURCE, baseline_source=ROOT / 'baselines/poisson',
        output_root=output / 'timing', task='poisson', input_root=DATA / 'inputs/poisson/final-test',
        truth_root=DATA / 'private/poisson/final-test', image=freeze_doc['image_id'], judge_source_root=judge,
        freeze_path=frozen, profile=freeze_doc['profile'])
    registry.verified_snapshot(state['final_id'])
    wrapper = {'formal': True, 'split': 'final-test', 'scope': 'post_hoc_sealed_candidate_timing_supplement',
        'new_scientific_sessions': 0, 'new_model_calls': 0, 'protocol': ref(OUT / 'protocol.json'),
        'source_hash': item['source_hash'], 'parent_replay': item['parent_replay'], 'result': value}
    write_json(output / 'result.json', wrapper)
    return {'result': ref(output / 'result.json'), 'score': value['score'], 'reward': value['reward'],
            'speedup': value['speedup'], 'performance_status': value['performance_status']}


def run():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    protocol = read_json(OUT / 'protocol.json')
    for item in (protocol['controller'], protocol['authorization'], protocol['template'], protocol['original_delivery']):
        run_plan._file_ref(ROOT, item)
    plan, plan_ref = frozen_plan(ROOT, PLAN)
    assert plan_ref == protocol['template']
    row, = protocol['authorized_runs']
    assert row in plan['runs'] and (row['task'], row['group']) == ('ode', 'g1')
    manifest_path = ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json'
    assert not manifest_path.exists(), 'Never silently restart this supplement'
    resource_reuse(plan)
    service = {'container': NAME, 'before': service_state(), 'restored': False, 'started_at': time.time()}
    write_json(OUT / 'service-restoration.json', service)
    names = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True).splitlines()
    assert set(names).issubset({NAME})
    result = {'protocol': ref(OUT / 'protocol.json'), 'new_scientific_sessions': 1, 'original_nine_unchanged': True}
    try:
        if service['before']['Running']:
            subprocess.run(['docker', 'stop', NAME], check=True, stdout=subprocess.DEVNULL)
        idle()
        record('ode_research_running', run_id=row['run_id'], attempt=1)
        value = asyncio.run(start(ROOT, PLAN, row['run_id']))
        if value['attempt_status'] in {'api_failed', 'infrastructure_failed'}:
            parent = read_json(manifest_path)['attempts'][-1]['attempt_id']
            record('ode_linked_infrastructure_retry', parent=parent)
            idle()
            value = asyncio.run(start(ROOT, PLAN, row['run_id'], retry_of=parent))
        idle()
        if value['attempt_status'] in {'completed', 'research_timeout'}:
            record('ode_scoring_running', run_id=row['run_id'])
            result['ode'] = score_ode(protocol, plan, row)
        else:
            result['ode'] = {'status': value['attempt_status'], 'score': None, 'reward': None}
            write_json(OUT / 'research-closure.json', {'status': 'infrastructure_exhausted', 'finished_at': value.get('finished_at'),
                'model_stopped': value.get('research_stop_returncode') == 0, 'cleanup_errors': value.get('cleanup_errors')})
            assert not value.get('cleanup_errors') and not value.get('bridge_errors')
        write_json(RESULTS / 'results.json', result | {'status': 'ode_closed'})
        idle()
        record('poisson_timing_running', run_id=protocol['poisson']['row']['run_id'])
        result['poisson'] = score_poisson(protocol)
        idle()
        write_json(RESULTS / 'results.json', result | {'status': 'measurements_closed'})
        write_json(OUT / 'original-preservation-after.json', verify_original())
        record('results_ready_for_review')
    except BaseException as exc:
        record('stopped', error=type(exc).__name__ + ': ' + str(exc)[:1500])
        raise
    finally:
        if service['before']['Running']:
            subprocess.run(['docker', 'start', NAME], check=True, stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + 60
        while True:
            after = service_state()
            if after['health'] != 'starting' or time.monotonic() >= deadline:
                break
            time.sleep(2)
        service.update(after=after, restored=after['Running'] == service['before']['Running'] and after['health'] in (None, 'healthy'), finished_at=time.time())
        write_json(OUT / 'service-restoration.json', service)
        assert service['restored'], 'Database did not restore'


def launch():
    assert not (OUT / 'process.json').exists()
    assert os.environ.get('ANTHROPIC_AUTH_TOKEN'), 'Expected configured model credential'
    assert read_json(OUT / 'validation.json')['status'] == 'passed'
    env = os.environ.copy()
    env.update(PYTHONPATH=str(ROOT), LITELLM_LOCAL_MODEL_COST_MAP='True')
    with (OUT / 'controller.stdout.log').open('xb') as stream:
        process = subprocess.Popen(['/usr/bin/caffeinate', '-dimsu', sys.executable, str(Path(__file__)), 'run'],
            cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True)
    write_json(OUT / 'process.json', {'pid': process.pid, 'started_at': time.time(), 'controller': ref(Path(__file__)),
               'new_scientific_sessions': 1, 'request_output_limit': 16384, 'sleep_inhibited': True})
    print(json.dumps({'status': 'launched', 'pid': process.pid}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['freeze', 'launch', 'run'])
    globals()[parser.parse_args().action]()
