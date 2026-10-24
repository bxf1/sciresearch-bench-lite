"""Execute untouched frozen research rows serially; stop for failure investigation."""
import fcntl
import json
import subprocess
import sys
from pathlib import Path

from runner.common import read_json, write_json
from runner.study import closed_research, frozen_plan

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PLAN = ROOT / 'freezes/research-run-plan-formal-003.json'


def main():
    plan, _ = frozen_plan(ROOT, PLAN)
    ledger = ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json'
    # The already launched first attempt owns this same lock until its host
    # outcome is durable. Wait, then validate it before admitting another row.
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with (ledger.parent / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fcntl.flock(lock, fcntl.LOCK_UN)
    completed = []
    for row in plan['runs']:
        manifest = read_json(ledger) if ledger.exists() else {'attempts': []}
        prior = [entry for entry in manifest['attempts'] if entry['run_id'] == row['run_id']]
        if prior:
            closed_research(ROOT, prior[-1], row)
            completed.append(row['run_id'])
            continue
        if subprocess.check_output(['docker', 'ps', '-q'], text=True).strip():
            raise RuntimeError('Unexpected running containers before next research row')
        name = f"{row['sequence']:02d}-{row['task']}-{row['group']}-r{row['repeat']}-a001"
        print(json.dumps({'event': 'starting', 'sequence': row['sequence'], 'run_id': row['run_id']}), flush=True)
        with (OUT / (name + '.stdout.log')).open('x') as log:
            proc = subprocess.run([sys.executable, '-m', 'runner.study', 'start', '--plan', str(PLAN),
                                   '--run-id', row['run_id']], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        manifest = read_json(ledger)
        entry = [entry for entry in manifest['attempts'] if entry['run_id'] == row['run_id']][-1]
        result = read_json(ROOT / entry['result']['path'])
        print(json.dumps({'event': 'finished', 'run_id': row['run_id'], 'exit_code': proc.returncode,
                          'status': result.get('status'), 'attempt_status': result.get('attempt_status'),
                          'cleanup_errors': result.get('cleanup_errors'), 'bridge_errors': result.get('bridge_errors')}), flush=True)
        if proc.returncode:
            return 1
        _, state = closed_research(ROOT, entry, row)
        assert result.get('score') is None and result.get('reward') is None
        if subprocess.check_output(['docker', 'ps', '-q'], text=True).strip():
            raise RuntimeError('Containers remain after closed research')
        completed.append(row['run_id'])
        write_json(OUT / 'research-progress.json', {'validly_closed': len(completed), 'planned': len(plan['runs']),
                                                  'completed_run_ids': completed})
        print(json.dumps({'event': 'verified', 'completed': len(completed), 'evaluations': len(state['evaluations']),
                          'first_id': state['first_id'], 'final_id': state['final_id']}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
