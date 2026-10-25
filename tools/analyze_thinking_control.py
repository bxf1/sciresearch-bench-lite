"""Reconcile the closed thinking/max study from immutable JSON evidence; no execution."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = 'research-98719c3c1cf3fc92'
OLD = 'research-6615cd7900ba0750'
LOG = 'logs/thinking-control-2026-10-25'
OUT = ROOT / 'results/thinking-control-2026-10-25'
SOURCES = {}


def read(name):
    data = (ROOT / name).read_bytes()
    SOURCES[name] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def reference(ref):
    value = read(ref['path'])
    assert SOURCES[ref['path']] == ref['sha256'], ref['path']
    return value


def short(checkpoint):
    if not checkpoint:
        return None
    return {k: checkpoint.get(k) for k in ('checkpoint_id', 'source_hash', 'score',
            'reward', 'evaluation_status', 'replay_count', 'reused_from')}


def main():
    manifest = read(f'research-runs/{PLAN}/manifest.json')
    reference(manifest['run_plan'])
    assert manifest['run_plan']['sha256'] == '25c3250f8615aa5a90a24206964533085b5448f06910f7e42a969e2f66763f0e'
    summary = read('results/thinking-control-2026-10-25/summary.json')
    assert summary['manifest_sha256'] == SOURCES[f'research-runs/{PLAN}/manifest.json']
    state = read(f'{LOG}/state.json')
    assert state['all_15_research_closed'] and state['stage'] == 'results_ready_for_review'
    operations = read(f'{LOG}/scoring-operations.json')['operations']
    assert len(operations) == 26 and Counter(o['exit_code'] for o in operations) == {0: 23, 2: 3}
    refusals = []
    for operation in operations:
        if operation['exit_code'] != 2:
            continue
        name = f"{LOG}/window-{operation['kind']}-{operation['task']}-{operation['identity']}/acceptance.json"
        acceptance = read(name)
        assert acceptance['status'] in ('rejected', 'host_preflight_rejected')
        observations = (ROOT / name).parent / 'host-observations.jsonl'
        assert hashlib.sha256(observations.read_bytes()).hexdigest() == acceptance['host_observations_sha256']
        refusals.append({**operation, 'acceptance_path': name, 'acceptance_sha256': SOURCES[name],
                         'acceptance': acceptance, 'terminal_for_this_batch': True})

    attempts, latest = [], {}
    for entry in manifest['attempts']:
        host = reference(entry['result'])
        registry = reference(entry['registry'])
        assert registry['closed'] and host['relay_cleanup']['all_removed']
        assert not host['cleanup_errors'] and host['worker_cleanup']['all_removed']
        limits = host['relay_status']['limits']
        assert limits['request_output_limit'] == 4096 and limits['session_output_limit'] == 200000
        assert limits['thinking'] == {'type': 'enabled'} and limits['output_config'] == {'effort': 'max'}
        assert host['research_budget_seconds'] == 1800 and host['max_evaluations'] == 20
        path = entry['relay_events']['path']
        raw = (ROOT / path).read_bytes()
        SOURCES[path] = hashlib.sha256(raw).hexdigest()
        assert SOURCES[path] == entry['relay_events']['sha256']
        events = [json.loads(line) for line in raw.splitlines()]
        finished = [e for e in events if e['event'] == 'request_finished']
        known_output = sum(e.get('output_tokens') or 0 for e in finished)
        charged = sum(e['charged_output_tokens'] for e in finished)
        assert charged == host['relay_status']['charged_output_tokens'] <= 200000
        assert len(finished) == host['relay_status']['request_count']
        replay = reference(entry['replay'])['diagnostics'] if entry.get('replay') else {}
        for role in ('first', 'final'):
            cp = replay.get(role)
            if cp and cp.get('checkpoint_id'):
                candidate = next(e for e in registry['evaluations'] if e['id'] == cp['checkpoint_id'])
                assert candidate['source_hash'] == cp['source_hash']
        final_id = registry['final_id']
        candidate_valid = bool(final_id and next(e for e in registry['evaluations'] if e['id'] == final_id)['artifact_valid'])
        row = {'run_id': entry['run_id'], 'attempt_id': entry['attempt_id'],
               'parent_attempt': entry['parent_attempt'], 'task': host['task'], 'group': host['group'],
               'repeat': host['repeat'], 'raw_status': host['attempt_status'],
               'first_id': registry['first_id'], 'final_id': final_id, 'valid_public_candidate': candidate_valid,
               'public_evaluations': len(registry['evaluations']), 'known_output_tokens': known_output,
               'charged_output_tokens': charged, 'successful_requests': host['relay_status']['successful_requests'],
               'failed_requests': host['relay_status']['failed_requests'],
               'context_clamped_one_token_responses': sum(e.get('effective_max_tokens') == 1 for e in finished),
               'input_tokens': sum(e.get('input_tokens') or 0 for e in finished),
               'cache_read_input_tokens': sum(e.get('cache_read_input_tokens') or 0 for e in finished),
               'started_at': host['started_at'], 'finished_at': host['finished_at'],
               'attempt_wall_seconds': host['finished_at'] - host['started_at'],
               'research_wall_seconds': registry['attempt_outcome']['recorded_at'] - registry['started_at'],
               'first': short(replay.get('first')), 'final': short(replay.get('final')),
               'host_evidence': entry['result'], 'registry_evidence': entry['registry'],
               'replay_evidence': entry.get('replay'), 'relay_evidence': entry['relay_events'],
               'host_infrastructure_sha256': {k: v for k, v in host['trusted_source_sha256'].items()
                    if k in ('runner/model_relay.py', 'runner/harbor_pilot.py', 'runner/relay_transport.py')},
               'native_infrastructure': host.get('native_setup_evidence')}
        attempts.append(row)
        latest[row['run_id']] = row
    assert len(attempts) == 17 and len(latest) == 15
    assert all(r['valid_public_candidate'] for r in latest.values())
    assert max(r['finished_at'] for r in attempts) < min(reference(b['result'])['started_at'] for b in manifest['baselines'])
    assert max(r['finished_at'] for r in attempts) < min(e['replay_started_at'] for e in manifest['attempts'] if e.get('replay_started_at'))

    old_manifest = read(f'research-runs/{OLD}/manifest.json')
    old_latest = {}
    for entry in old_manifest['attempts']:
        if entry.get('replay'):
            old_latest[entry['run_id'].replace(OLD, PLAN)] = reference(entry['replay'])['diagnostics']
    pairs = []
    for run_id, row in latest.items():
        before = short(old_latest[run_id]['final'])
        after = row['final']
        rejection = next((r for r in refusals if r['identity'] == run_id), None)
        valid = bool(after and after['evaluation_status'] == 'valid')
        comparable = bool(valid and before['evaluation_status'] == 'valid')
        delta = after['score'] - before['score'] if comparable else None
        first = row['first']
        within_delta = after['score'] - first['score'] if valid and first['evaluation_status'] == 'valid' else None
        pairs.append({'task': row['task'], 'group': row['group'], 'repeat': row['repeat'],
                      'run_id': run_id, 'attempt_id': row['attempt_id'], 'before': before, 'after': after,
                      'terminal_status': 'valid' if valid else rejection['acceptance']['status'],
                      'refusal_evidence': rejection['acceptance_path'] if rejection else None,
                      'comparable': comparable, 'delta_score': delta,
                      'paired_direction': 'unavailable' if delta is None else 'improved' if delta > 1e-9 else 'declined' if delta < -1e-9 else 'unchanged',
                      'first_final_delta': within_delta,
                      'first_final_direction': 'unavailable' if within_delta is None else 'same_source' if first['source_hash'] == after['source_hash'] else 'improved' if within_delta > 1e-9 else 'declined' if within_delta < -1e-9 else 'unchanged_score'})
    valid = [p for p in pairs if p['terminal_status'] == 'valid']
    assert len(valid) == 13 and all(p['after']['reward'] == 1 for p in valid)
    retained = list(latest.values())
    result = {'schema_version': 1, 'status': 'reviewed_terminal', 'plan_id': PLAN,
              'research_sessions': 15, 'attempts': 17, 'valid_public_submissions': 15,
              'valid_final_scores': 13, 'reward_one': 13, 'timing_rejected_sessions': 2,
              'scientific_no_submission': 0, 'author_baselines_valid': 10, 'author_baselines_refused': 1,
              'global_research_closure_verified': True,
              'latest_research_finished_at': max(r['finished_at'] for r in attempts),
              'first_baseline_started_at': min(reference(b['result'])['started_at'] for b in manifest['baselines']),
              'paired_directions': dict(Counter(p['paired_direction'] for p in pairs)),
              'first_final_directions': dict(Counter(p['first_final_direction'] for p in pairs)),
              'retained_usage': {k: sum(r[k] for r in retained) for k in ('known_output_tokens', 'charged_output_tokens', 'successful_requests', 'failed_requests', 'research_wall_seconds', 'public_evaluations')},
              'all_attempt_usage': {k: sum(r[k] for r in attempts) for k in ('known_output_tokens', 'charged_output_tokens', 'successful_requests', 'failed_requests', 'attempt_wall_seconds')},
              'attempt_records': attempts, 'pairs': pairs, 'timing_refusals': refusals,
              'author_baselines': summary['baseline_methods'],
              'raw_summary_pending_interpretation': 'The two pending runs and one pending baseline are terminal timing refusals in this batch, not running work.',
              'new_model_calls_during_analysis': 0, 'new_candidate_executions_during_analysis': 0,
              'limitations': ['Post-hoc matched control; thinking and max changed together, temperature is inactive.',
                              'Same previously used hidden set, sequential conditions, one host and small samples.',
                              'Infrastructure changed mid-batch; linked retries are not independent scientific samples.',
                              'Heat G1 r1 a002 includes 252 no-progress one-token continuations; raw timeout retained.',
                              'Timing refusals stay null; do not combine both batches into 30 identical-condition samples.'],
              'source_sha256': dict(sorted(SOURCES.items()))}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'reviewed-comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('attempt_records', 'pairs', 'timing_refusals', 'source_sha256', 'author_baselines')}, ensure_ascii=False, indent=2))
    for p in pairs:
        print(p['task'], p['group'], p['repeat'], p['before']['score'], p['after']['score'] if p['after'] else None, p['delta_score'], p['first_final_delta'])


if __name__ == '__main__':
    main()
