"""Build ordered report tables and optional figures/HTML from saved evidence only.

No model calls, candidate executions, or changes to historical scoring records.
Standard library suffices for JSON/tables. --figures needs matplotlib 3.10.7;
--html needs markdown-it-py 4.0.0. Both are presentation-only dependencies.
"""
import argparse
import base64
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/final-report-2026-10-25'
FIG = ROOT / 'docs/figures/final-report'
REPORT = ROOT / 'docs/submission-report-2026-10-24.md'
TASKS = ('heat', 'ode', 'poisson')
NAMES = {'heat': 'Heat', 'ode': 'ODE', 'poisson': 'Poisson'}
SOURCES = [
    'results/poisson-timing-recheck-2026-10-25/reviewed-results.json',
    'results/thinking-control-2026-10-25/reviewed-comparison.json',
    'results/delivery-analysis/run-summary.csv',
    'freezes/research-run-plan-thinking-max-2026-10-25.json',
    'research-runs/research-98719c3c1cf3fc92/final-replays/research-98719c3c1cf3fc92-poisson-g2-r1-a001/result.json',
    'logs/poisson-timing-recheck-2026-10-25/g2-window-002/operation-result.json',
    'logs/poisson-timing-recheck-2026-10-25/g2-window-002/host-observations.jsonl',
]


def read(name):
    return json.loads((ROOT / name).read_text())


def num(value):
    return None if value in (None, '', 'null') else float(value)


def fmt(value):
    return '—' if value is None else f'{value:.3f}'


def build_data():
    current, thinking = read(SOURCES[0]), read(SOURCES[1])
    with (ROOT / SOURCES[2]).open() as stream:
        old = {(r['task'], r['group'], int(r['repeat'])): r for r in csv.DictReader(stream)}
    plan = read(SOURCES[3])
    sequence = {r['run_id']: r['sequence'] for r in plan['runs']}
    attempts = {r['attempt_id']: r for r in thinking['attempt_records']}
    rows = []
    for p in sorted(current['pairs'], key=lambda p: (TASKS.index(p['task']), p['group'], p['repeat'])):
        a = attempts[p['attempt_id']]
        o = old[p['task'], p['group'], p['repeat']]
        first = a['first']
        measurement = next((m for m in current['measurements'] if m['run_id'] == p['run_id']), None)
        if measurement:
            first = measurement['first']
        rows.append({
            'display_order': len(rows) + 1, 'execution_sequence': sequence[p['run_id']],
            'task': p['task'], 'group': p['group'], 'repeat': p['repeat'],
            'label': f"{NAMES[p['task']]} {p['group'].upper()} r{p['repeat']}",
            'attempt_id': p['attempt_id'], 'attempt_raw_status': a['raw_status'],
            'old_first_score': num(o['first_score']), 'old_final_score': num(o['final_score']),
            'old_reward': num(o['reward']), 'old_has_submission': o['final_candidate'] not in ('', 'null'),
            'thinking_first_score': first['score'] if first else None,
            'thinking_final_score': p['after']['score'] if p['after'] else None,
            'thinking_reward': p['after']['reward'] if p['after'] else None,
            'thinking_has_submission': a['valid_public_candidate'],
            'paired_delta': p['delta_score'], 'first_final_direction': p['first_final_direction'],
            'output_tokens': a['known_output_tokens'], 'public_evaluations': a['public_evaluations'],
            'research_wall_seconds': a['research_wall_seconds'],
            'score_evidence': measurement['operation_result'] if measurement else a['replay_evidence'],
        })
    diagnostics = []
    for source in SOURCES[4:6]:
        x = read(source)
        samples = x['diagnostics']['first']['repeats'][0]['samples']
        b = [r['worker']['execution_wall_seconds'] for r in samples['B']]
        c = [r['worker']['execution_wall_seconds'] for r in samples['C']]
        assert len(b) == len(c) == 3
        assert all(r['passed'] == r['total'] == 12 for r in samples['C'])
        diagnostics.append({
            'source': source, 'formal_timing_accepted': False, 'formal_score': None,
            'baseline_seconds': b, 'candidate_seconds': c,
            'baseline_median_seconds': statistics.median(b), 'candidate_median_seconds': statistics.median(c),
            'raw_median_ratio_diagnostic_only': statistics.median(b) / statistics.median(c),
            'unique_cases': 12, 'candidate_replays': 3, 'passed_per_replay': [r['passed'] for r in samples['C']],
            'max_relative_residual': max(v['max_relative_residual'] for r in samples['C'] for v in r['cases']),
            'max_solution_error': max(v['max_solution_error'] for r in samples['C'] for v in r['cases']),
        })
    assert len(rows) == 15 and sum(r['thinking_final_score'] is not None for r in rows) == 14
    assert sum(r['thinking_reward'] == 1 for r in rows) == 14
    assert sum(r['old_reward'] == 1 for r in rows) == 6
    assert sum(r['old_has_submission'] for r in rows) == 9
    data = {
        'scope': 'Descriptive analysis of saved experiments; no new executions; G2 diagnostic timings are not formal scores.',
        'display_order': 'task Heat/ODE/Poisson, group G1/G2/G3, repeat r1/r2/r3',
        'repeat_definition': 'Fresh independent research session within the same task/group; not an attempt retry, test difficulty, or replay.',
        'rows': rows, 'g2_diagnostics': diagnostics,
        'retained_thinking_usage': thinking['retained_usage'], 'all_thinking_attempt_usage': thinking['all_attempt_usage'],
        'source_sha256': {s: hashlib.sha256((ROOT / s).read_bytes()).hexdigest() for s in SOURCES},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'analysis.json').write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    return data


def fill_tables(data):
    rows = data['rows']
    table = '| 序号 | 会话 | 原最终分 | thinking/max 最终分 | 差值 | 原 reward → 新 reward | 说明 |\n|---:|---|---:|---:|---:|---|---|\n'
    for r in rows:
        note = '原无提交，按协议记 0' if not r['old_has_submission'] else '两批均有提交'
        if r['task'] == 'poisson' and r['group'] == 'g1': note = '新分采用获准的独立计时补测'
        if r['task'] == 'poisson' and r['group'] == 'g2': note = '数值通过；两批正式计时无效'
        reward = lambda v: '—' if v is None else str(int(v))
        table += f"| {r['display_order']:02d} | {r['label']} | {fmt(r['old_final_score'])} | {fmt(r['thinking_final_score'])} | {fmt(r['paired_delta'])} | {reward(r['old_reward'])} → {reward(r['thinking_reward'])} | {note} |\n"
    detail = '| 序号 | 会话 | first 分 | final 分 | 公开评估次数 | 输出 token | 研究用时（分钟） | 实际计划序号 |\n|---:|---|---:|---:|---:|---:|---:|---:|\n'
    for r in rows:
        detail += f"| {r['display_order']:02d} | {r['label']} | {fmt(r['thinking_first_score'])} | {fmt(r['thinking_final_score'])} | {r['public_evaluations']} | {r['output_tokens']:,} | {r['research_wall_seconds']/60:.2f} | {r['execution_sequence']} |\n"
    diag = '| 测量 | 基线中位耗时（秒） | G2 中位耗时（秒） | 原始耗时比（仅诊断） | 正式分数 |\n|---|---:|---:|---:|---|\n'
    for label, d in zip(('首次测量', '独立补测'), data['g2_diagnostics']):
        diag += f"| {label} | {d['baseline_median_seconds']:.6f} | {d['candidate_median_seconds']:.6f} | {d['raw_median_ratio_diagnostic_only']:.3f}× | 未取得有效计时，留空 |\n"
    text = REPORT.read_text()
    for key, block in [('paired-results', table), ('session-details', detail), ('g2-diagnostics', diag)]:
        pattern = rf'<!-- BEGIN {key} -->.*?<!-- END {key} -->'
        text, n = re.subn(pattern, f'<!-- BEGIN {key} -->\n{block}<!-- END {key} -->', text, flags=re.S)
        assert n == 1, key
    REPORT.write_text(text)
    (OUT / 'ordered-results.md').write_text('# 按任务、指导组、重复次数排序的结果\n\n' + table + '\n' + detail + '\n' + diag)


def figures(data, font):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    if font:
        font_manager.fontManager.addfont(font)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=font).get_name()
    plt.rcParams.update({'font.size': 11, 'axes.unicode_minus': False, 'svg.fonttype': 'path', 'svg.hashsalt': 'sciresearch-final-report'})
    FIG.mkdir(parents=True, exist_ok=True)
    blue, orange, gray = '#176B87', '#D66A28', '#9AA5B1'

    def save(fig, name):
        fig.savefig(FIG / (name + '.png'), dpi=180, bbox_inches='tight', metadata={'Software': 'SciResearch report'})
        fig.savefig(FIG / (name + '.svg'), bbox_inches='tight', metadata={'Date': None})
        svg = FIG / (name + '.svg')
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
        plt.close(fig)

    fig, axs = plt.subplots(1, 2, figsize=(11, 3.7), layout='constrained')
    labels = ['原批次', 'thinking/max']
    axs[0].barh(labels, [9, 15], color=[blue, orange])
    for y, v in enumerate((9, 15)): axs[0].text(v - .3, y, f'{v}/15', ha='right', va='center', color='white', weight='bold')
    axs[0].set(title='A. 有提交的研究会话', xlim=(0, 16), xlabel='会话数')
    left = [0, 0]
    for vals, color, label in [([6, 14], blue, '成功（reward=1）'), ([8, 0], orange, '有效未成功'), ([1, 1], gray, '计时无效')]:
        axs[1].barh(labels, vals, left=left, color=color, label=label)
        for y, v in enumerate(vals):
            if v: axs[1].text(left[y] + v / 2, y, str(v), ha='center', va='center', color='white', weight='bold')
        left = [a+b for a,b in zip(left,vals)]
    axs[1].set(title='B. 最终评测结局', xlim=(0, 16), xlabel='会话数（每批固定 15）')
    axs[1].legend(loc='lower center', bbox_to_anchor=(.5, -.48), ncol=3, fontsize=10)
    for ax in axs:
        ax.invert_yaxis(); ax.spines[['top','right']].set_visible(False); ax.set_xticks([0,3,6,9,12,15])
    save(fig, 'outcomes')

    fig, axes = plt.subplots(3, 1, figsize=(11, 10), layout='constrained')
    for ax, task in zip(axes, TASKS):
        rs = [r for r in data['rows'] if r['task'] == task]
        for i, r in enumerate(rs):
            for shift, key, color in [(-.18, 'old_final_score', blue), (.18, 'thinking_final_score', orange)]:
                v = r[key]
                if v is None:
                    ax.scatter([i+shift], [5], color=gray, marker='x', s=65)
                else:
                    ax.bar(i+shift, v, .33, color=color)
                    ax.text(i+shift, v+1.8, f'{v:.1f}', ha='center', fontsize=8)
        ax.set_xticks(range(len(rs)), [f"{r['group'].upper()} r{r['repeat']}" for r in rs])
        ax.set(ylim=(0,112), title=f'{NAMES[task]}：原批次与 thinking/max', ylabel='任务内分数（0–100）')
        ax.spines[['top','right']].set_visible(False)
        ax.grid(axis='y', alpha=.15); ax.set_axisbelow(True)
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    fig.legend(handles=[Patch(color=blue,label='原批次'),Patch(color=orange,label='thinking/max'),Line2D([],[],marker='x',color=gray,linestyle='',label='×：无有效评分，非零分')], loc='outside lower center', ncol=3)
    save(fig, 'paired-scores')

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), layout='constrained')
    for ax, label, d in zip(axes, ('首次测量：窗口拒绝', '独立补测：窗口拒绝'), data['g2_diagnostics']):
        for i, key, color in [(0, 'baseline_seconds', blue), (1, 'candidate_seconds', orange)]:
            ax.scatter([i-.07,i,i+.07], d[key], color=color, s=45, zorder=3)
            m = statistics.median(d[key]); ax.plot([i-.23,i+.23],[m,m],color=color,lw=2)
            ax.text(i, m+.08, f'中位数 {m:.3f}s', ha='center', fontsize=10)
        ax.set(xticks=[0,1],xticklabels=['Jacobi-CG 基线','G2 候选'],ylim=(0,1.55),xlim=(-.5,1.5),ylabel='完整批次实测耗时（秒）',title=label)
        ax.spines[['top','right']].set_visible(False)
        ax.text(.5,1.44,f"原始比值 {d['raw_median_ratio_diagnostic_only']:.3f}× · 仅诊断",ha='center',color='#9C3A26',weight='bold')
    save(fig, 'g2-diagnostic')


def html_report():
    from markdown_it import MarkdownIt
    md = MarkdownIt('commonmark', {'html': True}).enable('table')
    body = md.render(REPORT.read_text())
    # Keep offline HTML self-contained; evidence links open the public repository.
    def image_data(m):
        path = (REPORT.parent / m.group(1)).resolve()
        return 'src="data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode() + '"'
    body = re.sub(r'src="(figures/[^\"]+\.png)"', image_data, body)
    def link(m):
        url = m.group(1)
        if url.startswith(('https:', 'http:', '#', 'mailto:')): return m.group(0)
        file, _, fragment = url.partition('#')
        rel = (REPORT.parent / file).resolve().relative_to(ROOT).as_posix()
        return 'href="https://github.com/bxf1/sciresearch-bench-lite/blob/main/' + rel + ('#'+fragment if fragment else '') + '"'
    body = re.sub(r'href="([^\"]+)"', link, body)
    # Main report uses a plain step list, so no JavaScript diagram renderer is required.
    headings = []
    def heading(m):
        title = m.group(1); anchor = 'section-' + str(len(headings)+1)
        headings.append((anchor,title))
        return f'<h2 id="{anchor}">{title}</h2>'
    body = re.sub(r'<h2>(.*?)</h2>', heading, body)
    nav = ''.join(f'<a href="#{a}">{t}</a>' for a,t in headings)
    style = '''
    :root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#edf2f6;color:#203044;font:16px/1.85 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans CJK SC",sans-serif}
    main{max-width:1040px;margin:36px auto;background:white;padding:55px 64px;box-shadow:0 8px 40px #173c5012;border-top:7px solid #176b87}h1{font-size:31px;line-height:1.4;color:#123d54}h2{font-size:24px;color:#176b87;margin-top:48px;padding-bottom:9px;border-bottom:1px solid #dbe6ed;scroll-margin-top:20px}h3{font-size:19px;margin-top:28px}a{color:#176b87;text-underline-offset:3px}p{margin:14px 0}nav{background:#f1f7fa;border-radius:10px;padding:20px 24px;display:grid;grid-template-columns:1fr 1fr;gap:6px 20px;margin:26px 0}nav a{font-size:14px;text-decoration:none}table{width:100%;border-collapse:collapse;margin:22px 0;font-size:13px;line-height:1.65}th{background:#eaf3f7;color:#123d54}th,td{padding:9px 8px;border-bottom:1px solid #dce5eb;text-align:left}tr:nth-child(even){background:#f8fafc}img{display:block;max-width:100%;height:auto;margin:20px auto}blockquote{border-left:4px solid #d66a28;background:#fff7ee;padding:8px 20px;margin:24px 0}code{font-size:.88em;background:#f0f3f6;padding:2px 4px;border-radius:3px;overflow-wrap:anywhere}pre{background:#f3f6f8;padding:18px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.6}pre code{padding:0;background:none}li{margin:6px 0}footer{color:#607587;border-top:1px solid #dce5eb;margin-top:40px;padding-top:16px;font-size:13px}
    @media(max-width:720px){main{padding:24px 18px;margin:0}h1{font-size:25px}nav{grid-template-columns:1fr}table{display:block;overflow-x:auto;white-space:normal}}
    @media print{body{background:white;font-size:10pt;line-height:1.6}main{max-width:none;margin:0;padding:0;box-shadow:none;border:0}nav{display:none}h1{font-size:22pt}h2{font-size:16pt;break-after:avoid}h3{break-after:avoid}h2+p,h3+p,p:has(img){break-after:avoid}img,pre,tr{break-inside:avoid}table{font-size:8pt;line-height:1.5;break-inside:avoid}th,td{padding:6px}p{orphans:3;widows:3}a{color:inherit;text-decoration:none}@page{size:A4;margin:18mm 16mm}}
    '''
    start = body.index('</h1>') + len('</h1>')
    body = body[:start] + '<nav aria-label="目录">' + nav + '</nav>' + body[start:]
    path = REPORT.with_suffix('.html')
    path.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SciResearch-Bench-Lite 最终实验报告</title><style>'+style+'</style><main>'+body+'<footer>由同目录 Markdown 报告生成；图像已内嵌，可离线阅读。外部证据链接指向公开仓库。</footer></main></html>')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--figures', action='store_true')
    parser.add_argument('--html', action='store_true')
    parser.add_argument('--font', help='Optional CJK font path; otherwise use local matplotlib font configuration.')
    args = parser.parse_args()
    data = build_data()
    fill_tables(data)
    if args.figures: figures(data, args.font)
    if args.html: html_report()
    print(json.dumps({'ordered_rows': len(data['rows']), 'valid_thinking_scores': 14, 'g2_formal_score': None,
                      'new_model_calls': 0, 'new_candidate_executions': 0, 'figures_generated': args.figures,
                      'html_generated': args.html}))
