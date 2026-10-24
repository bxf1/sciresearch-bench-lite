"""One linked retry after investigated terminal transport failures and recovery."""
from pathlib import Path
import json
import subprocess
import sys
from runner.common import read_json, write_json, file_hash
from runner.study import frozen_plan

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUN = 'research-6615cd7900ba0750-heat-g3-r2'
PLAN = ROOT / 'freezes/research-run-plan-formal-003.json'
parent = ROOT / 'research-runs' / RUN / 'result.json'
value = read_json(parent)
assert value['attempt_status'] == 'api_failed' and value['status'] == 'research_invalid'
assert value['relay_cleanup']['all_removed'] and value['worker_cleanup']['all_removed']
assert not value['bridge_errors'] and not value['cleanup_errors']
event_path = parent.parent / 'relay-evidence/evidence/events.jsonl'
events = [json.loads(line) for line in event_path.read_text().splitlines()]
accepted = {e['request_id']: e for e in events if e['event'] == 'request_accepted'}
finished = [e for e in events if e['event'] == 'request_finished']
success = [e for e in finished if e['outcome'] == 'success']
failed = [e for e in finished if e['outcome'] != 'success']
assert len(success) == 659 and len(failed) == 2
assert sum(e['output_tokens'] for e in success) == 194606
assert all(e['outcome'] == 'upstream_transport_error' and e['upstream_status'] is None and e['output_tokens'] is None for e in failed)
assert sum(e['charged_output_tokens'] for e in failed) == 5394
assert read_json(parent.parent / 'host-termination.json')['deadline_fired'] is False
investigation = OUT / 'heat-g3-r2-transport-investigation'
probe_path = investigation / 'synthetic-probe.json'
probe = read_json(probe_path)
assert probe['http_status'] == 200 and probe['complete'] is True
assert not subprocess.check_output(['docker', 'ps', '-q'], text=True).strip()
plan, _ = frozen_plan(ROOT, PLAN)
ledger = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')
assert [a for a in ledger['attempts'] if a['run_id'] == RUN][-1]['attempt_id'] == RUN + '-a001'
machine = subprocess.check_output(['colima', 'ssh', '--', 'cat', '/proc/sys/kernel/random/boot_id'], text=True).strip()
resource = read_json(ROOT / 'logs/resource-acceptance-local-002/summary.json')
assert machine == resource['machine_id']
info = json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .}}'], text=True))
assert info['NCPU'] >= 6 and info['MemTotal'] >= 8.5 * 1024**3
acceptance = investigation / 'retry-acceptance.json'
assert not acceptance.exists()
write_json(acceptance, {
    'parent_attempt': RUN + '-a001', 'parent_result_sha256': file_hash(parent),
    'relay_events_sha256': file_hash(event_path), 'recovery_probe_sha256': file_hash(probe_path),
    'failed_requests': [{**e, 'elapsed_seconds': e['timestamp'] - accepted[e['request_id']]['timestamp']} for e in failed],
    'known_successful_output_tokens': 194606, 'failed_reserved_tokens': 5394,
    'charged_output_tokens': 200000, 'actual_failed_usage': None,
    'reason': 'The terminal outcome was two upstream_transport_error events without HTTP status, not a normal scientific closure. Their conservative reservations exhausted the remaining budget. The frozen controller classified api_failed; preserve that classification and all prior cost. One synthetic request now completed with HTTP 200. Create one fresh linked retry under the unchanged third freeze.',
    'evidence_limit': 'The frozen generic transport handler did not retain the underlying exception type. No specific network cause is asserted.',
    'vm_boot_id': machine, 'plan_sha256': file_hash(PLAN),
    'docker': {k: info[k] for k in ('NCPU', 'MemTotal', 'CgroupVersion')},
    'power': subprocess.check_output(['pmset', '-g', 'batt'], text=True),
    'retry_limit_this_investigation': 1, 'hidden_scores_accessed': False,
})
print('transport_retry_preflight_passed', flush=True)
with (OUT / '10-heat-g3-r2-a002.stdout.log').open('x') as log:
    result = subprocess.run([sys.executable, '-m', 'runner.study', 'start', '--plan', str(PLAN),
                             '--run-id', RUN, '--retry-of', RUN + '-a001'],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
print('linked_retry_exit_code', result.returncode, flush=True)
if result.returncode:
    raise SystemExit(result.returncode)
with (OUT / 'research-sequence-005.stdout.txt').open('x') as log:
    result = subprocess.run([sys.executable, str(OUT / 'research_sequence.py')],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
raise SystemExit(result.returncode)
