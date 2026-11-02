"""PDF quality checks and a separate immutable supplement delivery inventory."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = 'optimized-r1-supplement-20261101'
OUT = ROOT / 'results' / TAG
PDF = ROOT / 'output/pdf/sciresearch-optimized-r1-supplement-20261101.pdf'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path)}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def pdf_audit():
    import pdfplumber
    from pypdf import PdfReader
    reader = PdfReader(PDF)
    assert len(reader.pages) == 4
    fonts, unembedded = set(), set()
    images = 0
    for page in reader.pages:
        images += len(page.images)
        for font_ref in page['/Resources'].get_object()['/Font'].get_object().values():
            font = font_ref.get_object()
            fonts.add(str(font.get('/BaseFont')))
            assert font.get('/Subtype') != '/Type3'
            descendants = [f.get_object() for f in font.get('/DescendantFonts', [])] or [font]
            for f in descendants:
                descriptor = f.get('/FontDescriptor')
                if not descriptor or not any(k in descriptor.get_object() for k in ('/FontFile', '/FontFile2', '/FontFile3')):
                    unembedded.add(str(font.get('/BaseFont')))
    assert not unembedded and images == 0
    pages, extracted = [], []
    with pdfplumber.open(PDF) as pdf:
        for index, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ''
            assert len(text) > 100 and '\ufffd' not in text
            assert not [c for c in page.chars if c['x0'] < 4 or c['x1'] > page.width-4 or c['top'] < 4 or c['bottom'] > page.height-4]
            pages.append({'page': index, 'characters': len(text), 'width': page.width, 'height': page.height})
            extracted.append(text)
    text = '\n'.join(extracted)
    for phrase in ('补测结论', '交付与探索', '主测试与独立诊断', '正式计时补测', '可追溯性'):
        assert phrase in text
    result = {'status': 'passed', 'pdf': ref(PDF), 'pages': pages, 'fonts': sorted(fonts),
              'all_fonts_embedded': True, 'raster_images': images, 'selectable_text': True}
    write(OUT / 'pdf-audit.json', result)
    print(json.dumps(result, ensure_ascii=False))


def index():
    assert not (OUT / 'delivery-manifest.json').exists(), 'Never replace a finalized supplement manifest'
    audit = read(OUT / 'pdf-audit.json')
    visual = read(OUT / 'pdf-visual-review.json')
    assert audit['status'] == visual['status'] == 'passed'
    assert audit['pdf'] == visual['pdf'] == ref(PDF)
    assert visual['reviewed_pages'] == [1, 2, 3, 4]
    analysis = read(OUT / 'analysis.json')
    assert analysis['status'] == 'passed'
    plan_path = ROOT / 'freezes' / ('research-run-plan-' + TAG + '.json')
    plan = read(plan_path)
    paths = {plan_path, PDF, ROOT / 'docs' / (TAG + '.md'), ROOT / 'docs' / (TAG + '.html')}
    for page in visual['rendered_pages']:
        assert sha(ROOT / page['path']) == page['sha256']
        paths.add(ROOT / page['path'])
    for name in ('supplement_optimized_failures.py', 'audit_optimized_supplement.py',
                 'build_optimized_supplement_report.py', 'finalize_optimized_supplement.py'):
        paths.add(ROOT / 'tools' / name)
    for base in (ROOT / 'logs' / TAG, OUT, ROOT / 'research-runs' / plan['plan_id'],
                 ROOT / 'research-runs' / (plan['plan_id'] + '-ode-g1-r1'),
                 ROOT / 'archives/pre-supplement-launch-fix-20261101'):
        paths.update(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.startswith('.'))
    rows = [{**ref(path), 'bytes': path.stat().st_size} for path in sorted(paths)]
    write(OUT / 'delivery-manifest.json', {'schema_version': 1, 'scope': 'post_hoc_two_failure_supplement',
          'new_scientific_sessions': 1, 'poisson_new_research': 0, 'original_delivery': analysis['original_preservation']['manifest'],
          'files': rows, 'total_files': len(rows), 'total_bytes': sum(r['bytes'] for r in rows)})
    verify()


def verify():
    manifest = read(OUT / 'delivery-manifest.json')
    for row in manifest['files']:
        path = ROOT / row['path']
        assert path.is_file() and path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], row['path']
    original = manifest['original_delivery']
    assert sha(ROOT / original['path']) == original['sha256']
    original_files = read(ROOT / original['path'])['files']
    for row in original_files:
        path = ROOT / row['path']
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], row['path']
    result = {'status': 'passed', 'supplement_files_verified': len(manifest['files']),
              'original_files_verified': len(original_files), 'new_scientific_sessions': 1, 'pdf_pages': 4}
    write(OUT / 'delivery-verification.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['pdf_audit', 'index', 'verify'])
    globals()[parser.parse_args().action]()
