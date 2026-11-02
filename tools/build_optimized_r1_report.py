"""Create the optimized-batch report from audited results and source-backed notes."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/optimized-r1-20261101'
LOG = ROOT / 'logs/optimized-r1-20261101'
FIG = ROOT / 'docs/figures/optimized-r1-20261101'
REPORT = ROOT / 'docs/optimized-r1-report-20261101.md'
PDF = ROOT / 'output/pdf/sciresearch-optimized-r1-report-20261101.pdf'
TASKS = ('heat', 'ode', 'poisson')
LABELS = {'heat': 'Heat', 'ode': 'ODE', 'poisson': 'Poisson'}
PROFILES = {'amplitude': '幅度 0.5 / 2 倍', 'spectral_decay': '谱衰减 1 / 3',
            'contiguous_mask': '连续缺失 25%', 'coordinate_scale': '非等比缩放',
            'coordinate_swap': '坐标交换', 'stable_cubic': '稳定三次系统',
            'large_grid': '256 × 256 网格', 'five_disks': '五圆系数', 'cache_order': '交错算子 / RHS'}
STATUS = {'completed': '主动结束', 'research_timeout': '研究硬截止', 'output_budget_exhausted': '输出预算耗尽',
          'api_failed': 'API 失败', 'infrastructure_failed': '基础设施失败',
          'valid': '有效', 'evaluation_invalid': '评估无效', 'invalid': '无效',
          'no_valid_candidate': '无合法候选', 'infrastructure_invalid': '基础设施无效',
          'no_valid_submission': '无合法提交',
          'deadline_fallback': '截止回退', 'explicit_finalization': '显式提交', 'explicit_finalize': '显式提交'}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fmt(x, digits=3):
    return '—' if x is None else f'{x:.{digits}f}'


def sci(x):
    return '—' if x is None else f'{x:.2e}'


def table(headers, rows):
    def cell(x):
        return str(x).replace('|', '&#124;').replace('\n', '<br>')
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '|' + '|'.join(['---'] * len(headers)) + '|']
                     + ['| ' + ' | '.join(cell(x) for x in row) + ' |' for row in rows])


def scientific_pass_text(n, *, no_candidate=False):
    if not n['replays_observed']:
        return '未交付' if no_candidate else '未测'
    return f"{n['passed_all_observed_replays']} / {n['expected_cases']}"


def charts(rows):
    os.environ.setdefault('MPLCONFIGDIR', str(OUT / 'matplotlib-cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font = '/System/Library/Fonts/Hiragino Sans GB.ttc'
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family': font_manager.FontProperties(fname=font).get_name(), 'font.size': 9,
                         'axes.unicode_minus': False, 'svg.fonttype': 'path', 'svg.hashsalt': 'optimized-r1-20261101'})
    FIG.mkdir(parents=True, exist_ok=True)
    files = {}
    def save(fig, name):
        for suffix in ('svg', 'png'):
            path = FIG / f'{name}.{suffix}'
            fig.savefig(path, dpi=300, metadata={'Date': None} if suffix == 'svg' else {'Software': 'SciResearch'})
            files[str(path.relative_to(ROOT))] = sha(path)
        plt.close(fig)
    for paired, name in ((False, 'final-scores'), (True, 'first-final-scores')):
        fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.55 if paired else 2.20), sharey=True)
        for ax, task in zip(axes, TASKS):
            selected = [r for r in rows if r['task'] == task]
            for i, row in enumerate(selected):
                values = ((row['first_score'], -.18, '#176b87'), (row['final_score'], .18, '#cf762c')) if paired else ((row['final_score'], 0, '#176b87'),)
                for j, (value, offset, color) in enumerate(values):
                    x = i + offset
                    if value is None:
                        ax.text(x, 4 + 11 * j, '无效', color='#9b3c3c', ha='center', fontsize=8, rotation=90 if paired else 0)
                        continue
                    ax.bar(x, value, .34 if paired else .55, color=color)
                    close = paired and row['first_score'] is not None and row['final_score'] is not None and abs(row['first_score'] - row['final_score']) < 10
                    ax.annotate(f'{value:.1f}', (x, value), xytext=(0, 14 if close and j else 3),
                                textcoords='offset points', ha='center', fontsize=8)
            ax.set(title=LABELS[task], xticks=[0, 1, 2], xticklabels=['G1', 'G2', 'G3'], ylim=(0, 123), yticks=[0, 25, 50, 75, 100])
            ax.spines[['top', 'right']].set_visible(False)
            ax.grid(axis='y', color='#e6ebef', linewidth=.7); ax.set_axisbelow(True)
        axes[0].set_ylabel('主任务分数')
        if paired:
            from matplotlib.patches import Patch
            fig.legend(handles=[Patch(color='#176b87', label='首次候选'), Patch(color='#cf762c', label='最终候选')],
                       loc='lower center', ncol=2, frameon=False)
        fig.subplots_adjust(left=.08, right=.99, bottom=.25 if paired else .17, top=.87, wspace=.20)
        save(fig, name)
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.6))
    import numpy as np
    from matplotlib.colors import ListedColormap, BoundaryNorm
    cmap = ListedColormap(['#f2e2dd', '#eed4af', '#c7dedb', '#87bbb5', '#267c84']); cmap.set_bad('#eeeeee')
    plot = []
    for ax, task in zip(axes, TASKS):
        selected = [r for r in rows if r['task'] == task]
        keys = [k for k in selected[0]['diagnostics'] if k.endswith('/forward')]
        data = np.full((3, 3), np.nan)
        for i, row in enumerate(selected):
            for j, key in enumerate(keys):
                n = row['diagnostics'][key]['numeric']
                if n['replays_observed']:
                    data[i, j] = n['passed_all_observed_replays']
                label = scientific_pass_text(n, no_candidate=row['diagnostic_status'] == 'no_valid_candidate')
                ax.text(j, i, label.replace(' ', ''), ha='center', va='center', color='white' if data[i, j] >= 4 else '#233b45', fontsize=9)
                plot.append({'run_id': row['run_id'], 'profile': key, 'numeric': n})
        from matplotlib.patches import Rectangle
        norm = BoundaryNorm([-.5, .5, 1.5, 2.5, 3.5, 4.5], 5)
        for i in range(3):
            for j in range(3):
                color = '#eeeeee' if np.isnan(data[i, j]) else cmap(norm(data[i, j]))
                ax.add_patch(Rectangle((j-.5, i-.5), 1, 1, facecolor=color, edgecolor='white', linewidth=1))
        ax.set(xlim=(-.5, 2.5), ylim=(2.5, -.5), aspect='equal')
        ax.set(title=LABELS[task], xticks=[0, 1, 2], yticks=[0, 1, 2], yticklabels=['G1', 'G2', 'G3'])
        labels = {'heat': ['幅度', '谱衰减', '连续缺失'], 'ode': ['缩放', '交换', '新结构'], 'poisson': ['大网格', '五圆', '缓存']}[task]
        ax.set_xticklabels(labels, fontsize=8); ax.tick_params(length=0)
        for spine in ax.spines.values(): spine.set_visible(False)
    fig.subplots_adjust(left=.06, right=.99, top=.86, bottom=.13, wspace=.35)
    save(fig, 'diagnostic-pass')
    return {'scope': 'optimized_r1_nine_only', 'files': files,
            'score_rows': [{k: r[k] for k in ('run_id', 'first_score', 'final_score')} for r in rows],
            'diagnostic_plot_rows': plot, 'format': 'SVG vector in PDF; PNG preview only'}


def main():
    analysis = read(OUT / 'analysis.json')
    assert analysis['scope'] == 'optimized_r1_nine_only' and analysis['scientific_sessions'] == 9
    for item in analysis['source_evidence']:
        assert sha(ROOT / item['path']) == item['sha256'], item['path']
    notes = read(OUT / 'method-analysis.json')
    rows = analysis['rows']; methods = notes['methods']
    assert {r['run_id'] for r in methods} == {r['run_id'] for r in rows}
    for item in methods:
        assert item['method'] and item['exploration'] and item['changes'] and item['limitations']
        for source in item['evidence']:
            assert sha(ROOT / source['path']) == source['sha256']
    totals = analysis['totals']
    figures = charts(rows)
    (OUT / 'figure-manifest.json').write_text(json.dumps(figures, ensure_ascii=False, indent=2) + '\n')
    cal = read(LOG / 'main-calibration/summary.json')['methods']
    dcal = read(LOG / 'diagnostic-calibration/summary.json')['rows']
    method_names = {'ls': '无正则 LS', 'rank5': '5 模态 LS', 'tikhonov': '固定 Tikhonov',
                    'discrepancy': 'discrepancy Tikhonov', 'tsvd': 'TSVD', 'raw': '原始差分',
                    'fixed': '固定平滑 + STLSQ', 'search': '公开验证选参', 'cg': 'CG',
                    'jacobi': 'Jacobi-CG', 'lu': 'LU 复用四 RHS'}
    exploration = table(['会话', '首次合法 / 分钟', '评估请求 / 接受', '源码版本', '可见 shell 命令', '结束状态'],
        [[r['label'], fmt((r['exploration']['first_valid_registration_seconds'] or 0)/60, 2) if r['exploration']['first_valid_registration_seconds'] is not None else '无',
          str(r['exploration']['received_public_evaluation_requests']) + ' / ' + str(r['exploration']['accepted_public_evaluations']), r['exploration']['unique_registered_source_hashes'],
          r['exploration']['observed_shell_commands'], STATUS.get(r['host_status'], r['host_status'])] for r in rows])
    cost = table(['会话', 'attempt 数', '研究分钟（全部）', '已知输出 token', '预算计入 token', '最终选择'],
        [[r['label'], r['attempt_count'], fmt(r['all_attempt_research_wall_seconds']/60, 2),
          f"{r['all_attempt_known_output_tokens']:,}", f"{r['all_attempt_charged_output_tokens']:,}",
          STATUS.get(r['selection_reason'], r['selection_reason'] or '无')] for r in rows])
    model_records = [a['model_request_audit'] for a in analysis['attempts'] if a['model_request_audit']['observed']]
    cost += ('\n\n运行期请求证据：共 ' + str(sum(a['requests_with_output_over_4096'] for a in model_records))
             + ' 次响应的已知输出超过 4096 token，最大为 '
             + f"{max((a['largest_observed_output_tokens'] for a in model_records), default=0):,}"
             + ' token；原生压缩请求共 ' + str(sum(a['native_compaction_requests'] for a in model_records))
             + ' 次。16,384 是单次请求上限；原生压缩及续接/上下文剩余额度可以请求更少 token。'
             + '单 token 请求共 ' + str(sum(a['one_token_requests'] for a in model_records)) + ' 次。')
    failed = [a for a in analysis['attempts'] if a['model_request_audit'].get('failed_requests')]
    if failed:
        labels = {r['run_id']: r['label'] for r in rows}
        cost += '\n\n**请求层失败与恢复。**原生请求重试发生在同一研究 attempt 内，不增加科学会话数。下表时间是失败请求实际占用时间，不含退避，也不从研究总成本扣除。未知输出按冻结策略计入保留额度；“已知输出为零”不表示实际生成量为零。\n\n'
        cost += table(['会话 / attempt', '失败请求', '占用请求秒', '输出未知请求', '失败请求计入预算 token'],
                      [[labels[a['run_id']] + ' / a' + a['attempt_id'].rsplit('-a', 1)[-1],
                        a['model_request_audit']['failed_requests'], fmt(a['model_request_audit']['failed_request_wall_seconds'], 1),
                        a['model_request_audit']['failed_requests_with_unknown_output'],
                        f"{a['model_request_audit']['failed_request_charged_output_tokens']:,}"] for a in failed])
    methods_text = []
    for index, row in enumerate(rows, 2):
        m = next(m for m in methods if m['run_id'] == row['run_id'])
        evidence_links = '；'.join(f"[{Path(s['path']).name}](../{s['path']})" for s in m['evidence'])
        methods_text.append(f"### 5.{index} {row['label']}：{m['title']}\n\n**方法。**{m['method']}\n\n**探索路径。**{m['exploration']}\n\n**关键修改与选择。**{m['changes']}\n\n**限制。**{m['limitations']}\n\n证据：{evidence_links}。")
    main_table = table(['会话', '最终分', '三次通过数（各12例）', 'reward', '正式加速比', '主结果状态'],
        [[r['label'], fmt(r['final_score']), (' / '.join(map(str, r['main_numeric']['final']['overall']['passed_per_replay'])) or '无执行') + (' †' if r['main_numeric']['final']['numeric_origin'].startswith('accuracy_only') else ''),
          '—' if r['reward'] is None else r['reward'], fmt((r['main_numeric']['final']['timing'] or {}).get('speedup')) + ('×' if (r['main_numeric']['final']['timing'] or {}).get('speedup') is not None else ''),
          STATUS.get(r['evaluation_status'], r['evaluation_status'])] for r in rows])
    main_table += '\n\n† Poisson G2 的三次数值检查在正式计时准入全部失败后独立补齐，只复用封存候选；主分、reward 和加速比仍为空。该补检不增加研究会话或测试实例。ODE G1 的有效零分来自未提交，并非执行后的数值错误。[数值补检证据](../results/optimized-r1-20261101/numeric-only-supplement.json)'
    level_tables = []
    for task in TASKS:
        data = []
        for row in (r for r in rows if r['task'] == task):
            for level, n in row['main_numeric']['final']['by_level'].items():
                metrics = list(n['metrics'].values())
                data.append([row['group'].upper(), ['易', '中', '难'][int(level)], scientific_pass_text(n, no_candidate=row['selection_reason'] == 'no_valid_submission'),
                             sci(metrics[0]['median']) + ' / ' + sci(metrics[0]['max']),
                             sci(metrics[1]['median']) + ' / ' + sci(metrics[1]['max'])])
        metric_names = {'heat': ('初场误差', '未来场误差'), 'ode': ('轨迹误差', '场误差'), 'poisson': ('最大相对残差', '最大解误差')}[task]
        level_tables.append(f"**{LABELS[task]} 分难度误差。**每格为已执行重放中逐例指标的中位数 / 最大值；通过要求同一实例在所有观察重放通过。\n\n" + table(['组别', '难度', '通过 / 4', metric_names[0], metric_names[1]], data))
    diagnostic_tables = []
    for task in TASKS:
        data = []
        for row in (r for r in rows if r['task'] == task):
            for key, result in row['diagnostics'].items():
                if key.endswith('/reverse'): continue
                n = result['numeric']; metrics = list(n['metrics'].values())
                data.append([row['group'].upper(), PROFILES[key.split('/')[0]], scientific_pass_text(n, no_candidate=row['diagnostic_status'] == 'no_valid_candidate'),
                             sci(metrics[0]['max']), sci(metrics[1]['max'])])
        metric_names = {'heat': ('最大初场误差', '最大未来场误差'), 'ode': ('最大轨迹误差', '最大场误差'), 'poisson': ('最大相对残差', '最大解误差')}[task]
        diagnostic_tables.append(f"**{LABELS[task]} 诊断。**\n\n" + table(['组别', '主题', '通过 / 4', *metric_names], data))
    cache_rows = []
    for row in (r for r in rows if r['task'] == 'poisson'):
        for direction in ('forward', 'reverse'):
            result = row['diagnostics']['cache_order/' + direction]; n = result['numeric']; t = result['timing'] or {}
            cache_rows.append([row['group'].upper(), '正序' if direction == 'forward' else '逆序', scientific_pass_text(n),
                               sci(n['metrics']['max_solution_error']['max']), fmt(t.get('speedup')), STATUS.get(t.get('performance_status'), t.get('performance_status') or '未测')])
    resource_rows = []
    for row in rows:
        result = row['main_numeric']['final']; res = result['resources']; t = result['timing'] or {}
        resource_rows.append([row['label'] + (' †' if result['numeric_origin'].startswith('accuracy_only') else ''), fmt(res['execution_wall_seconds']['median']), fmt(res['cpu_seconds']['median']),
                              fmt(res['memory_peak_bytes']['max']/2**20, 1) if res['memory_peak_bytes']['max'] is not None else '—',
                              t.get('measurement_attempts') if row['task'] == 'poisson' else '不适用'])
    resources_text = table(['主任务最终候选', '端到端秒（中位数）', 'CPU 秒（中位数）', '峰值 MiB（最大）', '实际测量尝试'], resource_rows)
    resources_text += '\n\n† 该行资源值来自三次数值补检，没有安静窗口资格；“实际测量尝试”仅统计正式 BCCBBC，故为 0。其他 Poisson 行采用首次有效窗口。CPU 与墙钟测量范围不同，不能用两列相除反推候选的并行度。'
    for task in TASKS:
        drows = []
        for row in (r for r in rows if r['task'] == task):
            for key, result in row['diagnostics'].items():
                if task != 'poisson' and not key.startswith('amplitude/' if task == 'heat' else 'coordinate_scale/'):
                    continue
                res = result['resources']; t = result['timing'] or {}
                drows.append([row['group'].upper(), '诊断 12 例整批' if task != 'poisson' else PROFILES[key.split('/')[0]] + ('（逆）' if key.endswith('/reverse') else ''),
                              fmt(res['execution_wall_seconds']['median']), fmt(res['cpu_seconds']['median']),
                              fmt(res['memory_peak_bytes']['max']/2**20, 1) if res['memory_peak_bytes']['max'] is not None else '—', fmt(t.get('speedup'))])
        resources_text += f'\n\n**{LABELS[task]} 诊断资源。**\n\n' + table(['组别', '执行范围', '端到端秒', 'CPU 秒', '峰值 MiB', '加速比'], drows)
    failures = []
    for row in rows:
        fails = row['main_numeric']['final']['overall']['failures']
        if row['reward'] != 1 or fails:
            failures.append([row['label'], STATUS.get(row['reason'], row['reason']) or ('计时无效' if row['final_score'] is None else '数值或效率条件未通过'),
                             ', '.join(f['id'][:10] for f in fails) or '见运行 / 提交记录'])
    failure_text = table(['会话', '主任务失败 / 无效原因', '失败实例 ID 前缀'], failures) if failures else '九组主任务均通过各自的科学与效率门槛。诊断失败实例仍完整保留在逐例结果中。'
    failure_text += '\n\n' + notes['failure_analysis']
    diagnostic_failures = [[row['label'], PROFILES[key.split('/')[0]], f['id'],
                           ', '.join(f'{metric}={sci(max(o[metric] for o in f["observations"]))}' for metric in result['numeric']['metrics'])]
                          for row in rows for key, result in row['diagnostics'].items()
                          for f in result['numeric']['failures']]
    if diagnostic_failures:
        failure_text += '\n\n**诊断失败实例。**同一数据由三组共享，因此重复 ID 表示不同候选在同一实例上的结果。\n\n' + table(['会话', '主题', '实例 ID', '误差'], diagnostic_failures)
    from datetime import datetime, timezone, timedelta
    def moment(x): return datetime.fromtimestamp(x, timezone(timedelta(hours=8))).isoformat(timespec='milliseconds')
    replacements = {
        'OVERVIEW': f"本批共关闭 9 个研究会话，使用 {totals['attempts']} 个 attempt；{totals['valid_main_results']} 组取得有效主结果，{totals['reward_one']} 组 reward 为 1。共有 {totals['registered_final_candidates']} 组封存最终源码。全部 attempt 已知输出 {totals['known_output_tokens_all_attempts']:,} token，计入预算 {totals['charged_output_tokens_all_attempts']:,} token。主任务与诊断分开报告，失败结果保留。",
        'SPLIT_TABLE': table(['划分', '每任务', '三任务合计', '用途'], [['公开开发集', 6, 18, 'Agent 探索与反馈'], ['主任务作者校验集', 12, 36, 'GT、规则与参考方法验收'], ['主任务测试集', 12, 36, '正式主分'], ['诊断作者校验集', 12, 36, '新增题与运行可行性'], ['诊断测试集', 12, 36, '只执行封存最终候选']]),
        'CALIBRATION_TABLE': table(['任务', '作者方法', '通过 / 12', '校验数值分'], [[LABELS[r['task']], method_names[r['method']], f"{r['result'].get('passed', 0)} / 12", fmt(r['result'].get('score'))] for r in cal]),
        'DIAGNOSTIC_CALIBRATION_TABLE': table(['任务 / 主题', '方法', '通过', '整批运行秒'], [[LABELS[r['task']] + ' / ' + ('全部主题' if '/all/' in r['profile'] else PROFILES[r['profile'].split('/')[1]]), method_names[r['method']], f"{r['result']['passed']} / {r['result']['total']}", fmt(r['result']['worker']['execution_wall_seconds'])] for r in dcal]),
        'EXPLORATION_TABLE': exploration, 'COST_TABLE': cost, 'METHODS': '\n\n'.join(methods_text),
        'CLOSURE': f"宿主确认九组研究全部关闭于 {moment(analysis['research_closed_at'])}；首次隐藏主测试启动于 {moment(analysis['first_hidden_scoring_at'])}。时间次序与各 attempt 的关闭记录通过核验，测试未反馈给研究 Agent。",
        'RESULT_TABLE': main_table, 'LEVEL_TABLE': '\n\n'.join(level_tables),
        'ITERATION_TABLE': table(['会话', '首次分', '最终分', '分差', '源码复用'], [[r['label'], fmt(r['first_score']), fmt(r['final_score']), fmt(r['final_score'] - r['first_score']) if r['final_score'] is not None and r['first_score'] is not None else '—', r['main_numeric']['final']['reused_from'] or '否'] for r in rows]),
        'DIAGNOSTIC_TABLE': '\n\n'.join(diagnostic_tables), 'CACHE_TABLE': table(['组别', '顺序', '通过 / 4', '最大解误差', '正式加速比', '计时状态'], cache_rows),
        'RESOURCE_TABLE': resources_text, 'FAILURES': failure_text,
        'CONCLUSIONS': notes['conclusions'], 'PROBLEMS': notes['problems'],
        'AUDIT': '冻结清单、数据与 GT 校验、执行器验收、探索时间线和逐例结果构成可复核证据链。报告构建不触发任何新模型研究或候选执行。主结果及诊断使用同一最终快照，图表数字来自机器可读分析。\n\n' + table(['证据', '文件'], [['冻结运行计划', '[plan](../freezes/research-run-plan-optimized-r1-20261101.json)'], ['探索时间线', '[timeline](../results/optimized-r1-20261101/exploration-timeline.json)'], ['封存后的原始结果', '[results](../results/optimized-r1-20261101/results.json)'], ['汇总与成本', '[analysis](../results/optimized-r1-20261101/analysis.json)'], ['方法证据与判断', '[methods](../results/optimized-r1-20261101/method-analysis.json)'], ['数据与 GT 检查', '[GT QC](../logs/optimized-r1-20261101/gt-qc.json)'], ['服务恢复', '[restoration](../logs/optimized-r1-20261101/study-service-restoration.json)']])}
    report = (ROOT / 'tools/templates/optimized-r1-report-20261101.md').read_text()
    for key, value in replacements.items():
        assert report.count('{{' + key + '}}') == 1, key
        report = report.replace('{{' + key + '}}', value)
    assert '{{' not in report
    # CommonMark needs separation after emphasis ending in CJK punctuation.
    report = re.sub(r'(\*\*[^*\n]+\*\*)(?=[A-Za-z0-9\u3400-\u9fff])', r'\1 ', report)
    REPORT.write_text(report)
    import build_final_report as renderer
    from finalize_submission_report import improve_pdf_quality
    renderer.REPORT = REPORT
    renderer.html_report(local_evidence=True)
    html = improve_pdf_quality(REPORT.with_suffix('.html').read_text(), report)
    for index, symbol in enumerate('₀₁₂₃₄₅₆₇₈₉'):
        html = html.replace(symbol, f'<sub>{index}</sub>')
    html = re.sub(r'<p>([^\n]*?)</p>\n<table>', r'<p class="table-caption">\1</p>\n<table>', html)
    html = html.replace('<p><strong>限制。</strong>', '<p class="method-limits"><strong>限制。</strong>')
    html = html.replace('<h3>8.4 ', '<h3 class="final-audit">8.4 ')
    html = html.replace('<p>Heat 应同时关注', '<p class="no-split">Heat 应同时关注')
    html, figures_wrapped = re.subn(r'<p>(<img[^>]+>)</p>\n<p[^>]*>([^\n]+)</p>',
        r'<figure>\1<figcaption>\2</figcaption></figure>', html)
    assert figures_wrapped == 3
    css = '''
    .equation{padding:10px 16px;background:#f0f6f9;border-left:3px solid #176b87;margin:14px 0;line-height:1.7}
    sub{font-size:75%;line-height:0}
    figure{margin:10px 0;break-inside:avoid}figure img{margin:4px auto}figcaption{font-size:9.5pt;line-height:1.5;margin:4px 0}
    @media print{
      h2{break-before:auto;margin-top:9mm}h2#section-1{margin-top:8mm}
      h2#section-5,h2#section-6{break-before:page;margin-top:0}
      h3{margin-top:6mm}table{break-inside:auto}thead{display:table-header-group}tr{break-inside:avoid}
      h3.final-audit{break-before:page;margin-top:0}
      .no-split{break-inside:avoid}
      th,td{padding:5px 6px}td:first-child{white-space:nowrap}p:has(img){break-after:auto}
      .table-caption,.method-limits{break-after:avoid}
      .equation{break-inside:avoid}a{overflow-wrap:anywhere}code{font-size:.85em}
    }
    '''
    REPORT.with_suffix('.html').write_text(html.replace('</style>', css + '</style>'))
    manifest = {'scope': analysis['scope'], 'report_path': str(REPORT.relative_to(ROOT)),
                'pdf_path': str(PDF.relative_to(ROOT)), 'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in
                (OUT / 'analysis.json', OUT / 'method-analysis.json', OUT / 'figure-manifest.json', REPORT,
                 ROOT / 'tools/templates/optimized-r1-report-20261101.md')},
                'new_model_calls': 0, 'new_candidate_executions': 0, 'vector_charts': 3, 'embedded_font_faces': 4}
    (OUT / 'report-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'built', 'rows': len(rows), 'figures': 3, 'report': str(REPORT)}))


if __name__ == '__main__':
    main()
