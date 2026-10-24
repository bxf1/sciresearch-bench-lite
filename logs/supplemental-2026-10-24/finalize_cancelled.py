"""Read retained evidence; summarize user cancellation without changing frozen runs."""
import collections
import csv
import datetime
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from runner import supplemental as sup
from runner.common import read_json, write_json

ROOT = Path.cwd()
sup.PLAN = ROOT / 'freezes/supplemental-500k-2026-10-24-recovery-003.json'
plan = sup.load_plan()
run = ROOT / 'research-runs' / plan['runs'][0]['settings']['run_id']
result = read_json(run / 'result.json')
state = read_json(run / 'registry/state.json')
assert result['attempt_status'] == 'cancelled' and state['closed']
assert not state['evaluations'] and state['first_id'] is None and state['final_id'] is None
assert result['relay_cleanup']['all_removed'] and not result['cleanup_errors']
native = next((run / 'auxiliary-agent/pi/sessions').glob('*.jsonl'))
events = [(i, json.loads(line)) for i, line in enumerate(native.read_text().splitlines(), 1)]
calls, outputs = [], {}
for line, event in events:
    message = event.get('message', {})
    if message.get('role') == 'assistant':
        for content in message.get('content', []):
            if content.get('type') == 'toolCall':
                calls.append(dict(content, line=line, timestamp=event['timestamp'],
                                  response_id=message.get('responseId')))
    elif message.get('role') == 'toolResult':
        outputs[message['toolCallId']] = message

def key(call):
    return json.dumps([call['name'], call['arguments']], sort_keys=True)

def describe(chosen):
    texts = [json.dumps(outputs[c['id']]['content'], sort_keys=True) for c in chosen if c['id'] in outputs]
    return {'count': len(chosen), 'first_line': chosen[0]['line'], 'last_line': chosen[-1]['line'],
            'first_timestamp': chosen[0]['timestamp'], 'last_timestamp': chosen[-1]['timestamp'],
            'unique_call_ids': len({c['id'] for c in chosen}),
            'unique_response_ids': len({c['response_id'] for c in chosen}),
            'completed_tools': len(texts), 'unique_output_hashes': len({hashlib.sha256(t.encode()).hexdigest() for t in texts}),
            'tool_errors': sum(bool(outputs.get(c['id'], {}).get('isError')) for c in chosen),
            'tool_name': chosen[0]['name'], 'arguments': chosen[0]['arguments']}

groups = collections.defaultdict(list)
for call in calls:
    groups[key(call)].append(call)
streaks, start = [], 0
for i in range(1, len(calls) + 1):
    if i == len(calls) or key(calls[i]) != key(calls[start]):
        streaks.append(calls[start:i]); start = i
audit = {'source': sup.reference(native), 'method': 'Native session assistant toolCall entries counted once; exact tool name and JSON arguments, no normalization.',
         'total_calls': len(calls), 'unique_call_ids': len({c['id'] for c in calls}),
         'unique_commands': len(groups), 'tool_counts': dict(collections.Counter(c['name'] for c in calls)),
         'top_repeated': [describe(g) for g in sorted(groups.values(), key=len, reverse=True)[:3]],
         'longest_consecutive': [describe(g) for g in sorted(streaks, key=len, reverse=True)[:4]],
         'terminal_streak': describe(streaks[-1]),
         'bench_evaluate_calls': sum(bool(re.search(r'\bbench\s+evaluate\b', c['arguments'].get('command', ''))) for c in calls),
         'bench_finalize_calls': sum(bool(re.search(r'\bbench\s+finalize\b', c['arguments'].get('command', ''))) for c in calls),
         'compactions': sum(e.get('type') == 'compaction' for _, e in events),
         'scope': 'Post-hoc observation, not model-internal causal diagnosis; no hidden data or intervention.'}
audit_path = ROOT / 'logs/supplemental-2026-10-24/repetition-audit-final.json'
write_json(audit_path, audit)
rows = []
for index, row in enumerate(plan['runs']):
    settings = row['settings']
    if index:
        assert not (ROOT / 'research-runs' / settings['run_id']).exists()
    rows.append({'run_id': settings['run_id'], 'task': settings['task'], 'group': settings['group'], 'repeat': settings['repeat'],
                 'status': 'cancelled_by_user' if index == 0 else 'cancelled_before_start',
                 'public_evaluations': 0, 'first_id': None, 'final_id': None,
                 'score': None, 'reward': None,
                 'known_output_tokens': result['relay_status']['charged_output_tokens'] if index == 0 else 0})
closure = {'status': 'cancelled_by_user', 'plan': sup.reference(sup.PLAN),
           'closed_at': datetime.datetime.fromtimestamp(result['finished_at'], ZoneInfo('Asia/Shanghai')).isoformat(),
           'authorization': sup.reference(ROOT / 'logs/supplemental-2026-10-24/user-stop-request.json'),
           'current_attempt': sup.reference(run / 'result.json'), 'repetition_audit': sup.reference(audit_path),
           'cleanup_confirmed': True, 'automation_deleted': True, 'hidden_replay_performed': False,
           'frozen_source_hashes_unchanged': True, 'no_new_scientific_scores': True, 'runs': rows,
           'original_g2_retiming': 'prior_preflight_rejected; no new timing performed; original invalid result retained'}
write_json(ROOT / 'logs/supplemental-2026-10-24/user-stop-confirmation.json', closure)
out = ROOT / 'results/submission-2026-10-24'
out.mkdir(exist_ok=True)
with (ROOT / 'results/formal-study-003/checkpoints.csv').open() as stream:
    finals = [r for r in csv.DictReader(stream) if r['checkpoint_role'] == 'final']
assert len(finals) == 15
valid = [r for r in finals if r['evaluation_status'] == 'valid']
successes = sum(r['reward'] in ('1', '1.0') for r in valid)
assert len(valid) == 14 and successes == 6
summary = {'status': 'finalized_from_completed_formal_experiments', 'formal_plan': sup.reference(ROOT / 'freezes/research-run-plan-formal-003.json'),
           'formal_results': sup.reference(ROOT / 'results/formal-study-003/summary.json'),
           'formal_sessions': 15, 'author_baseline_methods': 11, 'generated_instances': 90,
           'valid_scoring': 14, 'successful_sessions': successes, 'valid_unsuccessful_sessions': len(valid) - successes,
           'invalid_scoring_sessions': 1, 'submitted_sessions': 9, 'normal_no_submission_sessions': 6,
           'supplemental_closure': sup.reference(ROOT / 'logs/supplemental-2026-10-24/user-stop-confirmation.json'),
           'original_results_replaced': False, 'supplemental_in_scientific_denominator': False}
write_json(out / 'final-summary.json', summary)
print(json.dumps({'total_tool_calls': len(calls), 'top_repetition_counts': [x['count'] for x in audit['top_repeated']],
                  'longest_streak': audit['longest_consecutive'][0]['count'], 'tail': len(streaks[-1]),
                  'successful_formal_sessions': successes, 'closed_at': closure['closed_at']}))
