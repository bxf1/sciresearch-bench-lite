"""One linked retry after the user resolved the confirmed provider HTTP 402."""
from pathlib import Path
import json
import subprocess
import sys
from runner.common import read_json, write_json, file_hash
from runner.study import frozen_plan

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUN = 'research-6615cd7900ba0750-ode-g1-r1'
PLAN = ROOT / 'freezes/research-run-plan-formal-003.json'
parent = ROOT / 'research-runs' / RUN / 'retries' / (RUN + '-a002') / 'result.json'
r = read_json(parent)
assert r['attempt_status'] == 'api_failed' and r['status'] == 'research_invalid'
assert r['relay_cleanup']['all_removed'] and not r['bridge_errors'] and not r['cleanup_errors']
recovery_path = OUT / 'api-recovery-001/synthetic-probe.json'
recovery = read_json(recovery_path)
assert recovery['http_status'] == 200 and recovery['complete'] is True
assert recovery['user_authorization'] == '已处理，继续原计划'
assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip()
plan, _ = frozen_plan(ROOT, PLAN)
ledger = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')
assert [a for a in ledger['attempts'] if a['run_id'] == RUN][-1]['attempt_id'] == RUN + '-a002'
machine = subprocess.check_output(['colima', 'ssh', '--', 'cat', '/proc/sys/kernel/random/boot_id'], text=True).strip()
resource = read_json(ROOT / 'logs/resource-acceptance-local-002/summary.json')
assert machine == resource['machine_id']
info = json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .}}'], text=True))
assert info['NCPU'] >= 6 and info['MemTotal'] >= 8.5 * 1024**3
acceptance = OUT / 'api-recovery-001/retry-acceptance.json'
assert not acceptance.exists()
write_json(acceptance, {
    'parent_attempt': RUN + '-a002', 'parent_result_sha256': file_hash(parent),
    'recovery_probe_sha256': file_hash(recovery_path),
    'reason': 'User confirmed account resolution; one synthetic Messages request completed with HTTP 200. Retain the HTTP 402 attempt and create a new session under the unchanged third freeze.',
    'user_authorization': recovery['user_authorization'],
    'vm_boot_id': machine, 'plan_sha256': file_hash(PLAN),
    'docker': {k: info[k] for k in ('NCPU', 'MemTotal', 'CgroupVersion')},
    'power': subprocess.check_output(['pmset', '-g', 'batt'], text=True),
    'retry_limit_this_investigation': 1, 'hidden_scores_accessed': False,
})
print('recovery_preflight_passed', flush=True)
with (OUT / '04-ode-g1-r1-a003.stdout.log').open('x') as log:
    result = subprocess.run([sys.executable, '-m', 'runner.study', 'start', '--plan', str(PLAN),
                             '--run-id', RUN, '--retry-of', RUN + '-a002'],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
print('linked_retry_exit_code', result.returncode, flush=True)
if result.returncode:
    raise SystemExit(result.returncode)
with (OUT / 'research-sequence-003.stdout.txt').open('x') as log:
    result = subprocess.run([sys.executable, str(OUT / 'research_sequence.py')],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
raise SystemExit(result.returncode)
