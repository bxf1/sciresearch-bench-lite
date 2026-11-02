"""Standard-library, read-only verification of this independent local delivery."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/optimized-r1-20261101'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    manifest = read(OUT / 'delivery-manifest.json')
    assert manifest['scope'] == 'optimized_r1_nine_only'
    for row in manifest['files']:
        path = (ROOT / row['path']).resolve(strict=True)
        assert path.is_relative_to(ROOT) and path.is_file(), row['path']
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], row['path']
    raw, analysis = read(OUT / 'results.json'), read(OUT / 'analysis.json')
    assert raw['status'] == 'scoring_completed'
    expected = {(task, group, 1) for task in ('heat', 'ode', 'poisson') for group in ('g1', 'g2', 'g3')}
    assert {(r['run']['task'], r['run']['group'], r['run']['repeat']) for r in raw['rows']} == expected
    assert len(raw['rows']) == analysis['scientific_sessions'] == 9
    assert analysis['research_closed_at'] < analysis['first_hidden_scoring_at']
    counts = {'public-dev': 6, 'author-calibration': 12, 'final-test': 12,
              'diagnostic-calibration': 12, 'diagnostic-test': 12}
    identifiers = []
    for task in ('heat', 'ode', 'poisson'):
        for split, count in counts.items():
            data = read(ROOT / 'authoring/data/optimized-r1-20261101/inputs' / task / split / 'manifest.json')
            assert len(data['cases']) == count
            identifiers.extend(row['id'] for row in data['cases'])
    assert len(identifiers) == len(set(identifiers)) == analysis['data_instances'] == 162
    for row in analysis['rows']:
        d = next(r for r in raw['rows'] if r['run']['run_id'] == row['run_id'])['main']['diagnostics']
        assert (row['final_score'], row['reward']) == (d.get('score'), d.get('reward'))
    supplement = read(OUT / 'numeric-only-supplement.json')
    assert supplement['status'] == 'completed' and supplement['service']['restored']
    assert supplement['new_scientific_sessions'] == 0 and not supplement['changes_formal_scores']
    assert supplement['original_results']['sha256'] == sha(OUT / 'results.json')
    audit, visual = read(OUT / 'report-audit.json'), read(OUT / 'pdf-visual-review.json')
    pdf = ROOT / audit['pdf']['path']
    assert audit['status'] == visual['status'] == 'passed'
    assert audit['pdf']['sha256'] == visual['pdf']['sha256'] == sha(pdf)
    assert visual['reviewed_pages'] == list(range(1, len(audit['pdf']['pages']) + 1))
    assert audit['pdf']['all_fonts_embedded'] and audit['pdf']['raster_images'] == 0
    assert read(ROOT / 'logs/optimized-r1-20261101/study-service-restoration.json')['restored']
    preserved = read(ROOT / 'archives/pre-optimized-r1-20261101/preserved-reports.json')
    for row in preserved['files']:
        assert sha(ROOT / row['path']) == row['sha256'], row['path']
    print(json.dumps({'status': 'passed', 'files_verified': len(manifest['files']),
                      'scientific_sessions': 9, 'data_instances': 162, 'pdf_pages': len(visual['reviewed_pages']),
                      'new_model_calls': 0, 'new_candidate_executions': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
