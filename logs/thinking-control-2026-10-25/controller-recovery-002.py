"""Run the frozen control serially, then score after the full research barrier."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from runner.calibrate import METHODS
from runner.common import file_hash, read_json, write_json
from runner.study import closed_research, completed_task, frozen_plan, read_attempt

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PLAN = ROOT / 'freezes/research-run-plan-thinking-max-2026-10-25.json'
RESULTS = ROOT / 'results/thinking-control-2026-10-25'
REPAIR = ROOT / 'freezes/research-98719c3c1cf3fc92-pi-thinking-repair.json'


def record(stage, **details):
    write_json(OUT / 'state.json', {'stage': stage, 'updated_at': time.time(), 'controller_pid': os.getpid(),
                                  'plan': PLAN.relative_to(ROOT).as_posix(),
                                  'infrastructure_repair': {'path': REPAIR.relative_to(ROOT).as_posix(),
                                                            'sha256': file_hash(REPAIR)}, **details})
    print(json.dumps({'stage': stage, **details}), flush=True)


def invoke(name, command):
    with (OUT / (name + '.stdout.log')).open('x') as stream:
        return subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT).returncode


def idle():
    if subprocess.check_output(['docker', 'ps', '-q'], text=True).strip():
        raise RuntimeError('Unexpected active containers before next operation')


def main():
    plan, _ = frozen_plan(ROOT, PLAN)
    ledger = ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json'
    for row in plan['runs']:
        manifest = read_json(ledger) if ledger.exists() else {'attempts': []}
        prior = [e for e in manifest['attempts'] if e['run_id'] == row['run_id']]
        retry_of = None
        if prior:
            if (row['run_id'] == 'research-98719c3c1cf3fc92-heat-g1-r1'
                    and prior[-1]['attempt_id'] == row['run_id'] + '-a001'
                    and read_attempt(ROOT, prior[-1])['attempt_status'] == 'completed'):
                retry_of = prior[-1]['attempt_id']
            else:
                closed_research(ROOT, prior[-1], row)
                continue
        idle()
        latest = {e['run_id']: e for e in manifest['attempts']}
        retained = sum(read_attempt(ROOT, e)['attempt_status'] in ('completed', 'research_timeout')
                       for rid, e in latest.items() if rid != row['run_id'])
        record('research_running', sequence=row['sequence'], run_id=row['run_id'],
               closed_sessions=retained, hidden_data_accessed=False)
        command = [sys.executable, '-m', 'runner.study', 'start',
                   '--plan', str(PLAN), '--run-id', row['run_id']]
        if retry_of:
            command += ['--retry-of', retry_of]
        name = f"research-{row['sequence']:02d}" + ('-a002' if retry_of else '')
        code = invoke(name, command)
        entry = read_json(ledger)['attempts'][-1]
        closed_research(ROOT, entry, row)
        if code:
            raise RuntimeError(f'Research process exited {code}')
    manifest = read_json(ledger)
    for task in ('heat', 'ode', 'poisson'):
        completed_task(ROOT, plan, manifest, task)
    record('scoring_running', all_15_research_closed=True, hidden_data_accessed=True)
    operations = []
    for task in ('heat', 'ode', 'poisson'):
        for method in METHODS[task]:
            operations.append(('baseline', task, method))
    operations += [('final', row['task'], row['run_id']) for row in plan['runs']]
    outcomes = []
    for kind, task, identity in operations:
        idle()
        manifest = read_json(ledger)
        entries = ([b for b in manifest.get('baselines', []) if b['task'] == task and b['method'] == identity]
                   if kind == 'baseline' else [a for a in manifest['attempts'] if a['run_id'] == identity])
        ref = (entries[-1].get('result') if kind == 'baseline' else entries[-1].get('replay')) if entries else None
        if ref:
            outcomes.append({'kind': kind, 'task': task, 'identity': identity, 'action': 'retained', 'result': ref})
            continue
        name = kind + '-' + task + '-' + identity
        if task == 'poisson':
            command = [sys.executable, str(OUT / 'observed_final.py'), '--kind', kind,
                       '--identity', identity, '--output', str(OUT / ('window-' + name))]
        else:
            command = [sys.executable, '-m', 'runner.study', kind, '--plan', str(PLAN),
                       '--data', str(ROOT / 'authoring/data/v0.3-local')]
            command += ['--task', task, '--method', identity] if kind == 'baseline' else ['--run-id', identity]
        record('scoring_running', all_15_research_closed=True, operation=name, completed_operations=len(outcomes))
        code = invoke(name, command)
        outcomes.append({'kind': kind, 'task': task, 'identity': identity, 'exit_code': code, 'action': 'attempted_once'})
        write_json(OUT / 'scoring-operations.json', {'operations': outcomes})
    idle()
    code = invoke('report', [sys.executable, '-m', 'runner.study_report', '--project', str(ROOT), '--plan', str(PLAN),
                            '--manifest', str(ledger), '--output', str(RESULTS)])
    if code:
        raise RuntimeError(f'Report process exited {code}')
    record('results_ready_for_review', all_15_research_closed=True, results=RESULTS.relative_to(ROOT).as_posix(),
           operation_failures=[o for o in outcomes if o.get('exit_code', 0)], publication_complete=False)


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        record('stopped', error_type=type(exc).__name__, error=str(exc)[:800])
        raise
