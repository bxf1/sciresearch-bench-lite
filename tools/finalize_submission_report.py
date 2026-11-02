"""Editorial final edition: edition two is official; edition one and the rerun remain separate."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'archives/pre-final-pdf-20261031'
OUT = ROOT / 'results/final-report-2026-10-31'
FIG = ROOT / 'docs/figures/final-report-2026-10-31'
PDF = 'sciresearch-final-report-20261031-hq.pdf'

def read(path):
    return json.loads((ROOT / path).read_text())

def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()

def ref(path):
    path = Path(path)
    name = path.relative_to(ROOT).as_posix() if path.is_absolute() else path.as_posix()
    return {'path': name, 'sha256': sha(name)}

def verify_preservation():
    snapshot = read(ARCHIVE / 'manifest.json')
    for name, expected in snapshot['files'].items():
        assert sha(ARCHIVE / name) == expected
    for name, expected in snapshot['preserved_originals'].items():
        assert sha(name) == expected, name
    return snapshot

def figures(data, font):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family': font_manager.FontProperties(fname=font).get_name(),
                         'font.size': 10, 'axes.unicode_minus': False, 'svg.hashsalt': 'final-20261031'})
    FIG.mkdir(parents=True, exist_ok=True)
    files, panels = {}, {}
    configs = [('old-new-scores', 'old_final_score', 'final_score', '第一版（历史对照）', '第二版（正式结果）', '#8799A8', '#176B87'),
               ('first-final-scores', 'first_score', 'final_score', '首次候选', '最终候选', '#176B87', '#D16B24')]
    for name, left, right, left_label, right_label, color_a, color_b in configs:
        # Match the printed width so chart text retains its intended point size.
        fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.65), sharey=True)
        panels[name] = []
        for ax, task, label in zip(axes, ('heat', 'ode', 'poisson'), ('Heat', 'ODE', 'Poisson')):
            rows = [r for r in data['rows'] if r['task'] == task]
            assert [r['group'] for r in rows] == ['g1', 'g2', 'g3']
            x = list(range(3))
            a, b = [r[left] for r in rows], [r[right] for r in rows]
            bars_a = ax.bar([v - .18 for v in x], a, .35, color=color_a, label=left_label)
            bars_b = ax.bar([v + .18 for v in x], b, .35, color=color_b, label=right_label)
            for n, (bar_a, bar_b) in enumerate(zip(bars_a, bars_b)):
                # Close scores need staggered labels at the final printed size.
                for bar, lift in ((bar_a, 3), (bar_b, 15 if abs(a[n] - b[n]) < 12 else 3)):
                    ax.annotate(f'{bar.get_height():.1f}', (bar.get_x() + bar.get_width()/2, bar.get_height()),
                                xytext=(0, lift), textcoords='offset points', ha='center', fontsize=9)
            ax.set(title=label, xticks=x, xticklabels=['G1', 'G2', 'G3'], ylim=(0, 122), yticks=[0, 25, 50, 75, 100])
            ax.spines[['top', 'right']].set_visible(False)
            ax.spines[['left', 'bottom']].set_color('#A5B2BC')
            ax.grid(axis='y', color='#E6EBEF', linewidth=.7)
            ax.set_axisbelow(True)
            panels[name].append({'task': task, 'run_ids': [r['run_id'] for r in rows], left: a, right: b})
        axes[0].set_ylabel('分数')
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc='lower center', ncol=2, frameon=False, fontsize=10)
        fig.subplots_adjust(left=.09, right=.99, top=.88, bottom=.25, wspace=.20)
        for extension in ('png', 'svg'):
            path = FIG / (name + '.' + extension)
            fig.savefig(path, dpi=300, metadata={'Date': None} if extension == 'svg' else {'Software': 'SciResearch report renderer'})
            files[path.relative_to(ROOT).as_posix()] = sha(path)
        plt.close(fig)
    return {'analysis': ref('results/unified-r1-nine-2026-10-29/reviewed-results.json'),
            'purpose': 'Presentation-only landscape charts; underlying scores and original figures unchanged.',
            'display_label_decimals': 1, 'print_width_inches': 7.0,
            'pdf_rendering': 'vector_svg', 'panels': panels, 'files': files}

def improve_pdf_quality(html, report):
    """Embed subset TrueType fonts and vector charts, without editing report text."""
    from fontTools import subset
    from fontTools.ttLib import TTFont
    styles = []
    fonts = [
        ('ReportLatin', 400, '/System/Library/Fonts/Supplemental/Arial.ttf', -1),
        ('ReportLatin', 700, '/System/Library/Fonts/Supplemental/Arial Bold.ttf', -1),
        ('ReportCJK', 400, '/System/Library/Fonts/STHeiti Light.ttc', 1),
        ('ReportCJK', 700, '/System/Library/Fonts/STHeiti Medium.ttc', 1),
    ]
    for family, weight, source, number in fonts:
        font = TTFont(source, fontNumber=number)
        assert 'glyf' in font and not (font['OS/2'].fsType & 2)
        options = subset.Options()
        options.recalc_timestamp = False
        sub = subset.Subsetter(options=options)
        sub.populate(text=report + ''.join(chr(n) for n in range(32, 127)))
        sub.subset(font)
        stream = io.BytesIO()
        font.save(stream)
        payload = base64.b64encode(stream.getvalue()).decode()
        styles.append(f'@font-face{{font-family:{family};font-weight:{weight};src:url(data:font/ttf;base64,{payload}) format("truetype")}}')
    pngs = re.findall(r'!\[[^\]]*\]\((figures/[^)]+\.png)\)', report)
    assert len(pngs) == 3
    for name in pngs:
        png = ROOT / 'docs' / name
        svg = png.with_suffix('.svg')
        assert svg.exists() and '<image' not in svg.read_text()
        before = 'data:image/png;base64,' + base64.b64encode(png.read_bytes()).decode()
        after = 'data:image/svg+xml;base64,' + base64.b64encode(svg.read_bytes()).decode()
        assert before in html
        html = html.replace(before, after)
    styles.append('''
body{font-family:ReportLatin,ReportCJK,sans-serif;color:#172b3a;font-synthesis:none}
@media print{
  body{font-size:11pt;line-height:1.55}
  h1{font-size:23pt;line-height:1.4}
  h2{font-size:17pt}h3{font-size:13pt}
  p{margin:11px 0;orphans:3;widows:3}
  table{font-size:9.5pt;line-height:1.5;margin:12px 0}
  th,td{padding:5px 6px;overflow-wrap:anywhere}
  th{font-weight:700}
  img{width:100%;margin:8px auto}
  code,pre{font-family:"Courier New",ReportCJK,monospace}
  code{font-size:.94em}pre{font-size:9.5pt;line-height:1.55}
  .figure-note{font-size:10pt;line-height:1.5}
}
''')
    html = html.replace('<p>图中', '<p class="figure-note">图中')
    html = html.replace('<th>优先方向</th>', '<th style="width:12%">优先方向</th>')
    html = html.replace('<p>正常无提交和科学失败', '<p class="keep-together">正常无提交和科学失败')
    html = html.replace('<h1>SciResearch-Bench-Lite：', '<h1>SciResearch-Bench-Lite<br>')
    return html.replace('</style>', ''.join(styles) + '</style>')

def finalize_text():
    text = (ARCHIVE / 'docs/submission-report-2026-10-24.md').read_text()
    text = re.sub(r'^\*\*课程作业最终报告.*?<br>$', '**课程作业最终报告 · 第二版九组 r1 为正式结果 · 2026 年 10 月 31 日定稿**<br>\n实验记录日期：2026 年 10 月 29 日；本次仅整理报告，未新增模型研究或候选重放。<br>', text, count=1, flags=re.M)
    text = text.replace('sciresearch-unified-r1-ode-rerun-report-20261029.pdf', PDF)
    summary = '''## 摘要与阅读说明

本报告以**第二版统一执行器的九组 r1 作为正式主结果**：Heat、ODE、Poisson 各 G1/G2/G3 一组，共 9 个独立研究会话，**8/9 成功（88.9%）**。Heat 三组与 Poisson 三组全部成功；ODE G2/G3 成功，G1 因预算截止时未登记候选而记 0 分。主实验共 11 个 attempt，包含两个关联基础设施重试。

正式九组使用相同的修复后执行器、thinking/max 和 **16,384 单请求输出上限**，保留正常上下文压缩；每会话仍为 200,000 输出 token、30 分钟、20 次公开评估。九组研究全部关闭后才开始隐藏评分，执行器与原生 Pi 源码一致性均经哈希核验。

**第一版九组 r1 仅作历史对照**，其有效成绩与 9/9 成功结局保留，不替代第二版任何一组。第一版单请求上限为 4,096，执行过程中发生过修复；两版差异同时包含执行器、请求上限和独立会话波动，不能据此分离因果效应。旧 r2/r3 继续[归档](../archives/pre-heat-unified-20261029/README.md)，不进入本报告的正式统计。

**ODE G1 的后续补跑单列于第 13 节**：这是主结果已知后追加的 1 个会话，同样未提交、记 0 分。其结果和 26,155 输出 token、约 30.03 分钟开销单独报告，不并入正式九组成功率、用量或图表。

分数保留三位小数；`0` 表示按规则得到零分，`—` 表示不适用或没有有效结果。`reward=1` 表示满足全部成功条件；研究超时但已经登记有效候选的会话仍可成功。完整数据见[正式九组结果](../results/unified-r1-nine-2026-10-29/reviewed-results.json)和[证据索引](unified-r1-evidence-2026-10-29.md)。

'''
    text = text[:text.index('## 摘要与阅读说明')] + summary + text[text.index('## 1. 背景与研究目标'):]
    text = text.replace('### 4.2 原九组主实验只运行 r1', '### 4.2 版本角色与统计范围')
    marker = '### 4.3 展示、执行与评分顺序'
    scope = '''| 记录 | 本报告用途 | 研究会话数 | 成功数 | 展示位置 |
|---|---|---:|---:|---|
| 第二版统一执行器 r1 | 正式主结果 | 9 | 8 | 第 7.1、7.3、7.4 节 |
| 第一版 r1 | 历史对照 | 9 | 9 | 第 7.2 节逐组对照 |
| ODE G1 后续补跑 | 事后追加，单独报告 | 1 | 0 | 第 13 节 |

三类记录独立统计。第一版的有效计时补测只重放封存候选，不增加研究会话数；第二版的两个关联基础设施重试计入成本，不增加正式九组分母。ODE G1 的后续科学补跑单独计为 1 个会话。

'''
    text = text.replace(marker, scope + marker, 1)
    replacements = {
        '原九组主实验': '第二版正式九组',
        '原九组仍为': '第二版正式九组仍为',
        '原九组中的 ODE G1 r1': '第二版主实验 ODE G1 r1',
        '原九组一致': '第二版正式九组一致',
        '原九组的研究关闭屏障': '正式九组的研究关闭屏障',
        '原九组首次全部成功': '正式九组首次全部成功',
        '原批次与补跑': '正式九组与补跑',
        '原九组结果': '正式九组结果',
        '随后用户指定的单组事后补跑': '后续单组事后补跑',
        '用户后来指定的独立补跑': '后续独立补跑',
        '第 13 节是用户另行要求的新科学会话': '第 13 节单列事后追加的新科学会话',
        '## 7. 统一执行器的九组 r1 结果': '## 7. 正式实验结果：第二版九组 r1',
        '### 7.1 原九组结果': '### 7.1 正式主结果（8/9 成功）',
        '### 7.2 与历史 r1 逐组对照': '### 7.2 第一版历史对照与第二版正式结果',
        '| 旧 r1 最终分 | 新 r1 最终分 | 分差 | 旧保留输出 token | 新保留输出 token |': '| 第一版分数 | 第二版分数 | 分差 | 第一版输出 token | 第二版输出 token |',
        '### 7.3 会话内迭代与资源': '### 7.3 正式九组的会话内迭代与资源',
        '### 9.1 原九组观察': '### 9.1 正式结果的解释',
        '## 12. 九组主实验结论': '## 12. 正式主实验结论',
        '## 13. ODE G1 r1 单组补跑（2026-10-29）': '## 13. ODE G1 r1 单组补跑（独立报告）',
        '用户在原九组结果确认后，指定重新运行 ODE G1 r1。': '在第二版主实验关闭并获知 G1 未提交后，另行开展一次 ODE G1 r1 独立补跑。',
        '本次是失败结果已知后的事后补跑，不是基础设施重试，也不替换原主实验的分母。': '该补跑属于失败结果已知后的事后追加科学会话，独立报告结果与开销，不替换正式主实验分母。',
        '旧 r1 仅用于逐组对照': '第一版 r1 仅用于逐组对照',
        '上一版本已[按文件哈希独立暂存]': '第一版已[按文件哈希独立暂存]',
        '本次材料在当前本地工作区中核验；下列命令不调用模型或 Docker。GitHub 上的已发布版本仍为历史版本，尚不包含此次九组重测：': '本次定稿保存在本地工作区。下列命令只重建报告或核验已保存证据，不调用模型或执行候选：',
        '本次九组重测及报告尚未推送或上传。': '本次定稿未执行推送或上传操作。',
        '用户已允许临时暂停干扰日志进程': '已获准临时暂停干扰日志进程',
        '数据库按用户授权临时停止': '数据库按授权临时停止',
    }
    # Apply the longer, more specific phrases before shorter role labels.
    for before, after in sorted(replacements.items(), key=lambda item: -len(item[0])):
        text = text.replace(before, after)
    interpretation = '''三条任务表现不同。Heat 三组全部成功，相对第一版下降 0.478-1.599 分；研究过程改善没有转化为更高的最终数值分。ODE G2/G3 仍维持约 99.3 分，G1 的损失来自未交付候选，不能解释为已提交求解器的数学结果全部错误。Poisson G2/G3 的正式加速比分别由 2.554×、2.505× 提高至 3.868×、4.280×，数值正确性仍全部通过；G1 则由 4.145× 小幅降至 4.016×。

研究结束状态与科学成功应分别判断：ODE G2 和 Poisson G2 达到研究时间上限，但已经登记有效候选，因此最终 reward 仍为 1；ODE G1 截止时没有候选，按规则记 0 分。

成本也不能只看保留 attempt。正式九组已知输出从第一版的 587,172 降至 509,736 token，减少约 13.2%；计入各自基础设施失败后，从 616,777 降至 595,668，仅减少约 3.4%。保留研究时间约从 169.62 增至 172.74 分钟，且第二版少一个成功会话，不能仅凭输出减少宣称整体效率提高。第 13 节补跑的开销另计。

'''
    text = text.replace('**ODE G1 r1 未登记最终候选**', interpretation + '**ODE G1 r1 未登记最终候选**', 1)
    text = text.replace('figures/unified-r1-nine-2026-10-29/old-new-scores.png', 'figures/final-report-2026-10-31/old-new-scores.png')
    text = text.replace('figures/unified-r1-nine-2026-10-29/first-final-scores.png', 'figures/final-report-2026-10-31/first-final-scores.png')
    text = text.replace('![图2：历史 r1 与本次统一执行器 r1 的最终分数]', '![图2：第一版历史对照与第二版正式结果]')
    text = text.replace('![图3：本次九组 r1 首次与最终候选]', '![图3：第二版正式九组首次与最终候选]')
    text = text.replace('历史 Poisson G1、G2 采用', '图中数值标签保留一位小数，精确分数见上表；灰色为第一版对照，蓝色为第二版正式结果。\n\n第一版 Poisson G1、G2 采用', 1)
    text = text.replace('九个保留 attempt 共输出', '图中仅含第二版正式九组，数值标签保留一位小数；首次与最终候选属于同一研究会话，ODE G1 两列均为未提交零分。\n\n九个保留 attempt 共输出', 1)
    start = text.index('Heat G2 r1 第 44 个请求为原生压缩：')
    end = text.index('### 7.4 Poisson 正式计时', start)
    text = text[:start] + '压缩与传输请求的逐项记录见第 9.2 节，均保留在原始日志中。\n\n' + text[end:]
    compaction = '''正式九组保留 attempt 的 4 次原生压缩请求如下，单次压缩上限均为 8,192；压缩结束后研究请求上限仍为 16,384。

| 会话 / 请求 | 结局 | 已知输出 token | 耗时（秒） | 后续状态 |
|---|---|---:|---:|---|
| Heat G2 / #44 | success | 4,389 | 29.39 | 无新请求 |
| Heat G3 / #36 | success | 1,450 | 11.77 | 无新请求 |
| Poisson G2 / #56 | upstream_transport_error | 未知 | 120.02 | 随后重试原生压缩 |
| Poisson G2 / #57 | success | 3,933 | 23.29 | 恢复研究请求，上限 16,384 |

九个保留 attempt 内另按请求结局累计 2 次失败请求；客户端中断、可恢复的传输错误与整个 attempt 的基础设施失败分别统计。未完整返回请求的保守扣减额度及原记录均保留。

'''
    text = text.replace('本次基础设施失败 attempt 保留', compaction + '本次基础设施失败 attempt 保留', 1)
    for attempt, label in (
        ('research-a1eac24f70df21fd-heat-g2-r1-a001', 'Heat G2 a001'),
        ('research-fcc3d4b300a336f8-ode-g1-r1-a001', 'ODE G1 a001'),
    ):
        batch = '-'.join(attempt.split('-')[:2])
        evidence = f'../research-runs/{batch}/host-attempts/{attempt}.json'
        assert (ROOT / 'docs' / evidence).is_file()
        text = text.replace(f'- `{attempt}`：终止原因', f'- [{label}]({evidence})：')
    text = text.replace('。原记录保留，同一冻结配置关联重试。', '。')
    # This caveat is already stated in the scope and conclusion; avoid a stranded
    # one-line paragraph between the future-work table and delivery chapter.
    text = text.replace('这些改进属于后续新版本，不会追溯修改本次冻结参数、旧失败或隐藏分数。\n\n', '')
    text = text.replace('python3 tools/build_ode_g1_rerun_report.py', 'python3 tools/finalize_submission_report.py --html')
    text = text.replace('python3 tools/audit_ode_g1_rerun_report.py\n', 'python3 tools/audit_ode_g1_rerun_report.py\npython3 tools/audit_final_submission_report.py\n')
    text = text.replace('<!-- BEGIN thinking-baselines -->', '### 6.1 作者基线独立评分\n\n<!-- BEGIN thinking-baselines -->')
    text = text.replace('| 指标 | 第二版主实验 ODE G1 r1 | 本次单组补跑 |', '### 13.1 补跑结果与原因\n\n| 指标 | 第二版主实验 ODE G1 r1 | 本次单组补跑 |')
    text = text.replace('配置核验确认：共享执行器', '### 13.2 执行配置与证据\n\n配置核验确认：共享执行器')
    assert len(re.findall(r'\| M\d\d \|', text)) == 9
    assert '用户' not in text[text.index('## 13.'):]
    return text.rstrip() + '\n'

def main(args):
    snapshot = verify_preservation()
    official = read('results/unified-r1-nine-2026-10-29/reviewed-results.json')
    rerun = read('results/ode-g1-r1-rerun-2026-10-29/reviewed-results.json')
    assert official['new_sessions'] == 9 and official['new_reward_one'] == 8
    assert rerun['scientific_sessions'] == 1 and rerun['reward'] == 0
    OUT.mkdir(parents=True, exist_ok=True)
    if args.figures:
        manifest = figures(official, args.font)
        (OUT / 'figure-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    assert (OUT / 'figure-manifest.json').exists(), 'Generate figures once with --figures'
    report = finalize_text()
    (ROOT / 'docs/submission-report-2026-10-24.md').write_text(report)
    readme = (ARCHIVE / 'README.md').read_text()
    readme = readme.replace('sciresearch-unified-r1-ode-rerun-report-20261029.pdf', PDF)
    readme = readme.replace('最终报告 PDF（2026-10-29，九组 r1 统一重测及 ODE G1 单组补跑）', '最终报告 PDF（2026-10-31 清晰版，第二版正式结果）')
    readme = re.sub(r'\*\*ODE G1 r1 后续单组补跑：.*?\n', '**结果口径：第二版九组 r1 为正式主结果，8/9 成功；第一版仅作历史对照；ODE G1 后续补跑单列，0 分，不进入正式九组分母。** [定稿依据与证据](results/final-report-2026-10-31/index.json)。\n', readme)
    readme = readme.replace('## 九组 r1 重测结果', '## 正式结果：第二版九组 r1')
    (ROOT / 'README.md').write_text(readme.rstrip() + '\n')
    reproduction = (ARCHIVE / 'docs/reproduction.md').read_text()
    reproduction += f'''
## 最终定稿：第二版为正式结果（2026-10-31）

当前正式 PDF 为 `output/pdf/{PDF}`。第二版九组结果、第一版对照与 ODE G1 单组补跑分别统计；本次定稿只调整角色说明、图表排布与文字，没有新增科学实验。

清晰版嵌入 TrueType 字体并使用 SVG 矢量图，正文 11pt、表格 9.5pt。之前的 16 页 PDF 及对应排版源码保存在 `archives/pre-pdf-quality-20261031/`，科学数据和统计口径不变。

```bash
.report-venv/bin/python tools/finalize_submission_report.py --figures --html --font /System/Library/Fonts/Hiragino\\ Sans\\ GB.ttc
REPORT_PDF_NAME={PDF} node tools/render_final_report.cjs
python3 tools/audit_final_submission_report.py
python3 tools/build_delivery_manifest.py
python3 tools/verify_delivery.py
```

此前各节为对应历史版本的重建方法。最终定稿请使用本节入口；第一版、第二版初稿和含补跑的旧 PDF 均按原哈希保留。定稿前正文与脚本保存在[归档清单](../archives/pre-final-pdf-20261031/manifest.json)。科学结果 JSON 与原三张图不改写；两张新的横排图只改变展示方式。
'''
    (ROOT / 'docs/reproduction.md').write_text(reproduction.rstrip() + '\n')
    index = {'edition': 'final-20261031', 'editorial_date': '2026-10-31', 'experiment_date': '2026-10-29',
             'official': {'label': '第二版正式九组', 'sessions': 9, 'successes': 8, 'source': ref('results/unified-r1-nine-2026-10-29/reviewed-results.json')},
             'comparison': {'label': '第一版历史对照，仅 r1', 'sessions': 9, 'successes': 9, 'source': ref('results/thinking-r1-report-2026-10-29/analysis.json')},
             'supplement': {'label': 'ODE G1 事后独立补跑', 'sessions': 1, 'successes': 0, 'pooled_into_official': False, 'source': ref('results/ode-g1-r1-rerun-2026-10-29/reviewed-results.json')},
             'archive': ref(ARCHIVE / 'manifest.json'), 'preserved_originals': snapshot['preserved_originals'],
             'figure_manifest': ref(OUT / 'figure-manifest.json'), 'pdf_path': 'output/pdf/' + PDF,
             'pdf_quality': {'charts': 'vector_svg', 'fonts': 'embedded_subset_truetype', 'body_pt': 11, 'table_pt': 9.5,
                             'previous_layout': ref('archives/pre-pdf-quality-20261031/manifest.json')},
             'new_model_calls': 0, 'new_candidate_executions': 0}
    (OUT / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n')
    if args.html:
        from build_final_report import html_report
        html_report(local_evidence=True)
        path = ROOT / 'docs/submission-report-2026-10-24.html'
        html = path.read_text()
        for title in ('6.1 作者基线独立评分', '7.2 第一版历史对照与第二版正式结果', '7.3 正式九组的会话内迭代与资源', '7.4 Poisson 正式计时', '13.2 执行配置与证据'):
            html = html.replace('<h3>' + title + '</h3>', '<h3 class="result-page">' + title + '</h3>')
        html = html.replace('<p>实际环境为 M4 MacBook Air', '<p class="keep-together">实际环境为 M4 MacBook Air')
        css = '@media print{h2{margin-top:8mm}h3{margin-top:5mm}h2#section-8,h2#section-14,h3.result-page{break-before:page;margin-top:0}p:has(img){break-after:auto}.keep-together,li{break-inside:avoid}}'
        html = html.replace('</style>', css + '</style>')
        html = improve_pdf_quality(html, report)
        path.write_text(html)
    verify_preservation()
    print(json.dumps({'status': 'finalized', 'official_sessions': 9, 'official_successes': 8,
                      'comparison_sessions': 9, 'separate_rerun_sessions': 1, 'new_model_calls': 0, 'new_candidate_executions': 0}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', action='store_true')
    parser.add_argument('--figures', action='store_true')
    parser.add_argument('--font', default='/System/Library/Fonts/Hiragino Sans GB.ttc')
    main(parser.parse_args())
