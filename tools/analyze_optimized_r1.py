"""Read-only scientific aggregation of the closed optimized nine-session batch.

The controller owns candidate selection and execution. This file only joins saved
evidence, preserves invalid results as null, and exports replay-level observations.
"""
import csv
import copy
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/optimized-r1-20261101'
LOG = ROOT / 'logs/optimized-r1-20261101'
PLAN = ROOT / 'freezes/research-run-plan-optimized-r1-20261101.json'
METRICS = {'heat': ('E_init', 'E_forward'), 'ode': ('E_roll', 'E_field'),
           'poisson': ('max_relative_residual', 'max_solution_error')}
PROFILES = {'heat': ('amplitude', 'spectral_decay', 'contiguous_mask'),
            'ode': ('coordinate_scale', 'coordinate_swap', 'stable_cubic'),
            'poisson': ('large_grid', 'five_disks', 'cache_order')}


def read(path):
    return json.loads(Path(path).read_text())


def ref(path):
    path = Path(path)
    return {'path': path.relative_to(ROOT).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def checked(reference):
    path = ROOT / reference['path']
    assert ref(path)['sha256'] == reference['sha256'], reference['path']
    return read(path)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def summary(values):
    values = [v for v in values if finite(v)]
    return {'count': len(values), 'min': min(values) if values else None,
            'median': median(values) if values else None,
            'max': max(values) if values else None}


def numeric_samples(result):
    """Preserve numerical samples even if a timing window was invalidated."""
    if 'samples' in result:
        return result['samples'].get('C', [])
    return [result] if 'worker' in result or 'cases' in result else []


def checkpoint_samples(record):
    return [sample for replay in (record or {}).get('repeats', [])
            for sample in numeric_samples(replay)]


def cases_by_id(samples):
    cases = {}
    for sample in samples:
        for row in sample.get('cases', []):
            cases.setdefault(row['id'], []).append(row)
    return cases


def numeric_summary(samples, task, expected, *, profile=None, level=None):
    selected = []
    for sample in samples:
        selected.append([r for r in sample.get('cases', [])
                         if (profile is None or r.get('profile_id') == profile)
                         and (level is None or r.get('level') == level)])
    by_id = cases_by_id([{'cases': rows} for rows in selected])
    # A missing case is not imputed a numerical error. Counts retain the expected
    # denominator, and a case must pass every observed replay to pass this summary.
    passed = sum(len(rows) == len(samples) and all(r.get('scientific_pass') is True for r in rows)
                 for rows in by_id.values())
    return {'expected_cases': expected, 'observed_cases': len(by_id),
            'replays_observed': len(samples), 'passed_all_observed_replays': passed,
            'passed_per_replay': [sum(r.get('scientific_pass') is True for r in rows) for rows in selected],
            'metrics': {m: summary([r.get(m) for rows in selected for r in rows]) for m in METRICS[task]},
            'failures': [{'id': name, 'observations': rows} for name, rows in by_id.items()
                         if len(rows) != len(samples) or not all(r.get('scientific_pass') is True for r in rows)]}


def resources(samples):
    return {name: summary([sample.get('worker', {}).get(name) for sample in samples])
            for name in ('execution_wall_seconds', 'cpu_seconds', 'memory_peak_bytes')}


def model_request_audit(root):
    relay = Path(root) / 'relay-evidence/evidence/events.jsonl'
    if not relay.exists():
        relay = Path(root) / 'relay-evidence/events.jsonl'
    if not relay.exists():
        return {'observed': False}
    events = [json.loads(line) for line in relay.read_text().splitlines()]
    accepted = [r for r in events if r.get('event') == 'request_accepted']
    finished = [r for r in events if r.get('event') == 'request_finished']
    failed = [r for r in finished if r.get('outcome') != 'success']
    started = {r['request_id']: r.get('timestamp') for r in accepted}
    def request_seconds(row):
        start, end = started.get(row['request_id']), row.get('timestamp')
        return end - start if finite(start) and finite(end) and end >= start else None
    failure_times = [request_seconds(r) for r in failed]
    native = Path(root) / 'auxiliary-agent/pi.txt'
    native_retries = []
    if native.exists():
        for line in native.read_text(errors='replace').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') == 'auto_retry_start':
                native_retries.append(event)
    caps = sorted({r['effective_max_tokens'] for r in accepted if r.get('effective_max_tokens') is not None})
    assert all(0 < cap <= 16384 for cap in caps)
    return {'observed': True, 'request_count': len(accepted), 'effective_request_caps': caps,
            'largest_observed_output_tokens': max((r.get('output_tokens') or 0 for r in finished), default=0),
            'requests_with_output_over_4096': sum((r.get('output_tokens') or 0) > 4096 for r in finished),
            'native_compaction_requests': sum(r.get('request_kind') == 'native_compaction' for r in accepted),
            'one_token_requests': sum(r.get('effective_max_tokens') == 1 for r in accepted),
            'budget_reminders': sum(r.get('event') == 'research_budget_reminder' for r in events),
            'failed_requests': len(failed), 'failure_outcomes': dict(Counter(r.get('outcome') for r in failed)),
            'failed_request_wall_seconds': sum(t for t in failure_times if t is not None),
            'failed_request_durations_missing': sum(t is None for t in failure_times),
            'failed_request_known_output_tokens': sum(r.get('output_tokens') or 0 for r in failed),
            'failed_requests_with_unknown_output': sum(r.get('output_tokens') is None for r in failed),
            'failed_request_charged_output_tokens': sum(r.get('charged_output_tokens') or 0 for r in failed),
            'native_request_retry_count': len(native_retries),
            'native_request_retry_declared_backoff_seconds': sum(r.get('delayMs', 0) for r in native_retries)/1000,
            'note': '16384 is an upper bound. Native compaction and continuation/context allowance can request fewer tokens. Failed-request duration is observed occupied time, not counterfactual overhead; it remains included in total cost. Unknown output is not zero actual usage. Native request retries do not create scientific sessions or linked research attempts.'}


def timing(record):
    if not record:
        return None
    return {k: record.get(k) for k in ('evaluation_status', 'performance_status', 'speedup',
            'formal_timing', 'measurement_attempts', 'selected_window', 'selection_policy', 'timing_attempts')}


def main():
    closure = read(LOG / 'research-closure.json')
    assert closure['all_nine_closed'] and closure['status'] == 'passed'
    raw = read(OUT / 'results.json')
    assert raw['status'] == 'scoring_completed' and raw['scientific_sessions'] == 9
    plan = checked(raw['plan'])
    assert len(plan['runs']) == len(raw['rows']) == 9
    ledger_path = ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json'
    ledger = read(ledger_path)
    # The live ledger adds replay references after closure. Recover its exact
    # pre-scoring bytes and require the independently recorded closure hash.
    # This is a hash-verified recovery, not a replacement of any run record.
    closed_ledger = copy.deepcopy(ledger)
    closed_ledger['finalized_tasks'] = []
    for entry in closed_ledger['attempts']:
        entry.pop('replay', None)
        entry.pop('replay_started_at', None)
    closed_bytes = (json.dumps(closed_ledger, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    assert hashlib.sha256(closed_bytes).hexdigest() == closure['manifest_sha256']
    closed_path = OUT / 'research-closure-manifest.json'
    closed_path.write_bytes(closed_bytes)
    timeline = read(OUT / 'exploration-timeline.json')
    timeline_by_id = {a['attempt_id']: a for a in timeline['attempts']}
    latest = {}
    attempts = []
    evidence = [ref(PLAN), ref(OUT / 'results.json'), ref(OUT / 'exploration-timeline.json'),
                ref(ledger_path), ref(LOG / 'research-closure.json'), ref(closed_path)]
    supplement = read(OUT / 'numeric-only-supplement.json')
    assert supplement['status'] == 'completed' and not supplement['formal_timing']
    assert not supplement['changes_formal_scores'] and not supplement['candidate_selection_changed']
    assert supplement['service']['restored'] and supplement['new_scientific_sessions'] == 0
    assert checked(supplement['original_results']) == raw
    evidence.append(ref(OUT / 'numeric-only-supplement.json'))
    observation_audit = read(OUT / 'observation-audit.json')
    assert observation_audit['status'] == 'passed'
    evidence.append(ref(OUT / 'observation-audit.json'))
    supplemental = {}
    for group in supplement['groups']:
        assert group['split'] == 'final-test' and len(group['replays']) == 3
        samples = [checked(r) for r in group['replays']]
        evidence.extend(group['replays'])
        for role in group['roles']:
            supplemental[(group['run_id'], role)] = (group, samples)
    for entry in ledger['attempts']:
        host = checked(entry['result'])
        assert host.get('finished_at') is not None
        assert host['finished_at'] <= closure['closed_at']
        latest[entry['run_id']] = entry
        root = (ROOT / entry['registry']['path']).parent.parent if entry.get('registry') else ROOT / 'research-runs' / entry['run_id']
        registry = checked(entry['registry']) if entry.get('registry') else {}
        observed = timeline_by_id[entry['attempt_id']]
        bridge_requests = [path for path in sorted((root / 'file-bridge/requests').glob('*.json'))
                           if not path.name.endswith('.delivery.json')]
        public_requests = [path for path in bridge_requests if read(path).get('request', {}).get('operation') == 'evaluate']
        observed['summary']['received_public_evaluation_requests'] = len(public_requests)
        evidence.extend(ref(path) for path in public_requests)
        for name, digest in observed['evidence_sha256'].items():
            assert ref(root / name)['sha256'] == digest
        duration = ((host.get('research_stop_requested_at') or host['finished_at']) - registry['started_at']) if registry.get('started_at') else None
        attempts.append({'run_id': entry['run_id'], 'attempt_id': entry['attempt_id'],
                         'parent_attempt': entry.get('parent_attempt'), 'status': host['attempt_status'],
                         'host_wall_seconds': host['finished_at'] - host['started_at'],
                         'research_wall_seconds': duration, 'registry_root': str(root.relative_to(ROOT)),
                         'host': entry['result'], 'summary': observed['summary'],
                         'model_request_audit': model_request_audit(root)})
        evidence.append(entry['result'])
        if entry.get('registry'):
            evidence.append(entry['registry'])
    assert len(attempts) <= 18
    earliest_test = min(e['replay_started_at'] for e in ledger['attempts'] if e.get('replay_started_at'))
    assert closure['closed_at'] < earliest_test
    rows, case_rows = [], []
    order = {task: n for n, task in enumerate(('heat', 'ode', 'poisson'))}
    for item in sorted(raw['rows'], key=lambda r: (order[r['run']['task']], r['run']['group'])):
        run = item['run']; task = run['task']; run_id = run['run_id']
        entry = latest[run_id]
        assert entry['attempt_id'] == item['attempt']['attempt_id']
        if entry.get('replay'):
            assert checked(entry['replay']) == item['main']
            evidence.append(entry['replay'])
        d = item['main']['diagnostics']
        first, final = d.get('first'), d.get('final')
        a = next(a for a in attempts if a['attempt_id'] == entry['attempt_id'])
        related = [a for a in attempts if a['run_id'] == run_id]
        normalized = {'run_id': run_id, 'label': f"{task.title() if task != 'ode' else 'ODE'} {run['group'].upper()} r1",
                      'task': task, 'group': run['group'], 'sequence': run['sequence'],
                      'attempt_id': entry['attempt_id'], 'host_status': item['host_status'],
                      'attempt_count': len(related), 'evaluation_status': d['evaluation_status'],
                      'first_score': first.get('score') if first else None,
                      'final_score': d.get('score'), 'reward': d.get('reward'),
                      'first': first, 'final': final, 'exploration': a['summary'],
                      'research_wall_seconds': a['research_wall_seconds'],
                      'all_attempt_known_output_tokens': sum(x['summary']['known_output_tokens'] for x in related),
                      'all_attempt_charged_output_tokens': sum(x['summary']['charged_output_tokens'] for x in related),
                      'all_attempt_host_wall_seconds': sum(x['host_wall_seconds'] for x in related),
                      'all_attempt_research_wall_seconds': sum(x['research_wall_seconds'] or 0 for x in related),
                      'selection_reason': d.get('selection_reason'),
                      'reason': d.get('reason') or (final or {}).get('reason') or item['main'].get('reason')}
        normalized['main_numeric'] = {}
        for role, record in (('first', first), ('final', final)):
            samples = checkpoint_samples(record)
            numeric_origin = 'frozen_protocol_replay'
            if (run_id, role) in supplemental:
                assert task == 'poisson' and not samples and d['score'] is None
                group, samples = supplemental[(run_id, role)]
                assert record['source_hash'] == group['source_hash']
                numeric_origin = 'accuracy_only_supplement_no_formal_timing'
            normalized['main_numeric'][role] = {'overall': numeric_summary(samples, task, 12),
                'numeric_origin': numeric_origin,
                'by_level': {str(level): numeric_summary(samples, task, 4, level=level) for level in range(3)},
                'resources': resources(samples),
                'timing': timing(record['repeats'][0]) if task == 'poisson' and record and record.get('repeats') else None,
                'reused_from': (record or {}).get('reused_from')}
            for i, sample in enumerate(samples):
                case_rows.extend({'run_id': run_id, 'task': task, 'group': run['group'], 'split': 'final-test',
                                  'role': role, 'order': 'forward', 'replay': i + 1, 'numeric_origin': numeric_origin, **r} for r in sample.get('cases', []))
        diagnostic = item['diagnostic']
        profiles = diagnostic.get('profiles', {})
        normalized['diagnostic_status'] = diagnostic['status']
        normalized['diagnostics'] = {}
        for profile in PROFILES[task]:
            for direction in (('forward', 'reverse') if profile == 'cache_order' else ('forward',)):
                key = f'diagnostic-test/{profile if task == "poisson" else "all"}/{direction}'
                result = profiles.get(key, {})
                samples = numeric_samples(result)
                key2 = profile + '/' + direction
                normalized['diagnostics'][key2] = {'numeric': numeric_summary(samples, task, 4, profile=profile),
                    'resources': resources(samples), 'resource_scope': 'theme_batch' if task == 'poisson' else 'all_12_diagnostic_cases',
                    'timing': timing(result) if task == 'poisson' else None,
                    'evaluation_status': result.get('evaluation_status', diagnostic['status'])}
                for i, sample in enumerate(samples):
                    case_rows.extend({'run_id': run_id, 'task': task, 'group': run['group'], 'split': 'diagnostic-test',
                                      'role': 'final', 'order': direction, 'replay': i + 1, **r}
                                     for r in sample.get('cases', []) if r.get('profile_id') == profile)
        rows.append(normalized)
    for row in rows:
        for key in ('first_score', 'final_score'):
            assert row[key] is None or finite(row[key]) and 0 <= row[key] <= 100
        if row['evaluation_status'] != 'valid':
            assert row['final_score'] is None and row['reward'] is None
    for name in ('gt-qc.json', 'rule-fixtures.json', 'offline-acceptance.json', 'main-calibration/summary.json',
                 'diagnostic-calibration/summary.json', 'timing-calibration/summary.json', 'freeze-validation.json',
                 'unit-acceptance.json', 'executor-validation.json', 'provider-documentation.json',
                 'study-service-restoration.json'):
        evidence.append(ref(LOG / name))
    assert read(LOG / 'gt-qc.json')['count'] == 162
    value = {'scope': 'optimized_r1_nine_only', 'plan_id': plan['plan_id'], 'scientific_sessions': 9,
             'data_instances': 162, 'hidden_scoring_after_all_nine_closed': True,
             'research_closed_at': closure['closed_at'], 'first_hidden_scoring_at': earliest_test,
             'rows': rows, 'attempts': attempts,
             'totals': {'attempts': len(attempts), 'valid_main_results': sum(r['evaluation_status'] == 'valid' for r in rows),
                        'reward_one': sum(r['reward'] == 1 for r in rows),
                        'registered_final_candidates': sum(bool((r['final'] or {}).get('source_hash')) for r in rows),
                        'known_output_tokens_all_attempts': sum(a['summary']['known_output_tokens'] for a in attempts),
                        'charged_output_tokens_all_attempts': sum(a['summary']['charged_output_tokens'] for a in attempts),
                        'research_wall_seconds_all_attempts': sum(a['research_wall_seconds'] or 0 for a in attempts),
                        'host_wall_seconds_all_attempts': sum(a['host_wall_seconds'] for a in attempts)},
             'source_evidence': evidence, 'case_observation_count': len(case_rows),
             'accuracy_only_supplement': ref(OUT / 'numeric-only-supplement.json'),
             'interpretation': 'Replay rows are repeated observations, not independent agent samples. Null is infrastructure/timing invalidity; legal scientific failures remain zero. Accuracy-only supplemental outputs are explicitly tagged and never fill formal timing scores. Diagnostic results never contribute to main score.'}
    (OUT / 'analysis.json').write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    (OUT / 'case-results.json').write_text(json.dumps(case_rows, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    keys = sorted({k for r in case_rows for k in r})
    with (OUT / 'case-results.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys); writer.writeheader()
        for row in case_rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    print(json.dumps({'status': 'analyzed', **value['totals'], 'case_observations': len(case_rows)}))


if __name__ == '__main__':
    main()
