"""Summarize retained research traces without reading hidden scores or prompts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads((ROOT / 'freezes/research-run-plan-formal-003.json').read_text())
    ledger = ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json'
    rows = []
    for entry in json.loads(ledger.read_text())['attempts']:
        result_path = ROOT / entry['result']['path']
        result = json.loads(result_path.read_text())
        if result['status'] in ('starting', 'research_running'):
            continue
        directory = ROOT / 'research-runs' / entry['run_id']
        if entry['parent_attempt']:
            directory = directory / 'retries' / entry['attempt_id']
        registry_path = ROOT / entry['registry']['path']
        assert registry_path == directory / 'registry/state.json'
        state = json.loads(registry_path.read_text())
        names, stops, errors = Counter(), Counter(), Counter()
        signatures = []
        native = sorted((directory / 'auxiliary-agent/pi/sessions').glob('*.jsonl'))
        compactions = tool_results = 0
        for path in native:
            for event in events(path):
                compactions += event.get('type') == 'compaction'
                message = event.get('message', {})
                if message.get('role') == 'assistant':
                    stops[message.get('stopReason', 'unknown')] += 1
                    for part in message.get('content', []):
                        if part.get('type') == 'toolCall':
                            names[part.get('name')] += 1
                            payload = json.dumps([part.get('name'), part.get('arguments')], sort_keys=True)
                            signatures.append(hashlib.sha256(payload.encode()).hexdigest())
                elif message.get('role') == 'toolResult':
                    tool_results += 1
                    if message.get('isError'):
                        text = '\n'.join(c.get('text', '') for c in message.get('content', []) if c.get('type') == 'text')
                        category = ('output_limit_truncation' if 'response hit the output token limit' in text
                                    else 'process_creation_resource' if 'fork: retry: Resource temporarily unavailable' in text
                                    else 'other_tool_error')
                        errors[category] += 1
        previous, streak, longest = None, 0, 0
        for signature in signatures:
            streak = streak + 1 if signature == previous else 1
            longest = max(longest, streak)
            previous = signature
        relay_path = ROOT / entry['relay_events']['path']
        requests = [e for e in events(relay_path) if e['event'] == 'request_finished']
        success = [e for e in requests if e['outcome'] == 'success']
        rows.append({
            'run_id': entry['run_id'], 'attempt_id': entry['attempt_id'],
            'parent_attempt': entry['parent_attempt'], 'status': result['status'],
            'attempt_status': result.get('attempt_status'), 'result_sha256': digest(result_path),
            'registry_sha256': digest(registry_path) if registry_path.exists() else None,
            'public_evaluations': len(state.get('evaluations', [])),
            'artifact_valid_evaluations': sum(e['artifact_valid'] is True for e in state.get('evaluations', [])),
            'first_id': state.get('first_id'), 'final_id': state.get('final_id'),
            'selection_reason': state.get('selection_reason'),
            'finalization_invalid': state.get('finalization_invalid'),
            'tool_calls': dict(names), 'unique_tool_calls': len(set(signatures)),
            'longest_identical_tool_call_streak': longest, 'tool_results': tool_results,
            'tool_error_categories': dict(errors), 'assistant_stop_reasons': dict(stops),
            'native_compactions': compactions,
            'native_log_files': [{'path': str(p.relative_to(ROOT)), 'sha256': digest(p)} for p in native],
            'successful_requests': len(success), 'failed_requests': len(requests) - len(success),
            'request_outcomes': dict(Counter(e['outcome'] for e in requests)),
            'request_failure_reasons': dict(Counter(e.get('failure_reason') or e['outcome'] for e in requests if e['outcome'] != 'success')),
            'known_successful_output_tokens': sum(e['output_tokens'] for e in success),
            'charged_output_tokens': sum(e['charged_output_tokens'] for e in requests),
            'cost_usd': None,
        })
    with args.output.open('x') as output:
        json.dump({'observed_at_unix': time.time(), 'plan_id': plan['plan_id'],
                   'ledger_sha256_at_observation': digest(ledger), 'hidden_scores_accessed': False,
                   'scope': 'Closed research attempts only. Native tool errors describe agent behavior; they are not automatically infrastructure failures.',
                   'attempts': rows}, output, indent=2, ensure_ascii=False)
        output.write('\n')
    print(json.dumps({'output': str(args.output), 'closed_attempts': len(rows)}))

if __name__ == '__main__':
    main()
