"""Verify final-edition roles, unchanged experiments and presentation data."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
def read(path):
    return json.loads((ROOT / path).read_text())
def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()

def audit():
    index = read('results/final-report-2026-10-31/index.json')
    assert index['official']['sessions'] == 9 and index['official']['successes'] == 8
    assert index['comparison']['sessions'] == index['comparison']['successes'] == 9
    assert index['supplement']['sessions'] == 1 and index['supplement']['successes'] == 0
    assert index['supplement']['pooled_into_official'] is False
    assert index['new_model_calls'] == index['new_candidate_executions'] == 0
    for kind in ('official', 'comparison', 'supplement'):
        ref = index[kind]['source']
        assert sha(ref['path']) == ref['sha256']
    for path, expected in index['preserved_originals'].items():
        assert sha(path) == expected
    archive = index['archive']
    assert sha(archive['path']) == archive['sha256']
    saved = read(archive['path'])
    for name, expected in saved['files'].items():
        assert sha(Path(archive['path']).parent / name) == expected
    quality = index['pdf_quality']
    assert quality['charts'] == 'vector_svg' and quality['fonts'] == 'embedded_subset_truetype'
    assert quality['body_pt'] == 11 and quality['table_pt'] == 9.5
    previous = quality['previous_layout']
    assert sha(previous['path']) == previous['sha256']
    quality_archive = Path(previous['path']).parent
    previous_files = read(previous['path'])['files']
    for name, expected in previous_files.items():
        assert sha(quality_archive / name) == expected
    assert sha('output/pdf/sciresearch-final-report-20261031.pdf') == previous_files['output/pdf/sciresearch-final-report-20261031.pdf']
    figure_ref = index['figure_manifest']
    assert sha(figure_ref['path']) == figure_ref['sha256']
    figure = read(figure_ref['path'])
    assert figure['analysis'] == index['official']['source']
    assert len(figure['files']) == 4
    for name, expected in figure['files'].items():
        assert sha(name) == expected
    official = read(index['official']['source']['path'])
    for chart, panels in figure['panels'].items():
        assert len(panels) == 3
        fields = ('old_final_score', 'final_score') if chart == 'old-new-scores' else ('first_score', 'final_score')
        for panel, task in zip(panels, ('heat', 'ode', 'poisson')):
            rows = [r for r in official['rows'] if r['task'] == task]
            assert panel['task'] == task and panel['run_ids'] == [r['run_id'] for r in rows]
            for field in fields:
                assert panel[field] == [r[field] for r in rows]
    report = (ROOT / 'docs/submission-report-2026-10-24.md').read_text()
    previous_report = (ROOT / quality_archive / 'docs/submission-report-2026-10-24.md').read_text()
    content = report.replace('sciresearch-final-report-20261031-hq.pdf', 'sciresearch-final-report-20261031.pdf')
    for heading in ('### 6.1 作者基线独立评分', '### 13.1 补跑结果与原因', '### 13.2 执行配置与证据'):
        content = content.replace(heading + '\n\n', '')
    assert content == previous_report, 'PDF quality changes must preserve all report content'
    html = (ROOT / 'docs/submission-report-2026-10-24.html').read_text()
    assert html.count('data:image/svg+xml;base64,') == 3
    assert 'data:image/png;' not in html and html.count('data:font/ttf;base64,') == 4
    assert '第二版统一执行器的九组 r1 作为正式主结果' in report
    assert '第一版九组 r1 仅作历史对照' in report
    assert '## 13. ODE G1 r1 单组补跑（独立报告）' in report
    assert len(re.findall(r'\| M\d\d \|', report)) == 9
    assert '| 最终分数 | 0.000 | 0.000 |' in report
    for row in official['rows']:
        assert f"| {row['report_id']} | {row['label']} | {row['final_score']:.3f} |" in report
        assert f"| {row['label']} | {row['old_final_score']:.3f} | {row['final_score']:.3f} | {row['score_delta']:+.3f} |" in report
    assert (ROOT / index['pdf_path']).is_file()
    links = 0
    for name in ('docs/submission-report-2026-10-24.md', 'README.md', 'docs/reproduction.md'):
        path = ROOT / name
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('http:', 'https:', '#', 'mailto:')):
                continue
            assert (path.parent / target.split('#')[0]).exists(), (name, target)
            links += 1
    return {'status': 'passed', 'official_sessions': 9, 'official_successes': 8,
            'comparison_sessions': 9, 'separate_rerun_sessions': 1, 'separate_rerun_score': 0,
            'preserved_original_artifacts': len(index['preserved_originals']),
            'archived_files': len(saved['files']), 'new_figure_files': 4,
            'quality_archive_files': len(previous_files), 'report_content_preserved': True,
            'vector_charts': 3, 'embedded_truetype_faces': 4,
            'local_links_checked': links, 'new_model_calls': 0, 'new_candidate_executions': 0}

if __name__ == '__main__':
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
