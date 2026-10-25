"""Build the thinking-only report from immutable saved evidence, without execution.

Standard library builds JSON/tables and verifies provenance. Optional presentation
packages are isolated in tools/report-requirements.txt; no research code changes.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import statistics
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/thinking-r1-report-2026-10-25'
FIG = ROOT / 'docs/figures/thinking-r1-report'
REPORT = ROOT / 'docs/submission-report-2026-10-24.md'
TASKS = ('heat', 'ode', 'poisson')
NAMES = {'heat': 'Heat', 'ode': 'ODE', 'poisson': 'Poisson'}
SOURCES = [
    'results/poisson-timing-recheck-2026-10-25/reviewed-results.json',
    'results/thinking-control-2026-10-25/reviewed-comparison.json',
    'freezes/research-run-plan-thinking-max-2026-10-25.json',
    'research-runs/research-98719c3c1cf3fc92/final-replays/research-98719c3c1cf3fc92-poisson-g2-r1-a001/result.json',
    'logs/poisson-timing-recheck-2026-10-25/g2-window-002/operation-result.json',
    'logs/poisson-timing-recheck-2026-10-25/g2-window-002/host-observations.jsonl',
]
METHODS = {'ls':'未正则化 LS：直接拟合全部模态', 'rank5':'rank5：只保留五个低频模态',
 'tikhonov':'Tikhonov：限制不稳定解（固定参考）', 'discrepancy':'discrepancy：按噪声水平选正则强度',
 'tsvd':'TSVD：截去不稳定的奇异方向', 'raw':'原始差分：直接从噪声轨迹估导数',
 'fixed':'固定去噪和稀疏回归（固定参考）', 'search':'搜索去噪与稀疏参数',
 'cg':'CG：未预条件的共轭梯度', 'jacobi':'Jacobi-CG：对角预条件共轭梯度', 'lu':'LU：一次分解复用四个右端项（固定参考）'}


def read(name):
    return json.loads((ROOT / name).read_text())


def fmt(value):
    return '—' if value is None else f'{value:.3f}'


def build_data():
    current, thinking, plan = [read(s) for s in SOURCES[:3]]
    sources = {s: hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in SOURCES}
    def checked(evidence):
        name = evidence['path']
        digest = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        assert digest == evidence['sha256'], name
        sources[name] = digest
        return read(name)
    assert sources[SOURCES[2]] == '25c3250f8615aa5a90a24206964533085b5448f06910f7e42a969e2f66763f0e'
    assert thinking['latest_research_finished_at'] < thinking['first_baseline_started_at']
    sequence = {r['run_id']: r['sequence'] for r in plan['runs']}
    attempts = {r['attempt_id']: r for r in thinking['attempt_records']}
    rows = []
    for p in sorted(current['pairs'], key=lambda p: (TASKS.index(p['task']), p['group'], p['repeat'])):
        a = attempts[p['attempt_id']]
        registry = checked(a['registry_evidence'])
        host = checked(a['host_evidence'])
        original_evidence = a['replay_evidence']
        if original_evidence is None:
            refusal = next(v for v in thinking['timing_refusals'] if v['identity']==p['run_id'])
            original_evidence = {'path':refusal['acceptance_path'],'sha256':refusal['acceptance_sha256']}
        original_replay = checked(original_evidence)
        assert registry['closed'] and registry['first_id'] == a['first_id'] and registry['final_id'] == a['final_id']
        assert host['attempt_status'] == a['raw_status']
        relay = a['relay_evidence']; assert hashlib.sha256((ROOT/relay['path']).read_bytes()).hexdigest() == relay['sha256']
        sources[relay['path']] = relay['sha256']
        measurement = next((m for m in current['measurements'] if m['run_id'] == p['run_id']), None)
        evidence = measurement['operation_result'] if measurement else a['replay_evidence']
        raw = checked(evidence)['diagnostics'] if measurement else original_replay['diagnostics']
        first, final = raw['first'], raw['final']
        assert final['score'] == p['after']['score'] and final['reward'] == p['after']['reward']
        for role, result in [('first', first), ('final', final)]:
            candidate = next(e for e in registry['evaluations'] if e['id'] == registry[role+'_id'])
            assert result['source_hash'] == candidate['source_hash'] and candidate['artifact_valid']
        repeated = final.get('repeats') or first['repeats']
        batches = repeated[0]['samples']['C'] if p['task']=='poisson' else repeated
        assert len(batches) == 3 and all(b['passed'] == b['total'] == 12 for b in batches)
        rows.append({
            'display_order': len(rows)+1, 'execution_sequence': sequence[p['run_id']],
            'task': p['task'], 'group': p['group'], 'repeat': p['repeat'],
            'label': f"{NAMES[p['task']]} {p['group'].upper()} r{p['repeat']}",
            'run_id': p['run_id'], 'attempt_id': p['attempt_id'], 'attempt_raw_status': a['raw_status'],
            'first_id': a['first_id'], 'final_id': a['final_id'],
            'first_source_hash': first['source_hash'], 'final_source_hash': final['source_hash'],
            'thinking_first_score': first['score'], 'thinking_final_score': final['score'],
            'thinking_reward': final['reward'], 'thinking_has_submission': a['valid_public_candidate'],
            'evaluation_status': final['evaluation_status'], 'numerical_passed': 12, 'unique_cases': 12,
            'first_final_direction': p['first_final_direction'],
            'formal_speedup': repeated[0].get('speedup') if final['score'] is not None else None,
            'output_tokens': a['known_output_tokens'], 'public_evaluations': a['public_evaluations'],
            'research_wall_seconds': a['research_wall_seconds'],
            'host_evidence': a['host_evidence'], 'registry_evidence': a['registry_evidence'],
            'relay_evidence': relay, 'original_replay_evidence': original_evidence, 'score_evidence': evidence,
        })
    baselines = []
    for b in thinking['author_baselines']:
        item = {k:b[k] for k in ('task','method','evaluation_status','score','reward','passed')}
        item['formal_speedup'] = None
        if b.get('result_evidence'):
            item['evidence'] = b['result_evidence']
            d = checked(item['evidence'])['diagnostics']
            assert d['score'] == b['score'] and d['reward'] == b['reward']
            item['formal_speedup'] = d['repeats'][0].get('speedup')
        else:
            refusal = next(v for v in thinking['timing_refusals'] if v['kind']=='baseline' and v['identity']==b['method'])
            item['evidence'] = {'path':refusal['acceptance_path'],'sha256':refusal['acceptance_sha256']}
            assert checked(item['evidence'])['status'] == 'host_preflight_rejected'
        baselines.append(item)
    diagnostics = []
    for source in SOURCES[3:5]:
        samples = read(source)['diagnostics']['first']['repeats'][0]['samples']
        b = [r['worker']['execution_wall_seconds'] for r in samples['B']]
        c = [r['worker']['execution_wall_seconds'] for r in samples['C']]
        assert len(b) == len(c) == 3 and all(r['passed']==r['total']==12 for r in samples['C'])
        diagnostics.append({'source':source,'formal_timing_accepted':False,'formal_score':None,
            'baseline_seconds':b,'candidate_seconds':c,'baseline_median_seconds':statistics.median(b),
            'candidate_median_seconds':statistics.median(c),'raw_median_ratio_diagnostic_only':statistics.median(b)/statistics.median(c),
            'unique_cases':12,'candidate_replays':3,'passed_per_replay':[r['passed'] for r in samples['C']],
            'max_relative_residual':max(v['max_relative_residual'] for r in samples['C'] for v in r['cases']),
            'max_solution_error':max(v['max_solution_error'] for r in samples['C'] for v in r['cases'])})
    assert len(rows)==15 and sum(r['thinking_reward']==1 for r in rows)==14
    assert sum(r['output_tokens'] for r in rows)==thinking['retained_usage']['known_output_tokens']
    groups = {'main':[r for r in rows if r['repeat']==1],
              'appendix':[r for r in rows if r['repeat']>1], 'all':rows}
    for section,prefix in [('main','M'),('appendix','A')]:
        for index,r in enumerate(groups[section],1):
            r['report_section']=section
            r['report_id']=f'{prefix}{index:02d}'
    statistics_by_scope = {}
    for section,selected in groups.items():
        run_ids={r['run_id'] for r in selected}
        scoped_attempts=[a for a in thinking['attempt_records'] if a['run_id'] in run_ids]
        statistics_by_scope[section]={
            'run_ids':[r['run_id'] for r in selected], 'sessions':len(selected),
            'submissions':sum(r['thinking_has_submission'] for r in selected),
            'valid_final_scores':sum(r['thinking_final_score'] is not None for r in selected),
            'reward_one':sum(r['thinking_reward']==1 for r in selected),
            'timing_invalid':sum(r['thinking_final_score'] is None for r in selected),
            'first_final_direction':dict(Counter(r['first_final_direction'] for r in selected)),
            'retained_output_tokens':sum(r['output_tokens'] for r in selected),
            'public_evaluations':sum(r['public_evaluations'] for r in selected),
            'research_wall_seconds':sum(r['research_wall_seconds'] for r in selected),
            'attempt_count':len(scoped_attempts),
            'all_attempt_known_output_tokens':sum(a['known_output_tokens'] for a in scoped_attempts),
            'all_attempt_charged_output_tokens':sum(a['charged_output_tokens'] for a in scoped_attempts)}
    data={'scope':'Thinking/max only. Saved results, no new execution. G2 diagnostic times are not formal scores.',
          'presentation_rule':'Main: all tasks/groups r1. Appendix: Heat r2/r3. Post hoc presentation choice; no score-based selection or deleted observations.',
          'statistics_by_scope':statistics_by_scope,
          'display_order':'task Heat/ODE/Poisson, group G1/G2/G3, repeat r1/r2/r3',
          'repeat_definition':'Fresh research session, not a retry, difficulty or scoring replay.',
          'rows':rows,'author_baselines':baselines,'g2_diagnostics':diagnostics,
          'retained_thinking_usage':thinking['retained_usage'],'all_thinking_attempt_usage':thinking['all_attempt_usage'],
          'source_sha256':dict(sorted(sources.items()))}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'analysis.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    return data


def fill_tables(data):
    rows=data['rows']
    def row_tables(rows):
        table='| 序号 | 会话 | 最终分 | 数值通过 | reward | 正式加速比 | 结局 |\n|---:|---|---:|---|---:|---:|---|\n'
        detail='| 序号 | 会话 | first 分 | final 分 | 公开评估次数 | 输出 token | 研究用时（分钟） | 实际计划序号 |\n|---:|---|---:|---:|---:|---:|---:|---:|\n'
        for r in rows:
            note='成功' if r['thinking_reward']==1 else '计时无效；非零分'
            if r['task']=='poisson' and r['group']=='g1':note='成功（独立计时补测）'
            reward='—' if r['thinking_reward'] is None else str(r['thinking_reward'])
            speed='—' if r['formal_speedup'] is None else f"{r['formal_speedup']:.3f}×"
            table+=f"| {r['report_id']} | {r['label']} | {fmt(r['thinking_final_score'])} | 12 / 12 | {reward} | {speed} | {note} |\n"
            detail+=f"| {r['report_id']} | {r['label']} | {fmt(r['thinking_first_score'])} | {fmt(r['thinking_final_score'])} | {r['public_evaluations']} | {r['output_tokens']:,} | {r['research_wall_seconds']/60:.2f} | {r['execution_sequence']} |\n"
        return table,detail
    main_rows=[r for r in rows if r['report_section']=='main']
    appendix_rows=[r for r in rows if r['report_section']=='appendix']
    table,detail=row_tables(main_rows)
    appendix_table,appendix_detail=row_tables(appendix_rows)
    baseline='| 任务 | 作者方法及直观含义 | 分数 | 正确例 / 12 | reward | 正式加速比 |\n|---|---|---:|---:|---:|---:|\n'
    for b in data['author_baselines']:
        integer=lambda x:'—' if x is None else str(x)
        speed='—' if b['formal_speedup'] is None else f"{b['formal_speedup']:.3f}×"
        baseline+=f"| {NAMES[b['task']]} | {METHODS[b['method']]} | {fmt(b['score'])} | {integer(b['passed'])} | {integer(b['reward'])} | {speed} |\n"
    diag='| 测量 | 基线中位耗时（秒） | G2 中位耗时（秒） | 原始耗时比（仅诊断） | 正式分数 |\n|---|---:|---:|---:|---|\n'
    for label,d in zip(('首次测量','独立补测'),data['g2_diagnostics']):
        diag+=f"| {label} | {d['baseline_median_seconds']:.6f} | {d['candidate_median_seconds']:.6f} | {d['raw_median_ratio_diagnostic_only']:.3f}× | 未取得有效计时，留空 |\n"
    main=data['statistics_by_scope']['main']
    overview='| 指标 | 正文 r1 子集 |\n|---|---:|\n'
    for label,value in [('展示会话数',main['sessions']),('有提交',f"{main['submissions']} / {main['sessions']}（100%）"),('有效最终评分',f"{main['valid_final_scores']} / {main['sessions']}"),('成功，reward=1',f"{main['reward_one']} / {main['sessions']}（{main['reward_one']/main['sessions']*100:.1f}%）"),('有效但未成功',main['valid_final_scores']-main['reward_one']),('计时无效',main['timing_invalid'])]:
        overview+=f'| {label} | {value} |\n'
    usage='| 用量口径 | 正文 r1 子集 |\n|---|---:|\n'
    for label,value in [('9 个保留 attempt 的已知输出 token',f"{main['retained_output_tokens']:,}"),('含两个旧失败 attempt 的已知输出 token',f"{main['all_attempt_known_output_tokens']:,}"),('含失败 attempt 的 relay charged 额度',f"{main['all_attempt_charged_output_tokens']:,}"),('保留研究墙钟合计',f"{main['research_wall_seconds']/3600:.3f} 小时"),('公开评估次数合计',main['public_evaluations'])]:
        usage+=f'| {label} | {value} |\n'
    scope_table='| 统计范围 | 会话数 | 有提交 | 正式成功 | 计时无效 | 保留输出 token | 公开评估次数 | 研究用时（小时） |\n|---|---:|---:|---:|---:|---:|---:|---:|\n'
    for key,label in [('main','正文 r1'),('appendix','附录 Heat r2/r3'),('all','完整批次')]:
        st=data['statistics_by_scope'][key]
        scope_table+=f"| {label} | {st['sessions']} | {st['submissions']} | {st['reward_one']} | {st['timing_invalid']} | {st['retained_output_tokens']:,} | {st['public_evaluations']} | {st['research_wall_seconds']/3600:.3f} |\n"
    text=REPORT.read_text()
    for key,block in [('thinking-results',table),('session-details',detail),('g2-diagnostics',diag),('thinking-baselines',baseline),('main-overview',overview),('main-usage',usage),('appendix-results',appendix_table),('appendix-details',appendix_detail),('scope-statistics',scope_table)]:
        text,n=re.subn(rf'<!-- BEGIN {key} -->.*?<!-- END {key} -->',f'<!-- BEGIN {key} -->\n{block}<!-- END {key} -->',text,flags=re.S)
        assert n==1,key
    REPORT.write_text(text)
    (OUT/'ordered-results.md').write_text('# Thinking/max：正文 r1 与附录重复实验\n\n## 正文（M01–M09）\n\n'+overview+'\n'+table+'\n'+detail+'\n'+usage+'\n## 附录（A01–A06）\n\n'+appendix_table+'\n'+appendix_detail+'\n'+scope_table+'\n## 本批基线与 G2 诊断\n\n'+baseline+'\n'+diag)
    evidence='# Thinking/max 原始证据索引\n\n与正文 M01–M09、附录 A01–A06 一一对应。每个链接均指向保存的原始文件；完整 SHA256 见[机器可读索引](../results/thinking-r1-report-2026-10-25/analysis.json)。主报告与图表由同一索引生成，读者可沿评分 → 登记 → 候选源码 → 研究/relay 日志回查。独立补测另列，初次评分与拒绝记录保留。\n\n| 序号 | 会话（保留 attempt） | 研究与用量 | 登记与源码 | 当前独立评分 | 初次评分 |\n|---:|---|---|---|---|---|\n'
    for r in main_rows+appendix_rows:
        link=lambda key,label:f"[{label}](../{r[key]['path']})"
        registry=Path(r['registry_evidence']['path']).parent
        evidence+=f"| {r['report_id']} | {r['label']} / {r['attempt_id'].rsplit('-',1)[1]} | {link('host_evidence','host')} · {link('relay_evidence','relay')} | {link('registry_evidence','登记')} · [源码](../{registry}/snapshots/{r['final_id']}) | {link('score_evidence','评分')} | {link('original_replay_evidence','原记录')} |\n"
    evidence+='\n## 本批作者基线\n\n| 任务 | 方法 | 原始结果或准入拒绝 |\n|---|---|---|\n'
    for b in data['author_baselines']:evidence+=f"| {NAMES[b['task']]} | {b['method']} | [原记录](../{b['evidence']['path']}) |\n"
    evidence+='\n## 历史保全与核验\n\n两个失败 attempt 及三次执行器修复见[本批技术附录](thinking-control-2026-10-25.md)（该历史附录保留当时的跨批比较，当前主报告仅列 thinking）。G2 窗口拒绝见[计时附录](poisson-timing-recheck-2026-10-25.md)。上一版完整阅读报告已[独立归档](../archives/pre-thinking-only-20261025/README.md)，没有覆盖原始数据。\n\n运行 `python3 tools/verify_delivery.py` 检查交付哈希，再运行 `python3 tools/audit_thinking_report.py` 核对 15 行、图表来源、候选、用量、基线及主报告日志节选。两个命令均不调用模型或执行候选。\n'
    (ROOT/'docs/thinking-report-evidence-2026-10-25.md').write_text(evidence)


def figures(data,font):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    if font:
        font_manager.fontManager.addfont(font)
        plt.rcParams['font.family']=font_manager.FontProperties(fname=font).get_name()
    plt.rcParams.update({'font.size':11,'axes.unicode_minus':False,'svg.fonttype':'path','svg.hashsalt':'sciresearch-thinking-report'})
    FIG.mkdir(parents=True,exist_ok=True)
    blue,orange,gray='#176B87','#D66A28','#9AA5B1'
    def save(fig,name):
        fig.savefig(FIG/(name+'.png'),dpi=180,bbox_inches='tight',metadata={'Software':'SciResearch thinking report'})
        fig.savefig(FIG/(name+'.svg'),bbox_inches='tight',metadata={'Date':None})
        svg=FIG/(name+'.svg');svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,3.5),layout='constrained')
    for i,t in enumerate(TASKS):
        rs=[r for r in data['rows'] if r['task']==t and r['report_section']=='main'];n=len(rs);success=sum(r['thinking_reward']==1 for r in rs)
        axes[0].barh(NAMES[t],n,color=blue);axes[0].text(n-.2,i,f'{n}/{n}',ha='right',va='center',color='white',weight='bold')
        axes[1].barh(NAMES[t],success,color=blue,label='正式成功' if i==0 else None)
        axes[1].text(success/2,i,str(success),ha='center',va='center',color='white',weight='bold')
        if n-success:
            axes[1].barh(NAMES[t],n-success,left=success,color=gray,label='计时无效')
            axes[1].text(success+.5,i,'1',ha='center',va='center',color='white',weight='bold')
    axes[0].set_title('A. 正文 r1 有提交：9 / 9');axes[1].set_title('B. 正文 r1 正式成功 8，计时无效 1')
    axes[1].legend(loc='lower center',bbox_to_anchor=(.5,-.42),ncol=2)
    for ax in axes:ax.invert_yaxis();ax.set(xlim=(0,3.5),xlabel='正文 r1 会话数',xticks=range(4));ax.spines[['top','right']].set_visible(False)
    save(fig,'outcomes')
    fig,axes=plt.subplots(3,1,figsize=(11,10),layout='constrained')
    for ax,task in zip(axes,TASKS):
        rs=[r for r in data['rows'] if r['task']==task and r['report_section']=='main']
        for i,r in enumerate(rs):
            for shift,key,color in [(-.18,'thinking_first_score',blue),(.18,'thinking_final_score',orange)]:
                v=r[key]
                if v is None:ax.scatter([i+shift],[5],color=gray,marker='x',s=65)
                else:
                    ax.bar(i+shift,v,.33,color=color);ax.text(i+shift,v+1.8,f'{v:.1f}',ha='center',fontsize=8)
        ax.set_xticks(range(len(rs)),[f"{r['group'].upper()} r{r['repeat']}" for r in rs])
        ax.set(ylim=(0,112),title=f'{NAMES[task]}：r1 首次与最终候选',ylabel='任务内分数（0–100）')
        ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    fig.legend(handles=[Patch(color=blue,label='首次 first'),Patch(color=orange,label='最终 final'),Line2D([],[],marker='x',color=gray,linestyle='',label='×：无有效评分，非零分')],loc='outside lower center',ncol=3)
    save(fig,'first-final-scores')

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
    manifest={'analysis_sha256':hashlib.sha256((OUT/'analysis.json').read_bytes()).hexdigest(),
              'main_run_ids':data['statistics_by_scope']['main']['run_ids'],
              'figures':{'outcomes':'Main r1 rows only: submission and reward counts by task','first-final-scores':'Main r1 rows only: thinking_first_score/thinking_final_score in report order','g2-diagnostic':'g2_diagnostics: raw baseline_seconds/candidate_seconds, diagnostic only'},
              'files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FIG.iterdir()) if p.suffix in ('.png','.svg')}}
    (OUT/'figure-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


def html_report():
    from markdown_it import MarkdownIt
    md = MarkdownIt('commonmark', {'html': True}).enable('table')
    body = md.render(REPORT.read_text())
    assert '**' not in body, 'Unrendered Markdown emphasis in HTML'
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
    style += '@media print{footer{display:none}}'
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
    print(json.dumps({'ordered_rows': len(data['rows']), 'main_rows': 9, 'appendix_rows': 6, 'main_valid_scores': 8, 'valid_thinking_scores': 14, 'g2_formal_score': None,
                      'new_model_calls': 0, 'new_candidate_executions': 0, 'figures_generated': args.figures,
                      'html_generated': args.html}))
