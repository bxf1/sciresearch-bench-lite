"""Verify the second-edition-only report against saved experiment evidence."""
import hashlib
import json
from pathlib import Path
import re
from statistics import median

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text())


def sha(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def audit():
    analysis = read('results/second-edition-report-2026-11-01/analysis.json')
    official = read('results/unified-r1-nine-2026-10-29/reviewed-results.json')
    assert analysis['scope'] == 'second_edition_only'
    assert (analysis['official_sessions'], analysis['official_successes'], analysis['attempts']) == (9, 8, 11)
    assert analysis['new_model_calls'] == analysis['new_candidate_executions'] == 0
    assert official['latest_research_finished_at'] < official['first_hidden_replay_started_at']
    rows = analysis['rows']
    assert len(rows) == 9 and len({r['run_id'] for r in rows}) == 9
    assert [(r['task'], r['group']) for r in rows] == [
        (task, group) for task in ('heat', 'ode', 'poisson') for group in ('g1', 'g2', 'g3')]
    for row, source in zip(rows, official['rows']):
        assert all(value == source[key] for key, value in row.items()), row['label']
        assert not any(key.startswith('old_') or key == 'score_delta' for key in row)
        assert row['passed_per_replay'] == ([12, 12, 12] if row['reward'] else [])
    assert sum(r['reward'] for r in rows) == 8
    totals = analysis['totals']
    assert totals['public_evaluations'] == sum(r['public_evaluations'] for r in rows) == 22
    assert totals['retained_output_tokens'] == sum(r['output_tokens'] for r in rows) == 509736
    assert abs(totals['retained_wall_seconds'] - sum(r['research_wall_seconds'] for r in rows)) < 1e-8
    assert totals['all_attempt_known_output_tokens'] == official['all_new_attempt_known_output_tokens'] == 595668
    assert totals['all_attempt_charged_output_tokens'] == official['all_new_attempt_charged_output_tokens'] == 654531
    supplement = analysis['supplement']
    assert (supplement['sessions'], supplement['pooled'], supplement['final_score'], supplement['reward']) == (1, False, 0, 0)
    rerun = read(supplement['source']['path'])
    assert rerun['final_score'] == supplement['final_score'] and rerun['reward'] == supplement['reward']
    for ref in (analysis['archive'], analysis['figure_manifest'], supplement['source']):
        assert sha(ref['path']) == ref['sha256'], ref['path']
    for name, expected in analysis['source_sha256'].items():
        assert sha(name) == expected, name
    saved = read(analysis['archive']['path'])
    assert analysis['preserved_originals'] == saved['preserved_originals']
    for name, expected in saved['files'].items():
        assert sha(Path(analysis['archive']['path']).parent / name) == expected, name
    for name, expected in saved['preserved_originals'].items():
        assert sha(name) == expected, name

    splits = read('data/split-summary.json')
    assert analysis['splits'] == splits and splits['instances'] == 90
    assert len(splits['splits']) == 9
    for row in splits['splits']:
        count = 6 if row['split'] == 'public-dev' else 12
        assert row['instances'] == row['qc_passed'] == count
        assert row['levels'] == {str(level): count // 3 for level in range(3)}
    calibration = read('results/comparisons/calibration-summary.json')
    assert sha(calibration['source']) == calibration['source_sha256']
    assert analysis['calibration_methods'] == calibration['methods']
    assert len(calibration['methods']) == 11 and not calibration['formal']
    assert calibration['independent_model_sessions'] == 0
    for row in calibration['methods']:
        assert row['total'] == 12
        assert row['passed'] == (1 if row['method'] == 'ls' else 0 if row['method'] == 'raw' else 12)
    profile = read('freezes/t3-profile-local-001.json')
    assert analysis['profile'] == profile['profile'] == 'efficiency_gate_1.5'
    assert len(profile['groups']) == profile['calibration_criteria']['group_count'] == 3
    assert not profile['final_test_scores_accessed']
    for group in profile['groups']:
        assert group['order'] == 'BCCBBC' and group['formal_evidence_valid']
        assert group['scientific_checks_passed'] == 72
        speedup = median(group['baseline_seconds']) / median(group['candidate_seconds'])
        assert abs(group['speedup'] - speedup) < 1e-12 and speedup >= 1.8
        ratio = max(group['baseline_seconds']) / min(group['baseline_seconds'])
        assert abs(group['baseline_time_ratio'] - ratio) < 1e-12 and ratio <= 1.2

    report_path = ROOT / analysis['report_path']
    report = report_path.read_text()
    assert not any(term in report for term in ('第一版', 'old-new', '历史对照', '{{'))
    headings = re.findall(r'^## ([1-8])\. (.+)$', report, re.M)
    assert [int(number) for number, _ in headings] == list(range(1, 9))
    for (_, title), expected in zip(headings, ('问题定义', '生成 GT', '校验集', '开发集', '探索', '测试集', '结论', '问题分析')):
        assert expected in title, title
    assert '## 附录 A. ODE G1 独立补跑' in report
    assert len(re.findall(r'\| M\d\d \|', report)) == 9
    for row in rows:
        passed = '12/12/12' if row['passed_per_replay'] else '无候选，无重放'
        speedup = f"{row['speedup']:.3f}×" if row['speedup'] is not None else '—'
        assert f"| {row['report_id']} | {row['label']} | {row['final_score']:.3f} | {passed} | {row['reward']} | {speedup} |" in report
        assert f"| {row['label']} | {row['first_score']:.3f} | {row['final_score']:.3f} | {row['final_score']-row['first_score']:+.3f} |" in report
        assert f"| {row['label']} | {row['public_evaluations']} | {row['output_tokens']:,} | {row['research_wall_seconds']/60:.2f} | {row['status']} |" in report
    calibration_section = report.split('### 3.3 ', 1)[1].split('## 4.', 1)[0]
    assert len(re.findall(r'^\| (?:Heat|ODE|Poisson) \|', calibration_section, re.M)) == 11
    for row in calibration['methods']:
        score = f"{row['score']:.3f}" if row['score'] is not None else '—（仅数值验收）'
        assert f"| {row['passed']} / 12 | {score} |" in calibration_section
    assert [sum((r['final_score'] > r['first_score']) for r in rows),
            sum((r['final_score'] < r['first_score']) for r in rows),
            sum((r['final_score'] == r['first_score']) for r in rows)] == [3, 1, 5]
    figures = read(analysis['figure_manifest']['path'])
    assert figures['scope'] == 'second_edition_nine_r1_only'
    assert sha(figures['source']['path']) == figures['source']['sha256']
    assert figures['outcomes'] == [3, 2, 3]
    assert figures['plot_rows'] == [{k: r[k] for k in ('run_id', 'task', 'group', 'first_score', 'final_score', 'reward')} for r in rows]
    assert len(figures['files']) == 6
    for name, expected in figures['files'].items():
        assert sha(name) == expected, name
    html = report_path.with_suffix('.html').read_text()
    assert html.count('data:image/svg+xml;base64,') == 3 and 'data:image/png;' not in html
    assert html.count('data:font/ttf;base64,') == 4
    assert '第一版' not in html and 'old-new' not in html
    pdf = ROOT / analysis['pdf_path']
    assert pdf.read_bytes().startswith(b'%PDF-')
    links = 0
    for path in (report_path, ROOT / 'README.md', ROOT / 'docs/reproduction.md'):
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('http:', 'https:', '#', 'mailto:')):
                continue
            assert (path.parent / target.split('#')[0]).exists(), (str(path), target)
            links += 1
    return {'status': 'passed', 'scope': analysis['scope'], 'official_sessions': 9,
            'official_successes': 8, 'separate_rerun_sessions': 1, 'supplement_pooled': False,
            'qc_instances': 90, 'calibration_methods': 11, 'timing_calibration_groups': 3,
            'main_chapters': 8, 'vector_charts': 3, 'embedded_truetype_faces': 4,
            'preserved_original_artifacts': len(saved['preserved_originals']),
            'archived_files': len(saved['files']), 'local_links_checked': links,
            'new_model_calls': 0, 'new_candidate_executions': 0}


if __name__ == '__main__':
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
