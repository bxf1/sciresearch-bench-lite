"""Read-only audit of host observation continuity and saved cache-order outputs."""
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/optimized-r1-20261101'


def read(path):
    return json.loads(Path(path).read_text())


def ref(path):
    return {'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    ledger = read(ROOT / 'research-runs/research-194b4260e84e36bb/manifest.json')
    raw = read(OUT / 'results.json')
    roots = []
    for attempt in ledger['attempts']:
        if 'poisson' in attempt['run_id']:
            roots.append((ROOT / attempt['replay']['path']).parent / 'replays')
    roots.append(OUT / 'diagnostics')
    windows = []
    for base in roots:
        for path in sorted(base.rglob('acceptance.json')):
            if not path.parent.name.startswith('window-'):
                continue
            acceptance = read(path)
            observations_path = path.parent / 'host-observations.jsonl'
            assert ref(observations_path)['sha256'] == acceptance['host_observations_sha256']
            observations = [json.loads(line) for line in observations_path.read_text().splitlines()]
            times = [o['unix'] for o in observations]
            gaps = [b - a for a, b in zip(times, times[1:])]
            assert all(g > 0 for g in gaps)
            row = {'acceptance': ref(path), 'observations': ref(observations_path),
                   'policy': ref(path.parent / 'observation-policy.json'),
                   'status': acceptance['status'], 'measured': acceptance['measured'],
                   'observations_count': len(times), 'maximum_gap_seconds': max(gaps),
                   'first_unix': times[0], 'last_unix': times[-1],
                   'elapsed_seconds': times[-1] - times[0]}
            if acceptance['status'] == 'valid':
                qualified = read(path.parent / 'qualified-result.json')
                evidence = qualified['protocol_attempt']['evidence']
                start, end = evidence['window_started_unix'], evidence['window_finished_unix']
                assert times[0] < start < end < times[-1]
                assert not acceptance['violations'] and not acceptance['errors']
                assert qualified['performance_status'] == 'valid'
                row.update(measurement_window_seconds=end-start, coverage_verified=True)
            windows.append(row)
    comparisons = []
    for item in raw['rows']:
        if item['run']['task'] != 'poisson':
            continue
        rid = item['run']['run_id']
        files = {}
        for direction in ('forward', 'reverse'):
            record = item['diagnostic']['profiles']['diagnostic-test/cache_order/' + direction]
            assert record['performance_status'] == 'valid'
            root = OUT / 'diagnostics' / rid / ('diagnostic-test-cache_order-' + direction)
            root = root / f"window-{record['selected_window']:02d}" / 'measurement'
            files[direction] = {(sample, p.parent.name): p for sample in ('2-C', '3-C', '6-C')
                                for p in (root / sample / 'worker/artifacts/cases').glob('*/solution.npy')}
        assert files['forward'].keys() == files['reverse'].keys() and len(files['forward']) == 12
        for key, forward in files['forward'].items():
            reverse = files['reverse'][key]
            a, b = np.load(forward, allow_pickle=False), np.load(reverse, allow_pickle=False)
            assert a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
            comparisons.append({'run_id': rid, 'sample': key[0], 'case_id': key[1],
                'forward': ref(forward), 'reverse': ref(reverse),
                'bitwise_equal': forward.read_bytes() == reverse.read_bytes(),
                'relative_l2_difference': float(np.linalg.norm(a-b) / max(np.linalg.norm(a), 1e-300))})
    selected = [w for w in windows if w['status'] == 'valid']
    value = {'status': 'passed', 'scope': 'saved_outputs_only_no_new_execution',
             'windows': windows, 'selected_valid_windows': len(selected),
             'selected_maximum_observation_gap_seconds': max(w['maximum_gap_seconds'] for w in selected),
             'all_windows_maximum_observation_gap_seconds': max(w['maximum_gap_seconds'] for w in windows),
             'cache_order_comparisons': comparisons,
             'all_cache_outputs_bitwise_equal': all(c['bitwise_equal'] for c in comparisons),
             'note': 'Gap durations are descriptive audits, not a newly introduced pass/fail criterion. Only predeclared accepted windows supply official timings. Cache comparisons use all three selected C samples per direction and do not select the best output.'}
    (OUT / 'observation-audit.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print({k: v for k, v in value.items() if k not in ('windows', 'cache_order_comparisons', 'note')})


if __name__ == '__main__':
    main()
