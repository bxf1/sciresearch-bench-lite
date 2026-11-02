"""Audit provenance, grouping, report data and optional final PDF structure."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'results/optimized-r1-20261101'


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(include_pdf):
    analysis = read(OUT / 'analysis.json')
    raw = read(OUT / 'results.json')
    report_manifest = read(OUT / 'report-manifest.json')
    assert raw['status'] == 'scoring_completed'
    assert analysis['scope'] == report_manifest['scope'] == 'optimized_r1_nine_only'
    assert analysis['scientific_sessions'] == len(analysis['rows']) == len(raw['rows']) == 9
    assert analysis['data_instances'] == 162
    assert analysis['research_closed_at'] < analysis['first_hidden_scoring_at']
    closure = read(ROOT / 'logs/optimized-r1-20261101/research-closure.json')
    assert sha(OUT / 'research-closure-manifest.json') == closure['manifest_sha256']
    for reference in analysis['source_evidence']:
        assert sha(ROOT / reference['path']) == reference['sha256'], reference['path']
    for name, expected in report_manifest['source_sha256'].items():
        assert sha(ROOT / name) == expected, name
    supplement = read(OUT / 'numeric-only-supplement.json')
    assert supplement['status'] == 'completed' and supplement['service']['restored']
    assert not supplement['formal_timing'] and not supplement['changes_formal_scores']
    assert not supplement['candidate_selection_changed'] and supplement['new_scientific_sessions'] == 0
    assert sha(OUT / 'results.json') == supplement['original_results']['sha256']
    for group in supplement['groups']:
        row = next(r for r in analysis['rows'] if r['run_id'] == group['run_id'])
        assert row['task'] == 'poisson' and row['final_score'] is None and row['reward'] is None
        assert len(group['replays']) == 3
        for role in group['roles']:
            assert row[role]['source_hash'] == group['source_hash']
            assert row['main_numeric'][role]['numeric_origin'] == 'accuracy_only_supplement_no_formal_timing'
        for reference in group['replays']:
            assert sha(ROOT / reference['path']) == reference['sha256']
            result = read(ROOT / reference['path'])
            assert result['worker']['source_hash'] == group['source_hash']
    observations = read(OUT / 'observation-audit.json')
    assert observations['status'] == 'passed' and observations['selected_valid_windows'] == 16
    assert len(observations['cache_order_comparisons']) == 36
    for row in observations['windows']:
        for kind in ('acceptance', 'observations', 'policy'):
            assert sha(ROOT / row[kind]['path']) == row[kind]['sha256']
    for row in observations['cache_order_comparisons']:
        for kind in ('forward', 'reverse'):
            assert sha(ROOT / row[kind]['path']) == row[kind]['sha256']
        assert row['bitwise_equal'] and row['relative_l2_difference'] == 0
    plan = read(ROOT / raw['plan']['path'])
    from runner.run_plan import validate_start
    validate_start(plan, ROOT)
    from runner.registry import Registry
    snapshots = 0
    for attempt in analysis['attempts']:
        root = ROOT / attempt['registry_root']
        if not (root / 'registry/state.json').exists():
            continue
        state = read(root / 'registry/state.json')
        assert state['closed']
        assert state['budget_seconds'] == 1800 and state['max_evaluations'] == 20
        assert len(state['evaluations']) <= 20
        registry = Registry(root / 'registry')
        for candidate in state['evaluations']:
            if candidate.get('source_hash'):
                registry.verified_snapshot(candidate['id']); snapshots += 1
        observed = attempt['summary']
        assert observed['accepted_public_evaluations'] == len(state['evaluations'])
        assert observed['unique_registered_source_hashes'] == len({c['source_hash'] for c in state['evaluations'] if c.get('source_hash')})
    expected_order = [(task, group) for task in ('heat', 'ode', 'poisson') for group in ('g1', 'g2', 'g3')]
    assert [(r['task'], r['group']) for r in analysis['rows']] == expected_order
    checked_timing = 0
    def check_timing(value):
        nonlocal checked_timing
        if 'timing_attempts' not in value:
            return
        history = value['timing_attempts']
        assert len(history) <= 12
        assert value['measurement_attempts'] == sum(bool(a['measured']) for a in history) <= 3
        eligible = [a['number'] for a in history if a['status'] in ('valid', 'candidate_failed')]
        assert value['selected_window'] == (eligible[0] if eligible else None)
        assert value['selection_policy'] == 'first_valid_not_fastest'
        if value['performance_status'] == 'valid':
            from statistics import median
            times = {role: [s['worker']['execution_wall_seconds'] for s in value['samples'][role]] for role in ('B', 'C')}
            assert len(times['B']) == len(times['C']) == 3
            ratio = median(times['B']) / median(times['C'])
            assert abs(value['speedup'] - ratio) < 1e-12
            assert max(times['B']) / min(times['B']) <= 1.20
            assert abs(value['score'] - 100 * max(0, min(1, math.log(ratio) / math.log(8)))) < 1e-10
        checked_timing += 1
    for row in analysis['rows']:
        original = next(r for r in raw['rows'] if r['run']['run_id'] == row['run_id'])
        d = original['main']['diagnostics']
        assert (row['final_score'], row['reward'], row['evaluation_status']) == (d.get('score'), d.get('reward'), d['evaluation_status'])
        assert row['attempt_count'] <= 2
        for role in ('first', 'final'):
            value = d.get(role)
            if not value:
                continue
            if value.get('repeats'):
                assert len(value['repeats']) == (1 if row['task'] == 'poisson' else 3)
                for result in value['repeats']:
                    check_timing(result)
            else:
                assert value.get('score') == 0 or value.get('reused_from')
        for result in original['diagnostic'].get('profiles', {}).values():
            check_timing(result)
        assert len(row['diagnostics']) == (4 if row['task'] == 'poisson' else 3)
        for value in row['diagnostics'].values():
            n = value['numeric']
            assert n['expected_cases'] == 4 and n['observed_cases'] <= 4
            assert 0 <= n['passed_all_observed_replays'] <= n['observed_cases']
    assert sum(a['summary']['known_output_tokens'] for a in analysis['attempts']) == analysis['totals']['known_output_tokens_all_attempts']
    assert sum(r['reward'] == 1 for r in analysis['rows']) == analysis['totals']['reward_one']
    report_path = ROOT / report_manifest['report_path']
    report = report_path.read_text()
    assert '{{' not in report
    headings = re.findall(r'^## ([1-8])\. (.+)$', report, re.M)
    assert [n for n, _ in headings] == [str(n) for n in range(1, 9)]
    assert len(re.findall(r'^### 5\.(?:[2-9]|10) ', report, re.M)) == 9
    assert not any(word in report for word in ('第一版', 'old-new', '显著优于'))
    for row in analysis['rows']:
        score = '—' if row['final_score'] is None else f"{row['final_score']:.3f}"
        assert f"| {row['label']} | {score} |" in report
    links = 0
    for name in re.findall(r'\]\(([^)]+)\)', report):
        if name.startswith(('http:', 'https:', '#')):
            continue
        assert (report_path.parent / name).resolve().exists(), name
        links += 1
    html = report_path.with_suffix('.html').read_text()
    assert html.count('data:image/svg+xml;base64,') == 3
    assert 'data:image/png;' not in html
    assert html.count('data:font/ttf;base64,') == 4
    figure_manifest = read(OUT / 'figure-manifest.json')
    for name, expected in figure_manifest['files'].items():
        assert sha(ROOT / name) == expected
    assert figure_manifest['score_rows'] == [{k: r[k] for k in ('run_id', 'first_score', 'final_score')} for r in analysis['rows']]
    result = {'status': 'passed', 'scientific_sessions': 9, 'instances': 162,
              'snapshots_verified': snapshots, 'timing_records_verified': checked_timing,
              'local_links': links, 'main_chapters': 8, 'method_sections': 9,
              'main_and_diagnostic_separate': True, 'source_hashes_valid': True,
              'accuracy_supplement_preserves_null_score': True,
              'cache_order_output_pairs_verified': 36,
              'new_model_calls': 0, 'new_candidate_executions': 0}
    if include_pdf:
        from pypdf import PdfReader
        import pdfplumber
        pdf_path = ROOT / report_manifest['pdf_path']
        reader = PdfReader(pdf_path)
        images, font_names, unembedded = 0, set(), set()
        pages = []
        for page in reader.pages:
            resources = page['/Resources'].get_object()
            images += len(page.images)
            for font_ref in resources.get('/Font', {}).get_object().values():
                font = font_ref.get_object(); font_names.add(str(font.get('/BaseFont')))
                fonts = [f.get_object() for f in font.get('/DescendantFonts', [])] or [font]
                for f in fonts:
                    descriptor = f.get('/FontDescriptor')
                    if not descriptor or not any(k in descriptor.get_object() for k in ('/FontFile', '/FontFile2', '/FontFile3')):
                        unembedded.add(str(font.get('/BaseFont')))
        assert not unembedded, unembedded
        assert images == 0, 'Scientific plots must remain vector in the PDF'
        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ''
                assert len(text) > 50, f'sparse page {index}'
                assert '\ufffd' not in text, f'bad extraction page {index}'
                outside = [c for c in page.chars if c['x0'] < 4 or c['x1'] > page.width - 4 or c['top'] < 4 or c['bottom'] > page.height - 4]
                assert not outside, f'text outside page {index}'
                pages.append({'page': index, 'characters': len(text), 'width': page.width, 'height': page.height,
                              'min_x': min(c['x0'] for c in page.chars), 'max_x': max(c['x1'] for c in page.chars)})
            extracted = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        for text in ('问题定义', '生成 GT', '校验集', '开发集', '探索', '测试集', '结论', '问题分析'):
            assert text in extracted, text
        result['pdf'] = {'path': str(pdf_path.relative_to(ROOT)), 'sha256': sha(pdf_path), 'pages': pages,
                         'font_count': len(font_names), 'fonts': sorted(font_names), 'all_fonts_embedded': True,
                         'raster_images': images, 'selectable_text_verified': True,
                         'visual_page_review': 'pending separate rendered-page inspection'}
        visual_path = OUT / 'pdf-visual-review.json'
        if visual_path.exists():
            visual = read(visual_path)
            if visual['pdf']['sha256'] == sha(pdf_path):
                assert visual['status'] == 'passed'
                assert visual['reviewed_pages'] == list(range(1, len(pages) + 1))
                result['pdf']['visual_page_review'] = 'passed'
                result['pdf']['visual_review'] = {'path': str(visual_path.relative_to(ROOT)), 'sha256': sha(visual_path)}
    (OUT / ('report-audit.json' if include_pdf else 'report-data-audit.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'pdf'}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--pdf', action='store_true')
    audit(parser.parse_args().pdf)
