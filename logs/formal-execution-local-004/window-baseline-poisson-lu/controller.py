"""Fresh continuous host observation around one frozen Poisson final operation.

Uses the accepted revision-3 observer and existing study/replay APIs. No frozen
source, plan, solver, threshold, sample order, or historical evidence is edited.
"""
import argparse
import datetime
import json
import runpy
import subprocess
import threading
import time
from pathlib import Path

from runner.common import file_hash, read_json, write_json
from runner.phase import RESOURCES
from runner.replay import replay_checkpoint, replay_single
from runner.study import baseline, completed_task, final, frozen_plan
from runner.worker import docker

ROOT = Path(__file__).resolve().parents[2]
OBSERVER_SOURCE = ROOT / 'tests/accepted_t3_calibration.py'
observer_module = runpy.run_path(str(OBSERVER_SOURCE))
Observer, POLICY = observer_module['Observer'], observer_module['POLICY']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['baseline', 'final'], required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan_path = ROOT / 'freezes/research-run-plan-formal-003.json'
    plan, _ = frozen_plan(ROOT, plan_path)
    manifest = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')
    for task in ('heat', 'ode', 'poisson'):
        completed_task(ROOT, plan, manifest, task)
    assert file_hash(OBSERVER_SOURCE) == file_hash(ROOT / 'logs/t3-formal-calibration-local-005/controller.py')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
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
    result = {'status': 'starting', 'kind': args.kind, 'identity': args.identity,
              'model_calls': 0, 'final_test_scores_accessed': False}
    try:
        started = time.time()
        time.sleep(POLICY['preflight_seconds'])
        observer.sample()
        violations = observer.violations_since(started)
        if violations or observer.errors:
            result.update(status='host_preflight_rejected', violations=violations, observer_errors=observer.errors)
            return 2
        window_start = time.time()
        exclusive = {'status': 'passed', 'machine_exclusive_verified': True, 'machine_id': machine,
                     'other_host_workloads': [], 'cache_state': POLICY['cache_policy'],
                     'measurement_window_unix': [window_start, window_start + 1800],
                     'scope': 'Continuous revision-3 observation of macOS and dedicated Colima during this actual final operation.',
                     'observer_policy': {'path': 'observation-policy.json', 'sha256': file_hash(out / 'observation-policy.json')},
                     'quiet_preflight_seconds': POLICY['preflight_seconds'], 'continuous_observation_required': True}
        write_json(out / 'exclusive-window.json', exclusive)
        contract = {'status': 'frozen', 'resources': RESOURCES, 'image_id': resource['numeric_image_id'],
                    'resource_evidence': {'path': str(resource_path), 'sha256': file_hash(resource_path)},
                    'exclusivity_evidence': {'path': 'exclusive-window.json', 'sha256': file_hash(out / 'exclusive-window.json')}}
        contract_path = out / 'timing-contract.json'
        write_json(contract_path, contract)

        def measured(*call_args, **kwargs):
            row = replay_single(*call_args, **kwargs)
            observer.sample()
            violations = observer.violations_since(window_start)
            if violations or observer.errors:
                row.update(evaluation_status='evaluation_invalid', score=None, reward=None,
                           host_window_violations=violations, observer_errors=list(observer.errors))
            return row

        def checkpoint(*call_args, **kwargs):
            row = replay_checkpoint(*call_args, execute=measured, **kwargs)
            time.sleep(POLICY['sample_interval_seconds'])
            observer.sample()
            violations = observer.violations_since(window_start)
            if violations or observer.errors:
                # Preserve raw correctness and timings; reject their formal performance use.
                row.update(evaluation_status='evaluation_invalid', performance_status='invalid_environment',
                           score=None, reward=None, speedup=None, formal_timing=False,
                           formal_environment_qualified=False, formal_evidence_valid=False,
                           retry_permitted=False, host_window_violations=violations, observer_errors=list(observer.errors))
                write_json(Path(kwargs['output_root']) / 'result.json', row)
            return row

        result['final_test_scores_accessed'] = True
        common = {'timing_contract': contract_path, 'execute': checkpoint}
        data = ROOT / 'authoring/data/v0.3-local'
        if args.kind == 'baseline':
            value = baseline(ROOT, plan_path, 'poisson', args.identity, data, **common)
        else:
            value = final(ROOT, plan_path, args.identity, data, **common)
        write_json(out / 'operation-result.json', value)
        observer.sample()
        violations = observer.violations_since(window_start)
        (out / 'thermal-after.txt').write_text(subprocess.check_output(['pmset', '-g', 'therm'], text=True))
        clean = not docker('ps', '-q').stdout.strip()
        valid = value['diagnostics']['evaluation_status'] == 'valid'
        result.update(status='passed' if valid and clean and not violations and not observer.errors else 'rejected',
                      violations=violations, observer_errors=list(observer.errors), no_running_containers=clean,
                      evaluation_status=value['diagnostics']['evaluation_status'],
                      completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      operation_result_sha256=file_hash(out / 'operation-result.json'))
    except BaseException as exc:
        result.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        observer.stop.set()
        thread.join(timeout=10)
        result['host_observations_sha256'] = file_hash(observer.path)
        write_json(out / 'acceptance.json', result)
        print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
