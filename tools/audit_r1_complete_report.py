"""Verify the integrated report against unchanged source records and PDF bytes."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.analyze_optimized_r1 import checkpoint_samples, numeric_samples, numeric_summary, METRICS, resources

OUT = ROOT / 'results/r1-complete-20261101'
REPORT = ROOT / 'docs/r1-complete-report-20261101.md'
PDF = ROOT / 'output/pdf/sciresearch-r1-complete-report-20261101.pdf'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ref(path):
    return {'path': str(path.relative_to(ROOT)), 'sha256': sha(path)}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def audit(pdf=False):
    a, raw = read(OUT / 'analysis.json'), read(OUT / 'results.json')
    prior = read(ROOT / 'results/optimized-r1-20261101/results.json')
    extra = ROOT / 'results/optimized-r1-supplement-20261101'
    assert a['reported_groups'] == len(a['rows']) == len(raw['rows']) == 9
    assert a['scientific_sessions'] == len(a['attempts']) == 10 and a['data_instances'] == 162
    assert len({r['run_id'] for r in a['attempts']}) == 10
    assert sum(r['reward'] == 1 for r in a['rows']) == 9
    for x in a['source_evidence']:
        assert sha(ROOT / x['path']) == x['sha256']
    closure = read(ROOT / 'logs/optimized-r1-supplement-20261101/research-closure.json')
    ode_ledger = read(ROOT / 'research-runs/research-56e485a96415c456/manifest.json')
    assert closure['closed_at'] < ode_ledger['attempts'][0]['replay_started_at']
    p = read(extra / 'poisson/result.json')
    for row in a['rows']:
        key = (row['task'], row['group'])
        selected = next(x for x in raw['rows'] if (x['run']['task'], x['run']['group']) == key)
        original = next(x for x in prior['rows'] if (x['run']['task'], x['run']['group']) == key)
        if key == ('ode', 'g1'):
            assert selected['main'] == read(extra / 'ode/main-result.json')
            assert selected['diagnostic']['profiles']['diagnostic-test/all/forward'] == read(extra / 'ode/diagnostic-result.json')['result']
        elif key == ('poisson', 'g2'):
            assert selected['main']['diagnostics']['first']['repeats'] == [p['result']]
            assert selected['diagnostic'] == original['diagnostic']
            assert selected['main']['diagnostics']['first']['source_hash'] == p['source_hash']
        else:
            assert selected == original
        d = selected['main']['diagnostics']
        assert row['final_score'] == d['score'] and row['first_score'] == d['first']['score']
        for role in ('first', 'final'):
            samples = checkpoint_samples(d[role]); n = row['main_numeric'][role]
            assert len(samples) == 3 and all(len(s['cases']) == 12 for s in samples)
            assert n['overall'] == numeric_summary(samples, row['task'], 12)
            assert n['resources'] == resources(samples)
            for level in range(3):
                assert n['by_level'][str(level)] == numeric_summary(samples, row['task'], 4, level=level)
            if row['task'] == 'poisson':
                timing = d[role]['repeats'][0]
                times = {r: [x['worker']['execution_wall_seconds'] for x in timing['samples'][r]] for r in ('B', 'C')}
                ratio = median(times['B']) / median(times['C'])
                assert timing['formal_timing'] and timing['performance_status'] == 'valid'
                assert math.isclose(ratio, timing['speedup'], rel_tol=1e-12)
                assert math.isclose(d[role]['score'], 100 * min(1, max(0, math.log(ratio) / math.log(8))), rel_tol=1e-10)
                assert [x['role'] for x in timing['protocol_attempt']['samples']] == list('BCCBBC')
        assert row['main_numeric']['final']['overall']['passed_per_replay'] == [12, 12, 12]
        for name, diag in row['diagnostics'].items():
            profile, direction = name.split('/')
            source = selected['diagnostic']['profiles'][f"diagnostic-test/{profile if row['task']=='poisson' else 'all'}/{direction}"]
            assert diag['numeric'] == numeric_summary(numeric_samples(source), row['task'], 4, profile=profile)
    for target, field in [('known_output_tokens_all_attempts', 'known_output_tokens'), ('charged_output_tokens_all_attempts', 'charged_output_tokens')]:
        assert a['totals'][target] == sum(x['summary'][field] for x in a['attempts'])
        assert a['totals'][target] == sum(x['all_attempt_' + field] for x in a['rows'])
    notes = read(OUT / 'method-analysis.json')
    assert {m['run_id'] for m in notes['methods']} == {r['run_id'] for r in a['rows']}
    for m in notes['methods']:
        for x in m['evidence']:
            assert sha(ROOT / x['path']) == x['sha256']
    report = REPORT.read_text()
    forbidden = ('补测', '补检', '补跑', '重跑', '重测', '追补', '第一版')
    assert not any(word in report for word in forbidden)
    assert re.findall(r'^## (\d)\.', report, re.M) == list('12345678')
    assert len(re.findall(r'^### 5\.(?:[2-9]|10) ', report, re.M)) == 9
    assert '十个' in report and '575,944' in report and '739,784' in report
    for row in a['rows']:
        assert f"| {row['label']} | {row['final_score']:.3f} | 12 / 12 / 12 | 1 |" in report
        for name, result in row['diagnostics'].items():
            if name.endswith('/reverse'):
                continue
            metrics = [result['numeric']['metrics'][m]['max'] for m in METRICS[row['task']]]
            assert f"| {metrics[0]:.2e} | {metrics[1]:.2e} |" in report
    for link in re.findall(r'\]\(([^)]+)\)', report):
        if not link.startswith(('http:', 'https:', '#')):
            assert (REPORT.parent / link).resolve().exists(), link
    figures = read(OUT / 'figure-manifest.json')
    assert figures['score_rows'] == [{k: r[k] for k in ('run_id', 'first_score', 'final_score')} for r in a['rows']]
    for row in a['rows']:
        expected = {'heat': ['amplitude/forward', 'spectral_decay/forward', 'contiguous_mask/forward'],
                    'ode': ['coordinate_scale/forward', 'coordinate_swap/forward', 'stable_cubic/forward'],
                    'poisson': ['large_grid/forward', 'five_disks/forward', 'cache_order/forward']}[row['task']]
        plotted = [x for x in figures['diagnostic_plot_rows'] if x['run_id'] == row['run_id']]
        assert [x['profile'] for x in plotted] == expected
        assert all(x['numeric'] == row['diagnostics'][x['profile']]['numeric'] for x in plotted)
    for name, expected in figures['files'].items():
        assert sha(ROOT / name) == expected
    preserved = []
    for folder in ('optimized-r1-20261101', 'optimized-r1-supplement-20261101'):
        manifest = ROOT / 'results' / folder / 'delivery-manifest.json'
        records = read(manifest)['files']
        for row in records:
            path = ROOT / row['path']
            assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], row['path']
        preserved.append({'manifest': ref(manifest), 'files_verified': len(records)})
    result = {'status': 'passed', 'reported_groups': 9, 'scientific_sessions_accounted': 10,
        'chapters': 8, 'method_sections': 9, 'instances': 162, 'all_selected_main_pass': True,
        'metric_column_order_checked': True, 'original_deliveries_preserved': preserved,
        'source_evidence_verified': True, 'new_model_calls': 0, 'new_candidate_executions': 0}
    if pdf:
        from pypdf import PdfReader
        import pdfplumber
        reader = PdfReader(PDF); fonts = set(); pages = []
        assert len(reader.pages) == 22
        for page in reader.pages:
            assert not page.images
            for f in page['/Resources']['/Font'].get_object().values():
                font = f.get_object(); fonts.add(str(font.get('/BaseFont')))
                assert font.get('/Subtype') != '/Type3'
                for child in [c.get_object() for c in font.get('/DescendantFonts', [])] or [font]:
                    descriptor = child.get('/FontDescriptor')
                    assert descriptor and any(k in descriptor.get_object() for k in ('/FontFile', '/FontFile2', '/FontFile3'))
        with pdfplumber.open(PDF) as doc:
            for i, page in enumerate(doc.pages, 1):
                text = page.extract_text() or ''
                assert len(text) > 60 and '\ufffd' not in text
                assert not any(word in text for word in forbidden)
                assert not [c for c in page.chars if c['x0'] < 4 or c['x1'] > page.width-4 or c['top'] < 4 or c['bottom'] > page.height-4]
                pages.append({'page': i, 'characters': len(text)})
        result['pdf'] = {**ref(PDF), 'pages': pages, 'all_fonts_embedded': True, 'raster_images': 0, 'fonts': sorted(fonts)}
    write(OUT / ('report-audit.json' if pdf else 'data-audit.json'), result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('original_deliveries_preserved', 'pdf')}))


def index():
    audit_record, visual = read(OUT / 'report-audit.json'), read(OUT / 'pdf-visual-review.json')
    assert audit_record['status'] == visual['status'] == 'passed'
    assert audit_record['pdf']['sha256'] == visual['pdf']['sha256'] == sha(PDF)
    assert visual['reviewed_pages'] == list(range(1, 23))
    paths = {REPORT, REPORT.with_suffix('.html'), PDF,
             ROOT / 'tools/templates/r1-complete-report-20261101.md'}
    paths.update(ROOT / 'tools' / name for name in ('prepare_r1_complete_report.py',
                  'build_r1_complete_report.py', 'audit_r1_complete_report.py'))
    for base in (OUT, ROOT / 'docs/figures/r1-complete-20261101'):
        paths.update(p for p in base.rglob('*') if p.is_file() and 'matplotlib-cache' not in p.parts
                     and p.name not in ('delivery-manifest.json', 'delivery-verification.json'))
    for page in visual['rendered_pages']:
        assert sha(ROOT / page['path']) == page['sha256']
        paths.add(ROOT / page['path'])
    rows = [{**ref(p), 'bytes': p.stat().st_size} for p in sorted(paths)]
    manifest = {'scope': 'nine_group_complete_results', 'reported_groups': 9,
        'scientific_sessions_accounted': 10, 'source_deliveries': audit_record['original_deliveries_preserved'],
        'files': rows, 'total_files': len(rows), 'total_bytes': sum(r['bytes'] for r in rows)}
    write(OUT / 'delivery-manifest.json', manifest)
    for row in rows:
        assert sha(ROOT / row['path']) == row['sha256']
    for source in manifest['source_deliveries']:
        assert sha(ROOT / source['manifest']['path']) == source['manifest']['sha256']
    verified = {'status': 'passed', 'files_verified': len(rows), 'pdf_pages': 22,
                'reported_groups': 9, 'original_source_manifests_verified': 2}
    write(OUT / 'delivery-verification.json', verified)
    print(json.dumps(verified))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--pdf', action='store_true')
    parser.add_argument('--index', action='store_true'); args = parser.parse_args()
    index() if args.index else audit(args.pdf)
