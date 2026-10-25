"""User-authorized new timing observations of two closed, immutable candidates.

Keeps the original research ledger and every old score/refusal unchanged. Uses
the frozen scoring functions, BCCBBC order, resources and revision-3 observer.
At most three admission-only windows per run; one admitted measurement per run.
No model transport, research launcher, or scientific retry is called.
"""
import argparse
import datetime
import json
from pathlib import Path
import runpy
import subprocess
import threading
import time

from runner.common import file_hash, read_json, write_json
from runner.phase import RESOURCES, checked_hashes, guard_replay
from runner.replay import prepare_judge, replay_checkpoint, replay_single
from runner.study import closed_research, completed_task, frozen_plan, score_checkpoints
from runner.worker import docker

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PLAN = ROOT / 'freezes/research-run-plan-thinking-max-2026-10-25.json'
PLAN_ID = 'research-98719c3c1cf3fc92'
LEDGER = ROOT / 'research-runs' / PLAN_ID / 'manifest.json'
OBSERVER_SOURCE = ROOT / 'tests/accepted_t3_calibration.py'
MODULE = runpy.run_path(str(OBSERVER_SOURCE))
Observer, POLICY = MODULE['Observer'], MODULE['POLICY']


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': file_hash(path)}


def preflight_bindings():
    plan, plan_ref = frozen_plan(ROOT, PLAN)
    assert plan_ref['sha256'] == '25c3250f8615aa5a90a24206964533085b5448f06910f7e42a969e2f66763f0e'
    manifest = read_json(LEDGER)
    for task in ('heat', 'ode', 'poisson'):
        completed_task(ROOT, plan, manifest, task)
    assert 'poisson' in manifest['finalized_tasks']
    assert file_hash(OBSERVER_SOURCE) == file_hash(ROOT / 'logs/t3-formal-calibration-local-005/controller.py')
    selected = []
    for group in ('g1', 'g2'):
        run_id = f'{PLAN_ID}-poisson-{group}-r1'
        entry = [e for e in manifest['attempts'] if e['run_id'] == run_id][-1]
        row = next(r for r in plan['runs'] if r['run_id'] == run_id)
        registry, state = closed_research(ROOT, entry, row)
        old = ROOT / f'logs/thinking-control-2026-10-25/window-final-poisson-{run_id}/acceptance.json'
        assert read_json(old)['status'] in ('host_preflight_rejected', 'rejected')
        selected.append({'run_id': run_id, 'group': group, 'attempt_id': entry['attempt_id'],
                         'registry': entry['registry'], 'host_attempt': entry['result'],
                         'parent_refusal': ref(old), 'parent_replay': entry.get('replay'),
                         'first_id': state['first_id'], 'final_id': state['final_id'],
                         'source_hashes': {role: next(e['source_hash'] for e in state['evaluations']
                              if e['id'] == state[role + '_id']) for role in ('first', 'final')}})
    return plan, selected


def one_window(plan, item, number):
    out = OUT / f"{item['group']}-window-{number:03d}"
    out.mkdir(exist_ok=False)
    (out / 'controller.py').write_bytes(Path(__file__).read_bytes())
    (out / 'accepted-observer.py').write_bytes(OBSERVER_SOURCE.read_bytes())
    write_json(out / 'observation-policy.json', POLICY)
    resource_path = ROOT / 'logs/resource-acceptance-local-002/summary.json'
    resource = read_json(resource_path)
    assert resource['formal_resources_accepted'] is True and resource['resources'] == RESOURCES
    assert not docker('ps', '-q').stdout.strip()
    machine = subprocess.check_output(['colima', 'ssh', '--', 'cat', '/proc/sys/kernel/random/boot_id'], text=True).strip()
    assert machine == resource['machine_id']
    info = json.loads(docker('info', '--format', '{{json .}}').stdout)
    write_json(out / 'docker-before.json', {k: info[k] for k in ('NCPU', 'MemTotal', 'CgroupVersion', 'KernelVersion', 'Architecture', 'OperatingSystem')})
    (out / 'thermal-before.txt').write_text(subprocess.check_output(['pmset', '-g', 'therm'], text=True))
    observer = Observer(out / 'host-observations.jsonl')
    observer.sample()
    thread = threading.Thread(target=observer.watch, daemon=True)
    thread.start()
    result = {'status': 'starting', 'run_id': item['run_id'], 'window': number,
              'model_calls': 0, 'research_launches': 0, 'final_test_scores_accessed': False,
              'parent_refusal': item['parent_refusal'], 'parent_replay': item['parent_replay']}
    print(json.dumps({'stage': 'quiet_preflight', 'run_id': item['run_id'], 'window': number}), flush=True)
    try:
        started = time.time()
        time.sleep(POLICY['preflight_seconds'])
        observer.sample()
        violations = observer.violations_since(started)
        if violations or observer.errors:
            result.update(status='host_preflight_rejected', violations=violations, observer_errors=list(observer.errors))
            return result
        window_start = time.time()
        exclusive = {'status': 'passed', 'machine_exclusive_verified': True, 'machine_id': machine,
                     'other_host_workloads': [], 'cache_state': POLICY['cache_policy'],
                     'measurement_window_unix': [window_start, window_start + 1800],
                     'scope': 'New user-authorized observation of the existing closed candidate; original evidence retained.',
                     'observer_policy': {'path': 'observation-policy.json', 'sha256': file_hash(out / 'observation-policy.json')},
                     'quiet_preflight_seconds': POLICY['preflight_seconds'], 'continuous_observation_required': True}
        write_json(out / 'exclusive-window.json', exclusive)
        contract = {'status': 'frozen', 'resources': RESOURCES, 'image_id': resource['numeric_image_id'],
                    'resource_evidence': {'path': str(resource_path), 'sha256': file_hash(resource_path)},
                    'exclusivity_evidence': {'path': 'exclusive-window.json', 'sha256': file_hash(out / 'exclusive-window.json')}}
        contract_path = out / 'timing-contract.json'
        write_json(contract_path, contract)

        def measured(*args, **kwargs):
            row = replay_single(*args, **kwargs)
            observer.sample()
            bad = observer.violations_since(window_start)
            if bad or observer.errors:
                row.update(evaluation_status='evaluation_invalid', score=None, reward=None,
                           host_window_violations=bad, observer_errors=list(observer.errors))
            return row

        def checkpoint(*args, **kwargs):
            row = replay_checkpoint(*args, execute=measured, **kwargs)
            time.sleep(POLICY['sample_interval_seconds'])
            observer.sample()
            bad = observer.violations_since(window_start)
            if bad or observer.errors:
                row.update(evaluation_status='evaluation_invalid', performance_status='invalid_environment',
                           score=None, reward=None, speedup=None, formal_timing=False,
                           formal_environment_qualified=False, formal_evidence_valid=False,
                           retry_permitted=False, host_window_violations=bad, observer_errors=list(observer.errors))
                write_json(Path(kwargs['output_root']) / 'result.json', row)
            print(json.dumps({'stage': 'checkpoint_finished', 'run_id': item['run_id'],
                              'checkpoint_id': args[1], 'evaluation_status': row.get('evaluation_status')}), flush=True)
            return row

        # Same closure, snapshot, judge, data and freeze checks as study.final,
        # but write into this new observation directory, never its old ledger.
        manifest = read_json(LEDGER)
        latest = completed_task(ROOT, plan, manifest, 'poisson')
        entry = latest[item['run_id']]
        row = next(r for r in plan['runs'] if r['run_id'] == item['run_id'])
        registry, state = closed_research(ROOT, entry, row)
        freeze_path = ROOT / plan['freezes']['poisson']['path']
        freeze = read_json(freeze_path)
        judge = prepare_judge(ROOT, out / 'judge-source')
        assert checked_hashes(judge) == freeze['judge_source_hashes']
        data = ROOT / 'authoring/data/v0.3-local'
        config = {'task': 'poisson', 'input_root': data / 'inputs/poisson/final-test',
                  'truth_root': data / 'private/poisson/final-test', 'output_root': out / 'replays',
                  'image': freeze['image_id'], 'judge_source_root': judge, 'freeze_path': freeze_path,
                  'profile': freeze['profile'], 'baseline_source': ROOT / 'baselines/poisson',
                  'timing_contract': contract_path}
        guard_replay('poisson', config['input_root'], config['truth_root'], config['image'], judge,
                     freeze_path=freeze_path, profile=freeze['profile'])
        result['final_test_scores_accessed'] = True
        print(json.dumps({'stage': 'measurement_started', 'run_id': item['run_id']}), flush=True)
        diagnostics = score_checkpoints(registry, state, config, execute=checkpoint)
        frozen_plan(ROOT, PLAN)
        assert file_hash(ROOT / entry['registry']['path']) == entry['registry']['sha256']
        value = {'formal': True, 'split': 'final-test', 'kind': 'authorized_independent_timing_recheck',
                 'independent_research_sample': False, 'run_id': item['run_id'], 'attempt_id': item['attempt_id'],
                 'plan': ref(PLAN), 'freeze_sha256': plan['freezes']['poisson']['sha256'],
                 'registry_sha256': entry['registry']['sha256'], 'parent_refusal': item['parent_refusal'],
                 'parent_replay': item['parent_replay'], 'authorization': ref(OUT / 'authorization.json'),
                 'diagnostics': diagnostics}
        write_json(out / 'operation-result.json', value)
        observer.sample()
        violations = observer.violations_since(window_start)
        (out / 'thermal-after.txt').write_text(subprocess.check_output(['pmset', '-g', 'therm'], text=True))
        clean = not docker('ps', '-q').stdout.strip()
        valid = diagnostics['evaluation_status'] == 'valid'
        result.update(status='passed' if valid and clean and not violations and not observer.errors else 'rejected',
                      evaluation_status=diagnostics['evaluation_status'], violations=violations,
                      observer_errors=list(observer.errors), no_running_containers=clean,
                      operation_result=ref(out / 'operation-result.json'))
        return result
    except BaseException as exc:
        result.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        observer.stop.set()
        thread.join(timeout=10)
        result.update(completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      host_observations_sha256=file_hash(observer.path))
        write_json(out / 'acceptance.json', result)
        print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    plan, selected = preflight_bindings()
    if args.validate_only:
        print(json.dumps({'status': 'validated', 'selected': selected, 'model_calls': 0,
                          'research_launches': 0, 'scoring_calls': 0}, indent=2))
        return
    preserved = read_json(OUT / 'preserved-files.json')['files']
    assert all(file_hash(ROOT / n) == h for n, h in preserved.items())
    outcomes = []
    for item in selected:
        for number in range(1, 4):
            outcome = one_window(plan, item, number)
            outcomes.append(outcome)
            write_json(OUT / 'outcomes.json', {'outcomes': outcomes})
            if outcome['status'] != 'host_preflight_rejected':
                break
    assert all(file_hash(ROOT / n) == h for n, h in preserved.items())
    write_json(OUT / 'completion.json', {'status': 'measurements_closed', 'model_calls': 0,
               'research_launches': 0, 'original_files_unchanged': len(preserved), 'outcomes': outcomes,
               'all_two_passed': sum(o['status'] == 'passed' for o in outcomes) == 2})


if __name__ == '__main__':
    main()
