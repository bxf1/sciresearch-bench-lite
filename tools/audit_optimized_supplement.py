"""Audit saved supplemental evidence without changing scientific selections."""
import json
import math
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runner.common import canonical, digest, file_hash, read_json, write_json
from runner.exploration import attempt_timeline
from runner.phase import checked_hashes
from runner.study import closed_research, frozen_plan, read_attempt
from tests.accepted_t3_calibration import POLICY
from tools.analyze_optimized_r1 import checkpoint_samples, numeric_samples, numeric_summary, resources, model_request_audit
from tools.supplement_optimized_failures import OUT, RESULTS, PLAN, OLD, verify_original, ref


def main():
    result = read_json(RESULTS / 'results.json')
    assert result['status'] == 'measurements_closed'
    protocol = read_json(OUT / 'protocol.json')
    assert result['protocol'] == ref(OUT / 'protocol.json')
    plan, plan_ref = frozen_plan(ROOT, PLAN)
    prior, _ = frozen_plan(ROOT, OLD)
    assert plan_ref == protocol['template']
    for key in ('model', 'runtime_policy', 'tool_config', 'resources', 'tasks', 'research_images', 'execution_policy'):
        assert plan[key] == prior[key]
    row, = protocol['authorized_runs']
    ledger = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')
    assert 1 <= len(ledger['attempts']) <= 2
    assert {e['run_id'] for e in ledger['attempts']} == {row['run_id']}
    assert all(rid not in {e['run_id'] for e in ledger['attempts']} for rid in protocol['dormant_template_run_ids'])
    entry = ledger['attempts'][-1]
    host = read_attempt(ROOT, entry)
    assert host['attempt_status'] in ('completed', 'research_timeout')
    registry, state = closed_research(ROOT, entry, row)
    closure = read_json(OUT / 'research-closure.json')
    assert closure['all_authorized_sessions_closed'] and closure['dormant_sessions_launched'] == 0
    assert closure['closed_at'] <= entry['replay_started_at']
    timeline = attempt_timeline((ROOT / entry['registry']['path']).parent.parent)
    assert timeline == {k: v for k, v in read_json(RESULTS / 'exploration-timeline.json').items() if k not in ('scientific_sessions', 'run_id')}
    candidates = []
    for candidate in state['evaluations']:
        if candidate.get('source_hash'):
            source = registry.verified_snapshot(candidate['id'])
            assert digest(canonical(checked_hashes(source))) == candidate['source_hash']
            candidates.append({'id': candidate['id'], 'source_hash': candidate['source_hash'],
                               'files': {name: ref(source / name) for name in checked_hashes(source)}})
    main_result = read_json(RESULTS / 'ode/main-result.json')
    diag_result = read_json(RESULTS / 'ode/diagnostic-result.json')
    d = main_result['diagnostics']
    assert d['score'] == result['ode']['score'] and d['reward'] == result['ode']['reward']
    ode = {'host_status': host['attempt_status'], 'first_score': d['first']['score'], 'final_score': d['score'],
           'reward': d['reward'], 'selection_reason': state['selection_reason'],
           'first': numeric_summary(checkpoint_samples(d['first']), 'ode', 12),
           'final': numeric_summary(checkpoint_samples(d['final']), 'ode', 12),
           'resources': resources(checkpoint_samples(d['final'])), 'candidates': candidates,
           'timeline': timeline['summary'], 'research_seconds': host['research_stop_requested_at'] - state['started_at'],
           'attempt_wall_seconds': host['finished_at'] - host['started_at'],
           'requests': model_request_audit((ROOT / entry['registry']['path']).parent.parent),
           'main_by_level': {str(level): numeric_summary(checkpoint_samples(d['final']), 'ode', 4, level=level) for level in (0, 1, 2)},
           'diagnostic_status': diag_result['status'], 'diagnostics': {}}
    for role in ('first', 'final'):
        record = d[role]
        if record.get('repeats'):
            assert len(record['repeats']) == 3
            assert all(len(r['cases']) == 12 for r in record['repeats'])
            assert math.isclose(record['score'], sum(r['score'] for r in record['repeats']) / 3, abs_tol=1e-10)
    for profile in ('coordinate_scale', 'coordinate_swap', 'stable_cubic'):
        samples = numeric_samples(diag_result.get('result', {}))
        ode['diagnostics'][profile] = numeric_summary(samples, 'ode', 4, profile=profile)
    p = read_json(RESULTS / 'poisson/result.json')
    assert p['new_model_calls'] == p['new_scientific_sessions'] == 0
    assert p['source_hash'] == protocol['poisson']['source_hash']
    assert p['parent_replay'] == protocol['poisson']['parent_replay']
    timing = p['result']
    assert timing['selection_policy'] == 'first_valid_not_fastest'
    assert timing['measurement_attempts'] <= 3 and len(timing['timing_attempts']) <= 12
    windows = []
    for path in sorted((RESULTS / 'poisson/timing').glob('window-*/acceptance.json')):
        acceptance = read_json(path)
        observed_path = path.parent / 'host-observations.jsonl'
        assert acceptance['host_observations_sha256'] == file_hash(observed_path)
        assert read_json(path.parent / 'observation-policy.json') == POLICY
        observed = [json.loads(line) for line in observed_path.read_text().splitlines()]
        times = [v['unix'] for v in observed]
        gaps = [b - a for a, b in zip(times, times[1:])]
        assert all(g > 0 for g in gaps)
        window = {'number': acceptance['number'], 'status': acceptance['status'], 'measured': acceptance['measured'],
                  'observation_count': len(times), 'maximum_gap_seconds': max(gaps), 'acceptance': ref(path)}
        if acceptance['status'] == 'valid':
            qualified = read_json(path.parent / 'qualified-result.json')
            evidence = qualified['protocol_attempt']['evidence']
            assert times[0] < evidence['window_started_unix'] < evidence['window_finished_unix'] < times[-1]
            assert not acceptance['violations'] and not acceptance['errors']
            window['coverage_verified'] = True
        windows.append(window)
    selected = [w for w in windows if w['status'] in ('valid', 'candidate_failed')]
    if timing['selected_window'] is not None:
        assert selected and timing['selected_window'] == selected[0]['number']
    samples = timing['samples']
    times = {k: [v['worker']['execution_wall_seconds'] for v in samples[k]] for k in ('B', 'C')}
    if timing['performance_status'] == 'valid':
        assert len(samples['B']) == len(samples['C']) == 3 and timing['formal_timing']
        assert [r['role'] for r in timing['protocol_attempt']['samples']] == list('BCCBBC')
        assert math.isclose(timing['speedup'], median(times['B']) / median(times['C']), rel_tol=1e-12)
        assert math.isclose(timing['score'], min(100, max(0, 100 * math.log(timing['speedup']) / math.log(8))), rel_tol=1e-10)
    elif timing['performance_status'] == 'candidate_failed':
        assert timing['score'] == 0 and timing['reward'] == 0
    else:
        assert timing['score'] is None and timing['speedup'] is None
    poisson = {'status': timing['performance_status'], 'score': timing['score'], 'reward': timing['reward'],
               'speedup': timing['speedup'], 'numeric': numeric_summary(samples['C'], 'poisson', 12),
               'times': times, 'median_seconds': {k: median(v) if v else None for k, v in times.items()},
               'resources': resources(samples['C']), 'measurement_attempts': timing['measurement_attempts'],
               'admission_windows': len(windows), 'selected_window': timing['selected_window'], 'windows': windows}
    service = read_json(OUT / 'service-restoration.json')
    assert service['restored'] and service['after']['health'] == 'healthy'
    preservation = verify_original()
    analysis = {'status': 'passed', 'scope': 'post_hoc_two_failure_supplement', 'new_scientific_sessions': 1,
                'ode': ode, 'poisson': poisson, 'original_preservation': preservation,
                'service_restored': True, 'protocol': ref(OUT / 'protocol.json'),
                'source_evidence': [ref(RESULTS / 'results.json'), ref(RESULTS / 'ode/main-result.json'),
                    ref(RESULTS / 'ode/diagnostic-result.json'), ref(RESULTS / 'poisson/result.json'),
                    ref(RESULTS / 'exploration-timeline.json'), ref(OUT / 'research-closure.json'), ref(OUT / 'service-restoration.json')]}
    write_json(RESULTS / 'analysis.json', analysis)
    cases = []
    for role in ('first', 'final'):
        for replay, sample in enumerate(checkpoint_samples(d[role]), 1):
            cases.extend({'task': 'ode', 'split': 'main', 'role': role, 'replay': replay, **r} for r in sample['cases'])
    for sample in numeric_samples(diag_result.get('result', {})):
        cases.extend({'task': 'ode', 'split': 'diagnostic', 'role': 'final', 'replay': 1, **r} for r in sample['cases'])
    for replay, sample in enumerate(samples['C'], 1):
        cases.extend({'task': 'poisson', 'split': 'main', 'role': 'final', 'replay': replay, **r} for r in sample['cases'])
    write_json(RESULTS / 'case-results.json', {'rows': cases})
    print(json.dumps({'status': 'passed', 'ode_score': ode['final_score'], 'poisson_score': poisson['score'],
                      'original_files_verified': preservation['files_verified']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
