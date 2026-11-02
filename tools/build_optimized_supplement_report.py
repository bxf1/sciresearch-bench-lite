"""Build a compact, selectable-text PDF source for the two requested supplements."""
import base64
import hashlib
import io
import json
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/optimized-r1-supplement-20261101'
DOC = ROOT / 'docs/optimized-r1-supplement-20261101'


def fmt(value, digits=3):
    return '未取得有效值' if value is None else f'{value:.{digits}f}'


def sci(value):
    return '未测' if value is None else f'{value:.2e}'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '|' + '|'.join(['---'] * len(headers)) + '|'] +
                     ['| ' + ' | '.join(str(x).replace('|', '/') for x in row) + ' |' for row in rows])


def passed(n):
    return f"{n['passed_all_observed_replays']} / {n['expected_cases']}" if n['replays_observed'] else '未交付 / 未测'


def main():
    a = json.loads((OUT / 'analysis.json').read_text())
    assert a['status'] == 'passed'
    notes = json.loads((OUT / 'method-notes.json').read_text())
    for evidence in a['source_evidence'] + notes['evidence']:
        assert hashlib.sha256((ROOT / evidence['path']).read_bytes()).hexdigest() == evidence['sha256']
    o, p = a['ode'], a['poisson']
    t, req = o['timeline'], o['requests']
    success_ode = o['reward'] == 1
    success_poisson = p['status'] == 'valid' and p['reward'] == 1
    outcome_ode = '交付成功，主测试通过' if success_ode else ('未交付合法候选，按规则计 0 分' if not o['candidates'] else '已交付，未达到主任务通过要求')
    outcome_p = '计时有效，达到效率门槛' if success_poisson else '未获得有效正式计时' if p['score'] is None else '计时有效，但未达到效率门槛'
    page1 = f'''# 九组 r1 实验：两项补测

SciResearch-Bench-Lite · 2026-11-01 · 独立补充报告

## 1. 补测结论

本次按用户“有两组未成功，去补测一下”的要求，对优化批次中 ODE G1 的未交付和 Poisson G2 的计时无效分别补测。结果如下。

{table(['补测对象', '原批次状态', '本次结果', '本次分数'], [
    ['ODE G1 r1', '未提交候选，0 分', outcome_ode, fmt(o['final_score'])],
    ['Poisson G2 r1', '数值通过，正式计时无效', outcome_p, fmt(p['score'])]])}

**ODE G1 是一次新的独立研究；Poisson G2 仅重放原封存候选。** 本次新增科学会话为 1 个。原九组的结果、分母和 PDF 均保留，补测单独呈现。

## 2. 固定条件与边界

ODE G1 沿用原模型路由、详细方法指导、工具、公开开发集和资源限制：30 分钟、20 次公开评估、20 万输出 token。单次响应上限为 16,384 token，正常上下文压缩保留。全新工作区中未注入旧解法、私有反馈或旧失败诊断。

Poisson G2 使用原 candidate-001，源码哈希未变。按照 BCCBBC 顺序重测，三次基线与候选的时间中位数相除计算加速比；时间包含启动、导入、I/O 和求解。最多 12 个准入窗口、3 次实际测量，采用首次有效结果。

研究容器保持 4 vCPU / 4 GiB，执行容器保持 1 vCPU / 4 GiB。ODE 研究关闭、候选封存后才开始主测试和诊断。Poisson 计时期间停止获授权的 PostgreSQL，结束后已恢复健康状态。

**解释范围：** 本次是事后补测，数据沿用冻结批次。它回答这两个具体问题能否补足结果，不能将原九组改称“首次全部成功”，也不能证明 G1/G2/G3 的总体优劣。
'''
    first_time = fmt(t['first_valid_registration_seconds'] / 60, 2) if t['first_valid_registration_seconds'] is not None else '未登记'
    page2 = f'''## 3. ODE G1：交付与探索

本次研究用时 {o['research_seconds']/60:.2f} 分钟，宿主 attempt 总用时 {o['attempt_wall_seconds']/60:.2f} 分钟。结果为：{outcome_ode}。

{table(['指标', '本次观测'], [
    ['首次合法候选时间（分钟）', first_time],
    ['公开评估请求 / 独立源码版本', f"{t['accepted_public_evaluations']} / {t['unique_registered_source_hashes']}"],
    ['可观察 shell 命令 / 非 bench 命令', f"{t['observed_shell_commands']} / {t['observed_shell_commands_other_than_bench']}"],
    ['首次 / 最终候选分数', f"{fmt(o['first_score'])} / {fmt(o['final_score'])}"],
    ['已知 / 计费用量（输出 token）', f"{t['known_output_tokens']:,} / {t['charged_output_tokens']:,}"]])}

### 方法与探索路径

{notes['ode_method']}

{notes['ode_exploration']}

### 关键取舍与限制

{notes['ode_limitations']}

公开评估数只统计登记请求，独立版本数按源码哈希去重。Shell 命令是可观察活动，并不等于内部实验总数。方法分析依据源码和日志；不可观察的过程不作推断。
'''
    main_rows = []
    for key, label in [('0', '低难度'), ('1', '中难度'), ('2', '高难度')]:
        n = o['main_by_level'][key]
        main_rows.append([label, passed(n), sci(n['metrics']['E_roll']['max']), sci(n['metrics']['E_field']['max'])])
    diag_rows = []
    for key, label in [('coordinate_scale', '非等比坐标缩放'), ('coordinate_swap', '坐标交换'), ('stable_cubic', '新稳定三次系统')]:
        n = o['diagnostics'][key]
        diag_rows.append([label, passed(n), sci(n['metrics']['E_roll']['max']), sci(n['metrics']['E_field']['max'])])
    page3 = f'''## 4. ODE G1：主测试与独立诊断

主测试采用冻结的 12 例。首次、最终候选各重放三次；源码相同则复用并保留标记。每例必须在所有已观测重放中均通过，才计入下表的通过数。误差列取该组全部重放的最大值。

{table(['主测试难度', '通过 / 总数', '最大 E_roll', '最大 E_field'], main_rows)}

最终主分为 **{fmt(o['final_score'])}**，reward 为 **{o['reward']}**。无候选时不存在数值误差，应记录为未测，不能将误差填为零。

### 诊断集

仅测试最终候选，不新增研究、不用于选择候选，也不计入主分。每主题 4 例，检查坐标改变与动力学支撑结构变化后的适应性。

{table(['诊断主题', '通过 / 总数', '最大 E_roll', '最大 E_field'], diag_rows)}

{notes['ode_test_interpretation']}

### 输出上限与执行情况

本次实际观测的请求上限集合为 {req['effective_request_caps']}；最大响应输出 {req['largest_observed_output_tokens']:,} token，超过 4,096 token 的响应有 {req['requests_with_output_over_4096']} 次。原生压缩请求 {req['native_compaction_requests']} 次，1-token 请求 {req['one_token_requests']} 次。

请求失败 {req['failed_requests']} 次，其占用时间和计费用量均保留在成本记录中；它们不自动构成新增科学会话。预算提醒只在可交互边界生效。
'''
    times = p['times']
    time_rows = []
    if times['B'] and times['C']:
        for number, role, index in [(1, 'B', 0), (2, 'C', 0), (3, 'C', 1), (4, 'B', 1), (5, 'B', 2), (6, 'C', 2)]:
            time_rows.append([str(number), 'Jacobi 基线' if role == 'B' else '封存候选', fmt(times[role][index], 6)])
    time_table = table(['执行次序', '对象', '端到端时间（秒）'], time_rows) if time_rows else '本轮未进入有效测量，正式时间和加速比保持为空。'
    memory = p['resources']['memory_peak_bytes']['max']
    coverage = ('连续观测记录覆盖所采用的有效计时窗口，受干扰窗口均已排除。'
                if p['status'] == 'valid' else '本轮未形成有效的正式性能结果，保留全部拒绝记录；数值结果与计时状态分别解释。')
    page4 = f'''## 5. Poisson G2：正式计时补测

本轮共使用 {p['admission_windows']} 个准入窗口，进行 {p['measurement_attempts']} 次实际测量，采用的窗口为 {p['selected_window'] if p['selected_window'] is not None else '无'}。状态：{outcome_p}。

{time_table}

基线中位数 **{fmt(p['median_seconds']['B'], 6)} 秒**，候选中位数 **{fmt(p['median_seconds']['C'], 6)} 秒**；正式加速比 **{fmt(p['speedup'])} 倍**，正式主分 **{fmt(p['score'])}**。数值通过情况为 **{passed(p['numeric'])}**。

{notes['poisson_interpretation']}

宿主测得候选 CPU 时间中位数为 {fmt(p['resources']['cpu_seconds']['median'], 4)} 秒，峰值内存最大值为 {fmt(memory / 2**20, 2) if memory is not None else '未取得'} MiB。{coverage}

## 6. 可追溯性与报告口径

原交付的 {a['original_preservation']['files_verified']:,} 个文件哈希复核通过。本次补测保存协议、启动前校验拒绝、研究时间线、候选快照、逐例结果及宿主观测。启动前拒绝发生在模型调用之前，研究成本为零；没有隐藏或覆盖失败记录。

补测证据目录：`results/optimized-r1-supplement-20261101/`。其中 `analysis.json` 为核验汇总，`case-results.json` 为逐例结果，`exploration-timeline.json` 为 ODE 探索时间线，`delivery-manifest.json` 为补测交付索引。

{notes['conclusion']}
'''
    pages = [page1, page2, page3, page4]
    report = '\n\n<div class="page-break"></div>\n\n'.join(pages)
    DOC.with_suffix('.md').write_text(report)
    fonts = []
    for family, weight, path, number in [
        ('ReportLatin', 400, '/System/Library/Fonts/Supplemental/Arial.ttf', -1),
        ('ReportLatin', 700, '/System/Library/Fonts/Supplemental/Arial Bold.ttf', -1),
        ('ReportCJK', 400, '/System/Library/Fonts/STHeiti Light.ttc', 1),
        ('ReportCJK', 700, '/System/Library/Fonts/STHeiti Medium.ttc', 1)]:
        font = TTFont(path, fontNumber=number)
        assert 'glyf' in font and not (font['OS/2'].fsType & 2)
        options = subset.Options(); options.recalc_timestamp = False
        sub = subset.Subsetter(options=options); sub.populate(text=report + ''.join(chr(n) for n in range(32, 127)))
        sub.subset(font); stream = io.BytesIO(); font.save(stream)
        payload = base64.b64encode(stream.getvalue()).decode()
        fonts.append(f'@font-face{{font-family:{family};font-weight:{weight};src:url(data:font/ttf;base64,{payload}) format("truetype")}}')
    css = '''@page{size:A4;margin:17mm 17mm 18mm}*{box-sizing:border-box}
body{font-family:ReportLatin,ReportCJK,sans-serif;font-synthesis:none;color:#18313f;font-size:10.5pt;line-height:1.5;margin:0}
h1{font-size:23pt;line-height:1.3;margin:0 0 9mm;color:#154e65}h2{font-size:16pt;margin:0 0 4mm;padding-bottom:2mm;border-bottom:1px solid #bed0d8}
h2:not(:first-child){margin-top:6mm}h3{font-size:12pt;margin:4mm 0 2mm}p{margin:3mm 0;orphans:3;widows:3}
table{width:100%;border-collapse:collapse;font-size:9.5pt;line-height:1.45;margin:4mm 0}th,td{border:1px solid #cad9df;padding:5px 7px;text-align:left;vertical-align:top}
th{background:#eaf2f5}tr:nth-child(even){background:#f7f9fb}tr{break-inside:avoid}code{font-family:ReportLatin,ReportCJK,sans-serif;font-size:9pt;overflow-wrap:anywhere}
.page-break{break-before:page}strong{font-weight:700;color:#153f54}'''
    html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>两项补测报告</title><style>' + ''.join(fonts) + css + '</style></head><body>'
    html += MarkdownIt('commonmark', {'html': True}).enable('table').render(report) + '</body></html>'
    DOC.with_suffix('.html').write_text(html)
    print(json.dumps({'status': 'built', 'planned_pages': 4, 'html': str(DOC.with_suffix('.html'))}))


if __name__ == '__main__':
    main()
