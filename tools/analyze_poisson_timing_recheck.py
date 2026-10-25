"""Review separately authorized timing measurements without replacing old evidence."""
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = 'logs/poisson-timing-recheck-2026-10-25'
OUT = ROOT / 'results/poisson-timing-recheck-2026-10-25'
SOURCES = {}


def read(name):
    data = (ROOT / name).read_bytes()
    SOURCES[name] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def verified(ref):
    value = read(ref['path'])
    assert SOURCES[ref['path']] == ref['sha256'], ref['path']
    return value


def main():
    original = read('results/thinking-control-2026-10-25/reviewed-comparison.json')
    authorization = read(f'{LOG}/authorization.json')
    completion = read(f'{LOG}/completion.json')
    assert completion['status'] == 'measurements_closed'
    assert completion['model_calls'] == completion['research_launches'] == 0
    assert hashlib.sha256((ROOT / f'{LOG}/controller.py').read_bytes()).hexdigest() == authorization['controller_sha256']
    bindings = {r['run_id']: r for r in authorization['validated_candidates']}
    pairs = copy.deepcopy(original['pairs'])
    measured, windows = [], []
    for outcome in completion['outcomes']:
        group = bindings[outcome['run_id']]['group']
        base = f"{LOG}/{group}-window-{outcome['window']:03d}"
        accepted = read(base + '/acceptance.json')
        assert accepted == outcome
        observation = ROOT / base / 'host-observations.jsonl'
        SOURCES[base + '/host-observations.jsonl'] = hashlib.sha256(observation.read_bytes()).hexdigest()
        assert SOURCES[base + '/host-observations.jsonl'] == accepted['host_observations_sha256']
        verified(outcome['parent_refusal'])
        if outcome['parent_replay']:
            verified(outcome['parent_replay'])
        record = {'run_id': outcome['run_id'], 'window': outcome['window'], 'status': outcome['status'],
                  'acceptance_path': base + '/acceptance.json', 'model_calls': 0, 'research_launches': 0,
                  'final_test_scores_accessed': outcome['final_test_scores_accessed']}
        windows.append(record)
        if not outcome.get('operation_result'):
            assert outcome['status'] == 'host_preflight_rejected' and not outcome['final_test_scores_accessed']
            continue
        value = verified(outcome['operation_result'])
        binding = bindings[outcome['run_id']]
        assert value['registry_sha256'] == binding['registry']['sha256']
        registry = verified(binding['registry'])
        assert registry['closed']
        first, final = value['diagnostics']['first'], value['diagnostics']['final']
        for role, cp in (('first', first), ('final', final)):
            assert cp['checkpoint_id'] == binding[role + '_id']
            assert cp['source_hash'] == binding['source_hashes'][role]
        valid = outcome['status'] == 'passed'
        if valid:
            assert not outcome['violations'] and not outcome['observer_errors'] and outcome['no_running_containers']
            assert value['diagnostics']['evaluation_status'] == 'valid'
            for cp in (first, final):
                assert all(r['formal_evidence_valid'] and r['formal_timing'] for r in cp['repeats'])
        current = next(p for p in pairs if p['run_id'] == outcome['run_id'])
        current['initial_control_result'] = copy.deepcopy(current['after'])
        current['timing_recheck'] = outcome['operation_result']
        selected = {k: final.get(k) for k in ('checkpoint_id', 'source_hash', 'score', 'reward', 'evaluation_status', 'replay_count', 'reused_from')}
        if not valid:
            selected.update(score=None, reward=None, evaluation_status='invalid')
        current['after'] = selected
        current['terminal_status'] = 'valid' if valid else outcome['status']
        current['refusal_evidence'] = None if valid else record['acceptance_path']
        comparable = valid and current['before']['evaluation_status'] == 'valid'
        delta = final['score'] - current['before']['score'] if comparable else None
        change = final['score'] - first['score'] if valid else None
        current.update(comparable=comparable, delta_score=delta,
                       paired_direction='unavailable' if delta is None else 'improved' if delta > 1e-9 else 'declined' if delta < -1e-9 else 'unchanged',
                       first_final_delta=change,
                       first_final_direction='unavailable' if change is None else 'same_source' if first['source_hash'] == final['source_hash'] else 'improved' if change > 1e-9 else 'declined' if change < -1e-9 else 'unchanged_score')
        measured.append({**record, 'original_attempt_id': value['attempt_id'], 'parent_refusal': outcome['parent_refusal'],
                         'parent_replay': outcome['parent_replay'], 'operation_result': outcome['operation_result'],
                         'first': {k: first.get(k) for k in ('checkpoint_id', 'source_hash', 'score', 'reward', 'evaluation_status')},
                         'final': selected, 'first_speedup': first['repeats'][0].get('speedup') if valid else None,
                         'final_speedup': final['repeats'][0].get('speedup') if valid else None,
                         'independent_research_sample': False})
    assert len(measured) == 2 and len({r['run_id'] for r in measured}) == 2
    result = {'schema_version': 1, 'status': 'reviewed', 'research_sessions': 15, 'research_attempts': 17,
              'new_research_sessions': 0, 'new_model_calls': 0, 'new_admitted_timing_measurements': len(measured),
              'admission_only_refusals': sum(r['status'] == 'host_preflight_rejected' for r in windows),
              'valid_final_scores': sum(p['terminal_status'] == 'valid' for p in pairs),
              'reward_one': sum(p['terminal_status'] == 'valid' and p['after']['reward'] == 1 for p in pairs),
              'timing_invalid_sessions': sum(p['terminal_status'] != 'valid' for p in pairs),
              'original_published_valid_scores': original['valid_final_scores'],
              'author_baselines_valid': 10, 'author_baselines_refused': 1,
              'research_usage_unchanged': original['all_attempt_usage'],
              'original_evidence_files_verified_unchanged': completion['original_files_unchanged'],
              'paired_directions': dict(Counter(p['paired_direction'] for p in pairs)),
              'first_final_directions': dict(Counter(p['first_final_direction'] for p in pairs)),
              'measurements': measured, 'windows': windows, 'pairs': pairs,
              'limitations': original['limitations'] + ['The newly authorized timing windows occur after publication; their scores are separately dated observations of unchanged sources, not new independent research samples.'],
              'source_sha256': dict(sorted(SOURCES.items()))}
    OUT.mkdir(exist_ok=True, parents=True)
    (OUT / 'reviewed-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('measurements', 'pairs', 'source_sha256', 'windows', 'limitations')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
