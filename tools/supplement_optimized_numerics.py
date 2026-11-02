"""Accuracy-only completion where formal Poisson admission produced no outputs.

Never retries BCCBBC, changes a selection, or fills a formal performance score.
"""
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runner.common import read_json, write_json, file_hash, canonical, digest, tree_hashes
from runner.study import frozen_plan, completed_task, closed_research, reference
from runner.run_plan import _file_ref
from runner.replay import prepare_judge, replay_single

OUT = ROOT / 'results/optimized-r1-20261101'
DATA = ROOT / 'authoring/data/optimized-r1-20261101'
PLAN = ROOT / 'freezes/research-run-plan-optimized-r1-20261101.json'


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    raw_path = OUT / 'results.json'
    raw = read_json(raw_path)
    assert raw['status'] == 'scoring_completed'
    assert read_json(ROOT / 'logs/optimized-r1-20261101/state.json')['stage'] == 'results_ready_for_report'
    plan, plan_ref = frozen_plan(ROOT, PLAN)
    ledger = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')
    latest = completed_task(ROOT, plan, ledger, 'poisson')
    destination = OUT / 'numeric-only'
    destination.mkdir(exist_ok=False)
    result = {'purpose': 'accuracy_only_missing_outputs', 'formal_timing': False,
              'changes_formal_scores': False, 'new_scientific_sessions': 0,
              'candidate_selection_changed': False, 'plan': plan_ref,
              'original_results': reference(ROOT, raw_path), 'started_at': time.time(),
              'groups': [], 'status': 'running'}
    name = 'dcomp-demo-postgres'
    running = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True).splitlines()
    assert set(running).issubset({name}), running
    restore = name in running
    result['service'] = {'before_running': restore, 'restored': False}
    output_path = OUT / 'numeric-only-supplement.json'
    write_json(output_path, result)
    try:
        if restore:
            subprocess.run(['docker', 'stop', name], check=True, stdout=subprocess.DEVNULL)
        for item in raw['rows']:
            row = item['run']
            if row['task'] != 'poisson':
                continue
            registry, state = closed_research(ROOT, latest[row['run_id']], row)
            freeze_path = _file_ref(ROOT, plan['freezes']['poisson'])
            freeze = read_json(freeze_path)
            jobs = {}
            for role in ('first', 'final'):
                record = item['main']['diagnostics'].get(role)
                if not record:
                    continue
                samples = [s for r in record.get('repeats', []) for s in r.get('samples', {}).get('C', [])]
                if samples:
                    continue
                identifier = state[role + '_id']
                assert identifier and record['source_hash']
                job = jobs.setdefault(record['source_hash'], {'roles': [], 'identifier': identifier})
                job['roles'].append(role)
            # All diagnostics in this completed batch already contain three C observations.
            assert all(len(v.get('samples', {}).get('C', [])) == 3
                       for v in item['diagnostic'].get('profiles', {}).values())
            for source_hash, job in jobs.items():
                source = registry.verified_snapshot(job['identifier'])
                assert digest(canonical(tree_hashes(source))) == source_hash
                root = destination / row['run_id'] / source_hash[:12]
                judge = prepare_judge(ROOT, root / 'judge-source')
                group = {'run_id': row['run_id'], 'roles': job['roles'], 'split': 'final-test',
                         'source_hash': source_hash, 'candidate_id': job['identifier'],
                         'reason': 'all_formal_preflight_windows_rejected_no_numeric_outputs',
                         'formal_timing': False, 'formal_score': None, 'replays': []}
                result['groups'].append(group)
                for index in range(3):
                    output = root / f'replay-{index + 1}'
                    observed = replay_single(source, task='poisson', input_root=DATA / 'inputs/poisson/final-test',
                        truth_root=DATA / 'private/poisson/final-test', output_root=output,
                        image=freeze['image_id'], judge_source_root=judge, freeze_path=freeze_path)
                    group['replays'].append(reference(ROOT, output / 'result.json'))
                    write_json(output_path, result)
                    print({'run_id': row['run_id'], 'accuracy_replay': index + 1,
                           'status': observed['evaluation_status'], 'passed': sum(c.get('scientific_pass') is True for c in observed.get('cases', []))}, flush=True)
        assert file_hash(raw_path) == result['original_results']['sha256']
        result.update(status='completed', finished_at=time.time())
    finally:
        if restore:
            subprocess.run(['docker', 'start', name], check=True, stdout=subprocess.DEVNULL)
        after = subprocess.check_output(['docker', 'inspect', '--format', '{{.State.Running}}', name], text=True).strip() == 'true'
        result['service'].update(after_running=after, restored=after == restore)
        write_json(output_path, result)
        assert result['service']['restored']


if __name__ == '__main__':
    main()
