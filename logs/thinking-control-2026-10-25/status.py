"""Inspect all control sessions and relay progress without hidden-data access."""
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
read = lambda path: json.loads(path.read_text())
plan = read(ROOT / 'freezes/research-run-plan-thinking-max-2026-10-25.json')
ledger = ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json'
entries = {e['run_id']: e for e in read(ledger)['attempts']} if ledger.exists() else {}
rows = []
for run in plan['runs']:
    entry = entries.get(run['run_id'])
    row = {k: run[k] for k in ('sequence', 'task', 'group', 'repeat', 'run_id')}
    row.update(status='not_started', output_limit=200000)
    if entry:
        value = read(ROOT / entry['result']['path'])
        row.update(status=value['status'], attempt_status=value['attempt_status'])
        output = ROOT / 'research-runs' / run['run_id']
        if entry['parent_attempt']:
            output = output / 'retries' / entry['attempt_id']
        registry = output / 'registry/state.json'
        if registry.exists():
            state = read(registry)
            row.update(closed=state['closed'], public_evaluations=len(state['evaluations']),
                       first_id=state['first_id'], final_id=state['final_id'])
        events = output / 'relay-evidence/evidence/events.jsonl'
        live = read(output / 'result.json') if (output / 'result.json').exists() else {}
        admission = (live.get('relay') or {}).get('admission_path')
        if not events.exists() and admission:
            parent = Path(admission).parent.resolve()
            if parent.is_relative_to((ROOT / 'build').resolve()):
                events = parent / 'evidence/events.jsonl'
        if events.exists():
            records = []
            for line in events.read_text().splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            finished = [e for e in records if e['event'] == 'request_finished']
            row.update(successful_requests=sum(e['outcome'] == 'success' for e in finished),
                       failed_requests=sum(e['outcome'] != 'success' for e in finished),
                       known_output_tokens=sum(e.get('output_tokens') or 0 for e in finished),
                       charged_output_tokens=sum(e.get('charged_output_tokens') or 0 for e in finished),
                       event_age_seconds=round(time.time() - records[-1]['timestamp'], 1) if records else None)
            accepted = [e for e in records if e['event'] == 'request_accepted']
            if accepted:
                row.update(effective_thinking=accepted[-1].get('effective_thinking'),
                           effective_output_config=accepted[-1].get('effective_output_config'))
    rows.append(row)
print(json.dumps({'controller': read(OUT / 'state.json') if (OUT / 'state.json').exists() else None,
                  'closed_sessions': sum(r.get('closed') is True for r in rows), 'runs': rows}, ensure_ascii=False, indent=2))
