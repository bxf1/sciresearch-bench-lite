"""One investigated linked retry for a field-observed usage counter decrease."""
from pathlib import Path
import json
import subprocess
import sys
from runner.common import read_json, write_json, file_hash
from runner.study import frozen_plan

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUN = 'research-6615cd7900ba0750-poisson-g1-r1'
PLAN = ROOT / 'freezes/research-run-plan-formal-003.json'
parent = ROOT / 'research-runs' / RUN / 'result.json'
value = read_json(parent)
assert value['attempt_status'] == 'infrastructure_failed' and value['status'] == 'research_invalid'
assert value['relay_cleanup']['all_removed'] and value['worker_cleanup']['all_removed']
assert not value['bridge_errors'] and not value['cleanup_errors']
event_path = parent.parent / 'relay-evidence/evidence/events.jsonl'
finished = [json.loads(line) for line in event_path.read_text().splitlines()
            if json.loads(line)['event'] == 'request_finished']
assert len(finished) == 1 and finished[0]['failure_reason'] == 'usage_decreased'
assert finished[0]['usage_violation'] == {'field': 'input_tokens', 'previous': 434, 'observed': 306}
assert finished[0]['upstream_status'] == 200 and finished[0]['output_tokens'] is None
assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip()
plan, _ = frozen_plan(ROOT, PLAN)
ledger = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')
assert [a for a in ledger['attempts'] if a['run_id'] == RUN][-1]['attempt_id'] == RUN + '-a001'
machine = subprocess.check_output(['colima', 'ssh', '--', 'cat', '/proc/sys/kernel/random/boot_id'], text=True).strip()
resource = read_json(ROOT / 'logs/resource-acceptance-local-002/summary.json')
assert machine == resource['machine_id']
info = json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .}}'], text=True))
assert info['NCPU'] >= 6 and info['MemTotal'] >= 8.5 * 1024**3
investigation = OUT / 'poisson-g1-usage-investigation'
investigation.mkdir(exist_ok=False)
write_json(investigation / 'retry-acceptance.json', {
    'parent_attempt': RUN + '-a001', 'parent_result_sha256': file_hash(parent),
    'relay_events_sha256': file_hash(event_path), 'failed_request': finished[0],
    'reason': 'The first upstream HTTP 200 response reported input_tokens decreasing from 434 to 306. The frozen per-field monotonicity guard rejected it; output usage is unknown. No model tool or public evaluation completed. Preserve this invalid attempt and create one fresh linked retry without changing the usage guard, model, prompts, limits, data, or scoring.',
    'causal_limit': 'The log identifies the field and values but does not establish why the provider changed them or whether aggregate billing changed.',
    'vm_boot_id': machine, 'plan_sha256': file_hash(PLAN),
    'docker': {k: info[k] for k in ('NCPU', 'MemTotal', 'CgroupVersion')},
    'power': subprocess.check_output(['pmset', '-g', 'batt'], text=True),
    'retry_limit_this_investigation': 1, 'hidden_scores_accessed': False,
})
print('usage_retry_preflight_passed', flush=True)
with (OUT / '09-poisson-g1-r1-a002.stdout.log').open('x') as log:
    result = subprocess.run([sys.executable, '-m', 'runner.study', 'start', '--plan', str(PLAN),
                             '--run-id', RUN, '--retry-of', RUN + '-a001'],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
print('linked_retry_exit_code', result.returncode, flush=True)
if result.returncode:
    raise SystemExit(result.returncode)
with (OUT / 'research-sequence-004.stdout.txt').open('x') as log:
    result = subprocess.run([sys.executable, str(OUT / 'research_sequence.py')],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
raise SystemExit(result.returncode)
