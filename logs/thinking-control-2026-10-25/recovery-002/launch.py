"""Launch the one authorized linked retry, then the remaining frozen matrix."""
import os
from pathlib import Path
import subprocess
import sys
import time

from runner.common import file_hash, read_json, write_json
from runner.study import frozen_plan

OUT = Path(__file__).resolve().parent
BATCH = OUT.parent
ROOT = BATCH.parents[1]
PLAN = ROOT / 'freezes/research-run-plan-thinking-max-2026-10-25.json'
REPAIR = ROOT / 'freezes/research-98719c3c1cf3fc92-pi-thinking-repair.json'
plan, reference = frozen_plan(ROOT, PLAN)
assert reference['sha256'] == '25c3250f8615aa5a90a24206964533085b5448f06910f7e42a969e2f66763f0e'
assert not (OUT / 'process.json').exists(), 'Retain prior recovery; never launch twice.'
assert os.environ.get('ANTHROPIC_AUTH_TOKEN'), 'Provider credential unavailable'
for filename, field in (('previous-process.json', 'pid'), ('previous-state.json', 'controller_pid')):
    pid = read_json(OUT / filename)[field]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise RuntimeError(f'Previous controller process {pid} still exists')
assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip(), 'Unexpected live containers'
for name, sha in read_json(OUT / 'original-evidence-sha256.json')['files'].items():
    assert file_hash(ROOT / name) == sha, f'Original evidence changed: {name}'
probe = read_json(OUT / 'live-probe/result.json')
assert probe['status'] == 'passed' and probe['cleanup']['all_removed']
patch = read_json(OUT / 'native-patch.json')
assert patch['after_sha256'] == file_hash(OUT / 'agent-loop.patched.js')
assert probe['native']['records'][0]['stopReason'] == 'length'
assert probe['native']['records'][-1]['stopReason'] == 'stop'
manifest = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')
assert len(manifest['attempts']) == 5
assert any(e['attempt_id'] == 'research-98719c3c1cf3fc92-heat-g1-r1-a001' for e in manifest['attempts'])
env = os.environ.copy()
env['PYTHONPATH'] = str(ROOT)
env['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
controller = BATCH / 'controller-recovery-002.py'
with (OUT / 'controller.stdout.log').open('xb') as stream:
    proc = subprocess.Popen(['/usr/bin/caffeinate', '-dimsu', sys.executable, str(controller)], cwd=ROOT,
                            env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                            start_new_session=True, close_fds=True)
write_json(OUT / 'process.json', {'pid': proc.pid, 'started_at': time.time(), 'detached': True,
    'controller': controller.relative_to(ROOT).as_posix(), 'controller_sha256': file_hash(controller),
    'plan': reference, 'plan_id': plan['plan_id'],
    'infrastructure_repair': {'path': REPAIR.relative_to(ROOT).as_posix(), 'sha256': file_hash(REPAIR)},
    'retry_parent': 'research-98719c3c1cf3fc92-heat-g1-r1-a001',
    'retry_attempt': 'research-98719c3c1cf3fc92-heat-g1-r1-a002',
    'completed_retained': 3, 'remaining_unstarted': 11,
    'output_token_limit': 200000, 'thinking': {'type': 'enabled'}, 'output_config': {'effort': 'max'},
    'sleep_inhibited_while_running': True, 'prior_failure_preserved': True,
    'after_research': 'Original full closure barrier, independent scoring, report, then authorized publication.'})
print(f'Launched recovery supervisor PID {proc.pid}; linked retry a002, then remaining 11 sessions.')
