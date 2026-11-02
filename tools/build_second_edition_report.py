"""Build a second-edition-only scientific report from immutable saved evidence."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/second-edition-report-2026-11-01'
FIG = ROOT / 'docs/figures/second-edition-report-2026-11-01'
REPORT = ROOT / 'docs/second-edition-report-20261101.md'
PDF = 'output/pdf/sciresearch-second-edition-report-20261101.pdf'
ARCHIVE = 'archives/pre-second-edition-report-20261101/manifest.json'
OFFICIAL = 'results/unified-r1-nine-2026-10-29/reviewed-results.json'
RERUN = 'results/ode-g1-r1-rerun-2026-10-29/reviewed-results.json'
CALIBRATION = 'results/comparisons/calibration-summary.json'
SPLITS = 'data/split-summary.json'
PROFILE = 'freezes/t3-profile-local-001.json'

def read(path):
    return json.loads((ROOT / path).read_text())

def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()

def ref(path):
    return {'path': str(path), 'sha256': sha(path)}

def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                       '|' + '|'.join(['---'] * len(headers)) + '|'] +
                      ['| ' + ' | '.join(str(v) for v in row) + ' |' for row in rows])

def preserve():
    saved = read(ARCHIVE)
    for name, expected in saved['files'].items():
        assert sha(Path(ARCHIVE).parent / name) == expected
    for name, expected in saved['preserved_originals'].items():
        assert sha(name) == expected, name
    return saved

def make_figures(rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font = '/System/Library/Fonts/Hiragino Sans GB.ttc'
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family': font_manager.FontProperties(fname=font).get_name(),
                         'font.size': 10, 'axes.unicode_minus': False,
                         'svg.fonttype': 'path', 'svg.hashsalt': 'second-edition-20261101'})
    FIG.mkdir(parents=True, exist_ok=True)
    files = {}
    def save(fig, name):
        for suffix in ('png', 'svg'):
            path = FIG / (name + '.' + suffix)
            fig.savefig(path, dpi=300, metadata={'Date': None} if suffix == 'svg' else {'Software': 'SciResearch report'})
            files[path.relative_to(ROOT).as_posix()] = sha(path)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 1.9))
    counts = [sum(r['reward'] == 1 for r in rows if r['task'] == t) for t in ('heat', 'ode', 'poisson')]
    ax.barh(['Heat', 'ODE', 'Poisson'], counts, color='#176B87', height=.60)
    ax.invert_yaxis()
    ax.set(xlim=(0, 3.25), xticks=[0, 1, 2, 3], xlabel='成功研究会话数（每任务共 3 个 r1）')
    for y, count in enumerate(counts):
        ax.text(count - .15, y, f'{count}/3', va='center', ha='right', color='white', fontsize=11)
    ax.spines[['top', 'right']].set_visible(False)
    fig.subplots_adjust(left=.11, right=.97, top=.95, bottom=.29)
    save(fig, 'outcomes')
    for paired, name in ((False, 'final-scores'), (True, 'first-final-scores')):
        fig, axes = plt.subplots(1, 3, figsize=(7, 2.65 if paired else 2.15), sharey=True)
        for ax, task, label in zip(axes, ('heat', 'ode', 'poisson'), ('Heat', 'ODE', 'Poisson')):
            selected = [r for r in rows if r['task'] == task]
            x = range(3)
            if paired:
                left = ax.bar([v-.18 for v in x], [r['first_score'] for r in selected], .35, color='#176B87', label='首次候选')
                right = ax.bar([v+.18 for v in x], [r['final_score'] for r in selected], .35, color='#D16B24', label='最终候选')
                for a, b in zip(left, right):
                    for bar, lift in ((a, 3), (b, 15 if abs(a.get_height()-b.get_height()) < 12 else 3)):
                        ax.annotate(f'{bar.get_height():.1f}', (bar.get_x()+bar.get_width()/2, bar.get_height()),
                                    xytext=(0, lift), textcoords='offset points', ha='center', fontsize=9)
            else:
                bars = ax.bar(list(x), [r['final_score'] for r in selected], .55, color='#176B87')
                ax.bar_label(bars, fmt='%.1f', padding=4, fontsize=10)
            ax.set(title=label, xticks=list(x), xticklabels=['G1', 'G2', 'G3'], ylim=(0, 122), yticks=[0,25,50,75,100])
            ax.spines[['top', 'right']].set_visible(False)
            ax.spines[['left', 'bottom']].set_color('#A5B2BC')
            ax.grid(axis='y', color='#E6EBEF', linewidth=.7)
            ax.set_axisbelow(True)
        axes[0].set_ylabel('分数')
        if paired:
            handles, labels = axes[0].get_legend_handles_labels()
            fig.legend(handles, labels, loc='lower center', ncol=2, frameon=False)
        fig.subplots_adjust(left=.09, right=.99, top=.88, bottom=.25 if paired else .17, wspace=.20)
        save(fig, name)
    return {'scope': 'second_edition_nine_r1_only', 'source': ref(OFFICIAL),
            'outcomes': counts, 'plot_rows': [{k: r[k] for k in ('run_id','task','group','first_score','final_score','reward')} for r in rows],
            'format': 'SVG vector in PDF; PNG preview only', 'files': files}

def main():
    saved = preserve()
    original = read(OFFICIAL)
    rerun, calibration, splits = read(RERUN), read(CALIBRATION), read(SPLITS)
    assert original['new_sessions'] == 9 and original['new_reward_one'] == 8
    assert original['latest_research_finished_at'] < original['first_hidden_replay_started_at']
    fields = ('report_id','label','task','group','run_id','attempt_id','status','first_score','final_score','reward',
              'evaluation_status','passed_per_replay','speedup','public_evaluations','output_tokens','research_wall_seconds',
              'first_id','final_id','failed_requests','compaction_requests','one_token_requests',
              'host_evidence','registry_evidence','relay_evidence','score_evidence')
    rows = [{k: row[k] for k in fields} for row in original['rows']]
    OUT.mkdir(parents=True, exist_ok=True)
    figures = make_figures(rows)
    (OUT/'figure-manifest.json').write_text(json.dumps(figures, ensure_ascii=False, indent=2)+'\n')
    methods = {'ls':'无正则 LS','rank5':'5 模态 LS','tikhonov':'固定 Tikhonov','discrepancy':'discrepancy Tikhonov','tsvd':'TSVD',
               'raw':'原始差分','fixed':'固定平滑 + STLSQ','search':'公开验证选参','cg':'CG','jacobi':'Jacobi-CG','lu':'LU 复用四 RHS'}
    labels = {'heat':'Heat','ode':'ODE','poisson':'Poisson'}
    replacements = {
        'CALIBRATION_TABLE': table(['任务','作者方法','校验通过 / 12','校验数值分'],
            [[labels[r['task']],methods[r['method']],f"{r['passed']} / {r['total']}",f"{r['score']:.3f}" if r['score'] is not None else '—（仅数值验收）'] for r in calibration['methods']]),
        'SPLIT_TABLE': table(['划分','每任务数量','三任务合计','每任务易/中/难','使用者与作用'], [
            ['public-dev 开发集',6,18,'2 / 2 / 2','Agent 研究、公开反馈和候选迭代'],
            ['author-calibration 作者校验集',12,36,'4 / 4 / 4','作者验证数据、规则、参考方法及效率门槛'],
            ['final-test 测试集',12,36,'4 / 4 / 4','研究关闭后的可信独立评分']]),
        'EXPLORATION_TABLE': table(['会话','公开评估次数','已知输出 token','研究分钟','研究结束状态'],
            [[r['label'],r['public_evaluations'],f"{r['output_tokens']:,}",f"{r['research_wall_seconds']/60:.2f}",r['status']] for r in rows]),
        'RESULT_TABLE': table(['序号','会话','最终分','数值通过（三次）','reward','正式加速比'],
            [[r['report_id'],r['label'],f"{r['final_score']:.3f}",'12/12/12' if r['passed_per_replay'] else '无候选，无重放',r['reward'],f"{r['speedup']:.3f}×" if r['speedup'] is not None else '—'] for r in rows]),
        'ITERATION_TABLE': table(['会话','首次候选测试分','最终候选测试分','会话内分差'],
            [[r['label'],f"{r['first_score']:.3f}",f"{r['final_score']:.3f}",f"{r['final_score']-r['first_score']:+.3f}"] for r in rows]),
        'RERUN_TABLE': table(['指标','ODE G1 独立补跑'],[
            ['最终分数 / reward','0.000 / 0'],['首次 / 最终登记候选','无 / 无'],['研究状态','research_timeout'],
            ['公开评估次数',0],['已知输出 token',f"{rerun['all_attempt_known_output_tokens']:,}"],
            ['研究分钟',f"{rerun['retained_attempt']['research_wall_seconds']/60:.2f}"],['隐藏重放','未执行：没有候选']]),
    }
    report = (ROOT/'tools/templates/second-edition-report-20261101.md').read_text()
    for key, value in replacements.items():
        assert report.count('{{'+key+'}}') == 1
        report = report.replace('{{'+key+'}}', value)
    assert '{{' not in report and not any(t in report for t in ('第一版','old-new','历史对照'))
    REPORT.write_text(report)
    source_paths = [OFFICIAL,RERUN,CALIBRATION,SPLITS,PROFILE,'data/case-index.csv','data/file-manifest.json',
                    'docs/task_cards.md','docs/heat.md','docs/ode.md','docs/poisson.md',
                    'logs/heat-unified-r1-2026-10-29/scorer-tests.json','logs/heat-unified-r1-2026-10-29/executor-validation.json']
    analysis = {'scope':'second_edition_only','editorial_date':'2026-11-01','experiment_date':'2026-10-29',
        'official_sessions':9,'official_successes':8,'attempts':original['new_attempts'],'rows':rows,
        'totals':{'public_evaluations':original['new_public_evaluations'],'retained_output_tokens':original['new_output_tokens'],
                  'retained_wall_seconds':original['new_research_wall_seconds'],'all_attempt_known_output_tokens':original['all_new_attempt_known_output_tokens'],
                  'all_attempt_charged_output_tokens':original['all_new_attempt_charged_output_tokens']},
        'supplement':{'sessions':1,'pooled':False,'final_score':rerun['final_score'],'reward':rerun['reward'],'source':ref(RERUN)},
        'calibration_methods':calibration['methods'],'splits':splits,'profile':read(PROFILE)['profile'],
        'source_sha256':{n:sha(n) for n in source_paths},'archive':ref(ARCHIVE),
        'preserved_originals':saved['preserved_originals'],'figure_manifest':ref('results/second-edition-report-2026-11-01/figure-manifest.json'),
        'report_path':REPORT.relative_to(ROOT).as_posix(),'pdf_path':PDF,'new_model_calls':0,'new_candidate_executions':0}
    (OUT/'analysis.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2)+'\n')
    import build_final_report as renderer
    from finalize_submission_report import improve_pdf_quality
    renderer.REPORT = REPORT
    renderer.html_report(local_evidence=True)
    path = REPORT.with_suffix('.html')
    html = improve_pdf_quality(path.read_text(), report)
    for glyph, character in (('₀','0'),('₁','1'),('₂','2'),('ₖ','k')):
        html = html.replace(glyph, '<sub>'+character+'</sub>')
    html = html.replace('<td>Poisson</td>', '<td class="nowrap">Poisson</td>')
    for title in ('2.3 ODE：解析方程与高精度积分生成真值',
                  '3.3 作者校验集的实际验收结果','5.3 实际探索量与研究结局','6.3 同一会话首次与最终候选的测试集差异',
                  '8.3 基础设施失败与计时噪声需单独核算'):
        html = html.replace('<h3>'+title+'</h3>', '<h3 class="new-page">'+title+'</h3>')
    css = '''
    .equation{background:#f0f6f9;border-left:3px solid #176b87;padding:10px 16px;margin:14px 0;font-size:1.05em}
    @media print{
      h2{break-before:page;margin-top:0}h2#section-1{break-before:auto;margin-top:7mm}
      h3{margin-top:5mm}.new-page{break-before:page;margin-top:0}
      li,.equation{break-inside:avoid}p:has(img){break-after:auto}
      th:first-child{min-width:52px}table{break-inside:avoid}.nowrap{white-space:nowrap}
    }
    '''
    path.write_text(html.replace('</style>',css+'</style>'))
    preserve()
    print(json.dumps({'status':'built','official_sessions':9,'successes':8,'comparison_versions':0,'charts':3,'supplement_pooled':False,'new_model_calls':0,'new_candidate_executions':0}))

if __name__ == '__main__':
    main()
