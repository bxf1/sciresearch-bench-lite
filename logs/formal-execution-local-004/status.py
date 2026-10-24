"""Read compact trusted progress only; no credentials or candidate content."""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
plan = json.loads((ROOT / 'freezes/research-run-plan-formal-003.json').read_text())
manifest = json.loads((ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json').read_text())
latest = {item['run_id']: item for item in manifest['attempts']}
results = []
for entry in manifest['attempts']:
    value = json.loads((ROOT / entry['result']['path']).read_text())
    row = {k: value.get(k) for k in ('run_id', 'attempt_id', 'status', 'attempt_status')}
    registry = value.get('registry')
    if not registry:
        output = ROOT / 'research-runs' / entry['run_id']
        if entry['parent_attempt']:
            output = output / 'retries' / entry['attempt_id']
        path = output / 'registry/state.json'
        registry = json.loads(path.read_text()) if path.exists() else {}
    row.update(evaluations=len(registry.get('evaluations', [])), first_id=registry.get('first_id'),
               final_id=registry.get('final_id'), closed=registry.get('closed'))
    if value.get('status') in ('starting', 'research_running'):
        if registry.get('started_at'):
            row['research_elapsed_seconds'] = int(time.time() - registry['started_at'])
        running = json.loads((output / 'result.json').read_text()) if (output / 'result.json').exists() else value
        admission = (running.get('relay') or {}).get('admission_path')
        path = Path(admission).parent / 'evidence/events.jsonl' if admission else None
        if path and path.exists():
            lines = path.read_text().splitlines()
            events = [json.loads(line) for line in lines]
            finished = [event for event in events if event['event'] == 'request_finished']
            row.update(requests_finished=len(finished), charged_output_tokens=sum(event.get('charged_output_tokens', 0) for event in finished),
                       known_successful_output_tokens=sum(event.get('output_tokens', 0) for event in finished if event.get('outcome') == 'success'),
                       failed_requests=sum(event.get('outcome') != 'success' for event in finished),
                       last_request_outcome=finished[-1].get('outcome') if finished else None,
                       last_relay_event=events[-1]['event'] if events else None)
    results.append(row)
print(json.dumps({'validly_closed': sum(row['status'] == 'research_frozen' for row in results),
                  'attempts': len(results), 'latest': results[-1:],
                  'finalized_tasks': manifest['finalized_tasks']}, ensure_ascii=False))
