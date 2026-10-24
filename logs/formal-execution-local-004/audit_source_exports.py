"""Read only closed public submission records; retain exact failure references."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads((ROOT / 'freezes/research-run-plan-formal-003.json').read_text())
    ledger_path = ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json'
    ledger = json.loads(ledger_path.read_text())
    failed, evaluations, exports = [], 0, 0
    for entry in ledger['attempts']:
        result = json.loads((ROOT / entry['result']['path']).read_text())
        if result['status'] in ('starting', 'research_running'):
            continue
        directory = ROOT / 'research-runs' / entry['run_id']
        if entry['parent_attempt']:
            directory = directory / 'retries' / entry['attempt_id']
        state = json.loads((ROOT / entry['registry']['path']).read_text())
        evaluations += len(state['evaluations'])
        for path in sorted((directory / 'file-bridge/requests').glob('*.json')):
            if path.name.endswith('.delivery.json'):
                continue
            row = json.loads(path.read_text())
            if row.get('request', {}).get('operation') != 'evaluate':
                continue
            exports += 1
            if row.get('export_error'):
                failed.append({'attempt_id': entry['attempt_id'], 'candidate_id': row.get('candidate_id'),
                               'requested_source': row.get('original_r_source'), 'error': row['export_error'],
                               'evidence_path': str(path.relative_to(ROOT)),
                               'evidence_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    value = {'observed_at_unix': time.time(), 'plan_id': plan['plan_id'],
             'scope': 'Closed public research attempts only; no hidden scores read. Requested paths are recorded without assuming their filesystem type.',
             'closed_public_evaluations': evaluations, 'recorded_export_requests': exports,
             'source_export_failures': len(failed),
             'failure_source_counts': dict(Counter(row['requested_source'] for row in failed)),
             'failure_error_counts': dict(Counter(row['error'] for row in failed)), 'failures': failed}
    with args.output.open('x') as output:
        json.dump(value, output, indent=2, ensure_ascii=False)
        output.write('\n')
    print(json.dumps({k: v for k, v in value.items() if k != 'failures'}, ensure_ascii=False))

if __name__ == '__main__':
    main()
