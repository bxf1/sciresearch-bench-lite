"""Resume only the unstarted frozen sessions after the context handoff repair."""
import os
from pathlib import Path
import subprocess
import sys
import time

from runner.common import file_hash, read_json, write_json
from runner.study import frozen_plan, read_attempt, reference

OUT = Path(__file__).resolve().parent
BATCH = OUT.parent
ROOT = BATCH.parents[1]
PLAN = ROOT / 'freezes/research-run-plan-thinking-max-2026-10-25.json'
REPAIR = ROOT / 'freezes/research-98719c3c1cf3fc92-pi-context-repair.json'
plan, plan_ref = frozen_plan(ROOT, PLAN)
assert plan_ref['sha256'] == '25c3250f8615aa5a90a24206964533085b5448f06910f7e42a969e2f66763f0e'
assert not (OUT / 'process.json').exists(), 'Never launch a recovery twice.'
assert os.environ.get('ANTHROPIC_AUTH_TOKEN'), 'Provider credential unavailable'
pid = read_json(OUT / 'previous-process.json')['pid']
try:
    os.kill(pid, 0)
except ProcessLookupError:
    pass
else:
    raise RuntimeError(f'Previous controller process {pid} still exists')
assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip(), 'Unexpected live containers'
for name, sha in read_json(OUT / 'original-evidence-sha256.json')['files'].items():
    assert file_hash(ROOT / name) == sha, f'Original evidence changed: {name}'
probe = read_json(OUT / 'live-context-probe-a004/result.json')
assert probe['status'] == 'passed' and probe['cleanup']['all_removed']
assert probe['native']['real_native_agent_session'] is True
assert probe['native']['wires'][0]['requested_max_tokens'] == 1
assert probe['native']['responses'][-1]['stopReason'] == 'stop'
for patch in read_json(OUT / 'native-patch.json')['patches']:
    filename = Path(patch['path']).name.replace('.js', '.patched.js')
    assert patch['after_sha256'] == file_hash(OUT / filename)
assert read_json(OUT / 'controller-simulation.json')['status'] == 'passed'
manifest = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')
assert manifest == read_json(OUT / 'original-manifest.json')
latest = {e['run_id']: e for e in manifest['attempts']}
assert len(latest) == 4 and len(manifest['attempts']) == 6
assert all(read_attempt(ROOT, e)['attempt_status'] in ('completed', 'research_timeout') for e in latest.values())
env = os.environ.copy()
env['PYTHONPATH'] = str(ROOT)
env['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
controller = BATCH / 'controller-recovery-003.py'
with (OUT / 'controller.stdout.log').open('xb') as stream:
    proc = subprocess.Popen(['/usr/bin/caffeinate', '-dimsu', sys.executable, str(controller)], cwd=ROOT,
                            env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                            start_new_session=True, close_fds=True)
write_json(OUT / 'process.json', {'pid': proc.pid, 'started_at': time.time(), 'detached': True,
    'controller': controller.relative_to(ROOT).as_posix(), 'controller_sha256': file_hash(controller),
    'plan': plan_ref, 'plan_id': plan['plan_id'], 'infrastructure_repair': reference(ROOT, REPAIR),
    'closed_retained': 4, 'remaining_unstarted': 11, 'new_retries': 0,
    'output_token_limit': 200000, 'request_output_limit': 4096,
    'thinking': {'type': 'enabled'}, 'output_config': {'effort': 'max'},
    'sleep_inhibited_while_running': True, 'prior_evidence_preserved': True,
    'after_research': 'Original full closure barrier, independent scoring, report, then authorized publication.'})
print(f'Launched recovery supervisor PID {proc.pid}; retain four closed sessions and continue remaining 11.')
