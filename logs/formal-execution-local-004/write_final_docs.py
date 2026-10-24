"""Render local delivery documents from retained report data; no new scoring."""
import csv
import json
from pathlib import Path
import shutil
from runner.common import file_hash, read_json, write_json

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
REPORT=ROOT/'results/formal-study-003';S=read_json(REPORT/'summary.json');A=read_json(OUT/'final-audit-001.json')
PLAN=read_json(ROOT/'freezes/research-run-plan-formal-003.json')
def read_rows(name):
    with (REPORT/(name+'.csv')).open() as f:
        result=[]
        for row in csv.DictReader(f):
            parsed={}
            for key,val in row.items():
                try:parsed[key]=json.loads(val)
                except (ValueError,TypeError):parsed[key]=val
            result.append(parsed)
        return result
attempts=read_rows('attempts');latest={r['run_id']:r for r in attempts};good=[r for r in attempts if r['research_valid']]
def fmt(v,d=3):return '—' if v is None else f'{v:,.{d}f}'
def name(r):return f"{r['task']} {r['group'].upper()} r{r['repeat']}"
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|',*['| '+' | '.join(str(x) for x in row)+' |' for row in rows]])
run_table=table(['会话','first 分','final 分','final 通过数 / 12','reward','结果'],[
    [name(r),fmt(r['first_score']),fmt(r['final_score']),fmt(r['final_passed'],0),fmt(r['final_reward'],0),
     '计时无效，留空' if r['evaluation_status']!='valid' else '无有效提交' if r['first_id'] is None else '已重放']
    for r in (latest[x['run_id']] for x in PLAN['runs'])])
group_table=table(['任务','组别','有效评分 / 计划','final 中位数','范围','reward=1'],[
    [g['task'],g['group'].upper(),f"{g['score_n']}/{g['planned_sessions']}",fmt(g['score_median']),(f"{fmt(g['score_min'])}–{fmt(g['score_max'])}" if g['score_n'] else '—'),(sum(r['final_reward']==1 for r in good if r['task']==g['task'] and r['group']==g['group']) if g['score_n'] else '—')]
    for g in S['groups']])
pg=A['poisson_groups'];baseline_speed={x['owner']:x['speedup'] for x in pg if x['kind']=='author'}
baseline_table=table(['任务','方法','分数','通过数 / 12','reward','speedup'],[
    [b['task'],b['method']+('（固定参考）' if b['fixed_reference'] else ''),fmt(b['score']),b['passed'],b['reward'],fmt(baseline_speed.get(b['attempt_id']))]
    for b in S['baseline_methods']])
changed=[r for r in good if r['iteration_status'] in ('improved','degraded')]
change_table=table(['会话','first → final 分数','分数变化','通过数变化'],[[name(r),f"{fmt(r['first_score'])} → {fmt(r['final_score'])}",fmt(r['delta_score']),f"{r['first_passed']} → {r['final_passed']}"] for r in changed])
post_table=table(['会话','首次有效后秒数','新增公开评估','新增候选 CPU 秒','新增输出 token'],[[name(r),fmt(r['after_first_wall_seconds'],1),fmt(r['after_first_evaluations'],0),fmt(r['after_first_candidate_cpu_seconds']),fmt(r['after_first_output_tokens'],0)] for r in good if r['first_id'] is not None])
history=read_json(OUT/'version-cost-history-001.json')['versions']
history_table=table(['冻结版本','attempt','有效研究关闭','已知成功输出','charged'],[[x['version'],x['attempts'],x['valid_research'],f"{x['successful_output_tokens']:,}",f"{x['charged_output_tokens']:,}"] for x in history])
window_table=table(['操作','窗口结果','证据'],[[w['identity'].replace(PLAN['plan_id']+'-',''),w['status'],f"[记录](../{w['path']})"] for w in A['timing_windows']])
report=f'''# 第三版正式执行结果：保留一次无效计时

2026-10-23，Asia/Shanghai。本轮执行已收束：**15/15 次研究、11/11 种作者方法、全部 15 个 first/final 包装结果已执行；有效科学评分为 14/15、覆盖 8/9 格。** Poisson G2 在计时期间遇到后台 VPN CPU 峰值，性能结果无效，score/reward/speedup 保持 null。按用户要求不追加重测，因此不能宣称完整 15/15 有效科学验收通过。

[机器可读报告](../results/formal-study-003/summary.json)中的 `pending_run_ids` 仅包含 Poisson G2：它表示尚无有效科学评分，**并非该会话未执行**。所有规定操作均已尝试，没有未启动的剩余操作。完整核对见[交付审计](../logs/formal-execution-local-004/final-audit-001.json)。

## 协议与分母

采用 [formal-003 计划](../freezes/research-run-plan-formal-003.json)，plan ID `{PLAN['plan_id']}`，SHA256 `{A['plan_sha256']}`。DeepSeek-V4.1-Flash-1017 / `deepseek-flash`、temperature=0、top_p=1、thinking=disabled；每请求最多 4,096 输出 token，每独立会话累计最多 200,000 输出 token，研究 1,800 秒、20 次公开评估。原生压缩计入同一预算。R 为 4 CPU/4 GiB，W 为 1 CPU/4 GiB、禁 swap、数值线程 1；模型、提示、工具、数据、评分和源码均按第三版冻结执行。

15 次研究包括 heat 每组 3 次、ODE/Poisson 每组各 1 次。9 次留下 first/final，6 次无有效提交。总共保留 19 个研究 attempt，其中 4 个因宿主睡眠、HTTP 402、用量计数守卫或上游传输错误无效；不把它们加入科学分母。用户要求减少重试之后，新增关联研究重试为 0。

隐藏阶段在全体研究关闭后开始。93 个全新 W 批次及 1,116 次实例执行均有可核对记录：heat/ODE 共 51 次独立重放（作者 24、研究 27）；Poisson 共 7 个 BCCBBC 组、42 批次，其中 5 组有效、Poisson G2 的 2 组因宿主窗口无效保留。5 个 first/final 同源码会话显式复用结果，不增加独立重放。无提交结果没有伪造候选或执行批次。实例、重复重放、候选和作者方法均不增加独立研究样本数。

## 组别结果

G1 为详细方法指导，G2 为方法方向，G3 为共同契约但无额外方法指导。下表含正常无提交的零分；无效计时不补零。heat 每组 n=3 只支持探索性比较，ODE/Poisson 每组 n=1 只支持描述。S3 不与 S1/S2 跨任务平均。

{group_table}

heat 的中位数受未提交会话明显影响，不能据此断言某种指导稳定更优。ODE 三个会话均 12/12 通过，分数分别 96.551、98.793、99.068；仅各一次研究，不能作稳定排名。Poisson G1 的 final 为 **12/12 正确、2.513× speedup、reward=1**；G2 保留数值记录但无有效性能结论；G3 无提交为正常零结果。

## 每次研究的 first/final

`—` 表示缺失或无效，不等于零。无提交时没有 first 分，final 按协议为零。Poisson G2 两个检查点原始数值检查均在每次候选批次通过 12/12，但宿主窗口不合格，正式汇总的性能分、reward 和通过数均保守留空。

{run_table}

逐例误差、分档、通过情况和 first→final 差值见 [cases.csv](../results/formal-study-003/cases.csv)、[case-deltas.csv](../results/formal-study-003/case-deltas.csv)；30 个逻辑检查点见 [checkpoints.csv](../results/formal-study-003/checkpoints.csv)。无效 Poisson G2 的原始正确性记录保留在[其重放包装](../research-runs/{PLAN['plan_id']}/final-replays/{PLAN['plan_id']}-poisson-g2-r1-a001/result.json)，不以被拒绝的计时估计正式性能。

## 作者方法与固定参考

11 种方法均完成规定重放，弱方法的正常失败保留。固定参考是 heat `tikhonov`、ODE `fixed`、Poisson `lu`，并非事后挑选最佳方法。

{baseline_table}

heat 固定参考分为 93.271；ODE 固定参考分为 95.389；Poisson LU 为 2.249×、38.976 分。各研究与固定参考的逐会话、逐组及逐例差值见 [fixed-reference-runs.csv](../results/formal-study-003/fixed-reference-runs.csv)、[groups](../results/formal-study-003/fixed-reference-groups.csv)、[cases](../results/formal-study-003/fixed-reference-cases.csv)。Poisson G2 对照为 null；作者基线不扩充研究分母。

## 迭代与新增成本

8 次有候选且可比较的会话中，2 次提升、1 次退化、5 次源码不变。另 6 次无提交、1 次计时无效无法判断变化。不能把 first→final 对照解释为反馈的因果收益。

{change_table}

Poisson G1 的 speedup 从 2.163× 变为 2.513×。5 个同源码会话只复用同一结果，记为“未观察到迭代”；heat G2 r1 虽有后续候选，final 通过数从 12 降到 11，结果保留。

下表以首次有效候选完成时间为界，列出随后新增成本；跨越该时间边界的请求无法拆分 token，保留 null（表中 `—`），不估算补齐。

{post_table}

## 总成本与版本历史

第三版共 7,650 次已接受 API 请求，7,644 次成功、6 次失败请求的实际输出未知。15 次有效研究的已知成功输出为 **2,324,341 token**；包含 4 个无效 attempt 的已知成功输出为 **2,591,496 token**。代理 charged 为 **2,613,274**，差额 21,778 是保守失败额度，不是实测输出或金额。输入/cache 用量按字段保存在 [attempts.csv](../results/formal-study-003/attempts.csv)，不混作输出预算。所有金额为 null。

15 次有效研究墙钟合计 18,992.862 秒（5.276 小时）；全部 19 attempt 的研究墙钟合计 23,428.333 秒（6.508 小时，含睡眠干扰），不包含全部准备、等待账户处理与交付时间。公开评估可见的候选 CPU 合计 116.573 秒，24 个导出失败行没有 CPU 值，完整总额保持未知。隐藏 W 的 CPU 合计 285.577 秒，其中作者 49.783 秒、研究重放（含 T3 比较器）235.795 秒；计时无效批次的已发生资源消耗仍计入成本。所有单位均按原记录，不换算货币。

{history_table}

旧版因原生压缩修复与预算修订分别封存；不把不同冻结版本合并为同一科学比较。上表仅覆盖三版正式计划，排除 pilot、合成探测和当前 Codex 对话。[版本成本记录](../logs/formal-execution-local-004/version-cost-history-001.json)保留逐版计算口径。

## 无提交、接口问题与计时无效

6 次无有效提交：Poisson G3、heat G3 r2/r3、heat G1 r2/r3、heat G2 r3。原因不完全相同：有长段逐字重复工具调用，有仅递增文件名的同一计算，也有持续改变随机种子开展自建模拟但未转入提交。heat G1 r2 连续 515 次只改变文件名，结果文本相同；heat G1 r3 则使用 220 个不同种子产生不同模拟结果，不能混为相同计算。所有正常失败按预算关闭，未为表现不足加跑。

62 次公开评估中 23 次产物有效，24 次源码导出失败均只显示 `ReadError: empty file`。包含 8 次点路径、11 次绝对路径、4 次 `solve.py`、1 次 `out`。冻结路径守卫拒绝点路径段且要求目录，通用提示没有明确说明 `.` 不可用；宿主空 tar 错误掩盖了具体 exporter 错误。此接口局限影响提交，不能把无提交全归因于数学能力。研究期间未改提示、替模型提交或修改冻结实现。完整证据见[提交诊断](submission-diagnosis-2026-10-23.md)与[全矩阵导出审计](../logs/formal-execution-local-004/closed-source-export-audit-002.json)。

T3 使用新观察窗口，未复用旧校准时间。LU 第一次 30 秒前置检查遇到 VPN CPU 峰值，尚未读取隐藏成绩、未生成 LU attempt；保留拒绝窗口后，新准入通过，LU 仅测一次。Poisson G2 在实际测量中出现 VPN 进程约 6.406% 单核 CPU 的样本，超过既定 5% 门槛，两个检查点保守留空，不重测。没有改阈值、停止用户 VPN 或将无效速度升级为正式成绩。

{window_table}

## 验证、局限与交付

[正式报告生成](../logs/formal-execution-local-004/report-generation-001.stdout.txt)成功；[交付审计](../logs/formal-execution-local-004/final-audit-001.json)核对所有引用哈希、first/final 复用、三次重放、BCCBBC 顺序、93 个不同工作容器、资源限制和清理，当前运行容器为 0。冻结时的 [357 项测试](../logs/formal-freeze-local-003/unit-tests-final.txt)通过，随后可信源码未改动。两个交付审计草稿对记录字段的假设错误已留档并修正，仅修审计脚本，没有重跑实验或修改结果。

**完整有效科学验收未达成**：Poisson G2 的性能结论仍缺失；用户要求减少重试后，本轮以保留无效测量收束。小样本、三类合成任务、单一宿主与供应商别名映射均限制外推，不能声称跨科学领域能力或指导效果的因果结论。详细边界见[局限](limitations.md)。

本地证据包为 [evidence.tar.gz](../logs/formal-execution-delivery-local-005/evidence.tar.gz)，[成员清单](../logs/formal-execution-delivery-local-005/file-manifest.json)及[完整性与凭据扫描](../logs/formal-execution-delivery-local-005/integrity.json)单独保存。原始版本、失败 attempt、无效窗口、候选和逐例表全部保留。私有数值数组仍在本机 `authoring/data/v0.3-local`，由冻结哈希绑定；证据包不包含这些数组、宿主依赖或 Docker 镜像，不能单独解压即完整重跑。**本轮没有 GitHub 提交、推送或发布。**
'''
updates={}
updates['docs/formal-results-2026-10-23.md']=report
updates['docs/execution-status-2026-10-23.md']='''# 第三版执行已收束：15 次研究，1 项计时无效

2026-10-23（Asia/Shanghai）。15/15 次研究已有效关闭，9 次有 first/final、6 次无提交；共 19 个 attempt，4 个无效 attempt 保留。11/11 作者方法及全部 15 个研究 first/final 操作已执行。有效科学评分为 14/15、8/9 格；Poisson G2 的实际计时受后台 VPN CPU 峰值影响，score/reward/speedup 为 null，未重测。完整有效科学验收没有通过，不能报告为 15/15 全有效。

所有调度器已退出，当前运行容器为 0。**不要再启动研究或把正常失败重跑。** 用户最新减少重试指令之后，新增关联研究重试为 0；LU 的一次被拒绝前置窗口没有创建 baseline attempt，新的合格准入后只测量一次。

- [最终报告与逐会话结果](formal-results-2026-10-23.md)
- [机器可读报告](../results/formal-study-003/summary.json)
- [全部操作完成记录](../logs/formal-execution-local-004/hidden-phase-completion.json)
- [交付审计](../logs/formal-execution-local-004/final-audit-001.json)
- [提交原因诊断](submission-diagnosis-2026-10-23.md)
- [本地证据完整性](../logs/formal-execution-delivery-local-005/integrity.json)

当前计划为 `research-run-plan-formal-003.json` / `research-6615cd7900ba0750`。报告 `pending_run_ids` 中的 Poisson G2 是已执行但无有效评分，不是未开始任务。冻结模型、提示、数据、评分、预算与可信源码未在研究/隐藏阶段改动。本轮无新的研究或测量重试待执行，也未对外发布。

执行历史、旧恢复命令与阶段统计保留于[整理前快照](../logs/formal-execution-local-004/docs-before-final/docs/execution-status-2026-10-23.md)及各日志；这些命令不是当前待办。
'''
updates['docs/execution-handoff-2026-10-23.md']=f'''# SciResearch-Bench-Lite v0.3：执行收束与交付索引

2026-10-23（Asia/Shanghai）。原交接任务已执行并按用户“没研究出来的任务就正常关闭，无需过多重试”要求收束。**15 次研究全部关闭、11 种作者方法全部重放、15 个研究 first/final 操作全部执行。** 有效科学评分为 14/15、8/9 格；Poisson G2 因实际计时窗口不合格留空，完整 15/15 有效科学验收未达成，未追加重测。

## 当前状态

| 项目 | 结果 |
|---|---|
| 资源验收 | 原 15/15 通过；原 VM 身份保持，最终容器为 0 |
| T3 校准 | 原三组 216/216 检查通过；未复用旧时间窗口 |
| 冻结 | 第三版 `research-6615cd7900ba0750`，每会话 200,000 输出 token |
| 研究 | 15/15 有效关闭；9 有候选、6 无提交；另保留 4 个无效 attempt |
| 作者方法 | 11/11 完成，均有有效结果，科学零分保留 |
| 研究隐藏操作 | 15/15 已执行；14 有效、Poisson G2 计时无效 |
| 报告与归档 | [最终报告](formal-results-2026-10-23.md)、[审计](../logs/formal-execution-local-004/final-audit-001.json)、[本地归档](../logs/formal-execution-delivery-local-005/integrity.json) |
| 对外发布 | 本轮没有提交、推送或发布 |

## 读取入口与禁止重复执行

正式计划：[formal-003](../freezes/research-run-plan-formal-003.json)，SHA256 `{A['plan_sha256']}`。最终 ledger：[manifest](../research-runs/{PLAN['plan_id']}/manifest.json)，SHA256 `{A['manifest_sha256']}`。所有研究、隐藏和恢复控制器均已退出。不要重新运行启动或恢复脚本，不再增加研究 attempt；无提交和科学零分均保留。

[summary.json](../results/formal-study-003/summary.json)中的 `pending_run_ids` 只列出已测量但性能无效的 Poisson G2，不能误解为尚未执行。当前没有未启动的规定操作。按用户最新要求，本轮不再为其重测；如以后要开展新工作，应先明确新的授权和协议范围，不能改写原记录。

只读重建报告可使用新输出目录：

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study_report \\
  --project . --plan freezes/research-run-plan-formal-003.json \\
  --manifest research-runs/{PLAN['plan_id']}/manifest.json \\
  --output results/formal-study-review-new
```

不要 reset、clean、重新生成数据/计划、覆盖既有输出或把当前未提交工作切回旧版本。报告重建不调用模型或求解器，但必须保留原哈希引用。

## 证据边界

heat/ODE 的作者及不同候选各三次独立重放；同会话同源码显式复用。Poisson 每个不同方法/检查点一个 BCCBBC 组，合计 7 组，其中 G2 的 2 组性能无效。93 个 W 批次、1,116 次实例执行全部留档，不能作为 1,116 个独立研究样本。

T3 窗口保留一个 LU 前置检查拒绝（当时未读隐藏成绩、未创建 attempt），随后 LU 首次正式测量通过；Poisson G2 实际测量遇到 VPN CPU 峰值，留空且不重测。所有窗口与旧版本失败证据均保留。

[无提交诊断](submission-diagnosis-2026-10-23.md)区分反复相同计算、持续不同随机模拟、源码目录拒绝及 API/基础设施故障。冻结期间未修改提示或替模型完成提交。金额未知，失败占用不冒充实际 token，成本按版本分开。

[本地证据包](../logs/formal-execution-delivery-local-005/evidence.tar.gz)含源码、候选、结果、清单、逐例表与诊断；私有数值数组继续留在 `authoring/data/v0.3-local` 并由冻结哈希绑定，不包含在包中。宿主依赖、Docker 镜像和数据都仍是完整复现所需条件。原 8 个其他服务容器按已有授权保持停止，数据卷未删除。

原交接文字与历史执行步骤保留于[整理前快照](../logs/formal-execution-local-004/docs-before-final/docs/execution-handoff-2026-10-23.md)，版本修订见[原生压缩修复](compaction-freeze-2026-10-23.md)与[20 万预算冻结](budget-freeze-2026-10-23.md)。这些历史启动命令不是当前待办。
'''
# Preserve repository instructions and historical evidence while replacing stale current-status claims.
s=(ROOT/'README.md').read_text();start=s.index('三条合成科学计算任务：');s='# SciResearch-Bench-Lite v0.3\n\n'+'''2026-10-23 本轮执行已收束：**15/15 次研究关闭，11/11 作者方法及全部 15 个 first/final 操作完成。有效科学评分为 14/15、8/9 格**；Poisson G2 的计时窗口受后台 VPN 负载干扰，性能留空，按用户要求未重测。9 次研究有候选、6 次无有效提交；4 个无效 attempt 单独保留。完整有效科学验收尚未达成。\n\n[正式结果与成本](docs/formal-results-2026-10-23.md) · [机器可读报告](results/formal-study-003/summary.json) · [提交诊断](docs/submission-diagnosis-2026-10-23.md) · [交付审计](logs/formal-execution-local-004/final-audit-001.json) · [本地证据完整性](logs/formal-execution-delivery-local-005/integrity.json)\n\n采用[第三版 20 万输出预算冻结](docs/budget-freeze-2026-10-23.md)。全部调度器已退出，容器清理完成；不再重跑未提交任务。本轮没有 GitHub 提交、推送或发布。\n\n'''+s[start:]
a=s.index('**本机实现、校准');b=s.index('## 当前验收状态');s=s[:a]+'''## 正式执行前的实现与 pilot 证据\n\n下表中的生成、校准、隔离、pilot 与干净环境记录保留各自历史范围。90 例 GT QC、11 方法校准、真实模型接线和同宿主新依赖环境重放均已完成；它们不替代上方的正式 final-test 结果。历史发布以[既有发布记录](logs/publication-local-003/result.json)为限，不代表本轮内容已发布。\n\n'''+s[b:]
s=s.replace('当前工作源码348通过；此前新依赖环境归档源码328通过','第三版冻结源码357通过；历史新依赖环境归档源码328通过').replace('[当前Flash源码](logs/formal-freeze-local-001/model-switch/unit-tests.txt)','[第三版冻结源码](logs/formal-freeze-local-003/unit-tests-final.txt)')
s=s.replace('| 作者基线 | 11方法、132个方法×实例记录；保留弱基线失败 |','| 作者校准（历史） | 11方法、132个方法×实例记录；保留弱基线失败 |')
s=s.replace('[正式计划](freezes/research-run-plan-formal-001.json)','[当前正式计划](freezes/research-run-plan-formal-003.json)')
s=s.replace('| 三任务×三组研究 | **0个正式格**；最低9格，主计划15会话 | [未完成事项](#仍需完成) |','| 三任务×三组研究 | **15/15研究关闭、9/9研究格**；9有候选、6无提交，另4无效attempt | [最终结果](docs/formal-results-2026-10-23.md) |')
s=s.replace('| 隐藏重放与正式性能 | **未完成**；不把校准或pilot记成final | [局限](docs/limitations.md) |','| 隐藏重放与正式性能 | 全部操作已执行；**14/15有效评分、8/9有效科学格**，Poisson G2计时无效 | [最终报告](results/formal-study-003/summary.json) |')
a=s.index('已保存正式[15会话运行计划]');b=s.index('## 环境',a);s=s[:a]+'''本轮执行采用 [formal-003 计划](freezes/research-run-plan-formal-003.json)及三任务同号 freeze，已完成全部规定操作。原数据、镜像和可信源码不能重建或替换后冒充本次证据；运行/报告恢复入口见[收束交接](docs/execution-handoff-2026-10-23.md)。上述 draft、生成和校准命令仅供独立新工作使用，不是当前待办。\n\n'''+s[b:]
a=s.index('## 仍需完成');b=s.index('[调研对应关系]',a);s=s[:a]+'''## 执行范围与未达成项\n\n本轮规定操作已全部尝试并本地归档；Poisson G2 的性能测量无效，因此完整 15/15 有效科学验收未达成。按用户减少重试的要求，此项保留 null，不再自动测量。其他正常无提交与零分结果也不补跑。若以后继续实验或发布，需要明确新工作范围，不能覆盖本轮失败证据。\n\n三类受控合成任务、heat 每组 n=3、ODE/Poisson 每组 n=1、同一物理宿主与供应商模型别名均限制外推。首次→最终变化不证明反馈的因果效果，T3不与T1/T2平均。私有数值数组、运行镜像和宿主依赖仍需本机保留；证据包不是独立的完整运行环境。\n\n'''+s[b:]
s=s.replace('· [结果](docs/results.md)','· [正式结果](docs/formal-results-2026-10-23.md) · [历史结果](docs/results.md)');updates['README.md']=s
s=(ROOT/'docs/results.md').read_text();s=s.replace('# 本机实施与校准结果','# 本机实施与校准结果（历史记录）',1);s=s.replace('\n报告生成时间：','\n当前正式执行结果见[第三版最终报告](formal-results-2026-10-23.md)：15 次研究关闭、11 种作者方法及全部 first/final 操作完成，Poisson G2 计时无效且未重测；有效科学评分为 14/15。**下文保留正式执行前的历史状态，不是当前待办。**\n\n报告生成时间：',1);updates['docs/results.md']=s
s=(ROOT/'docs/limitations.md').read_text();a=s.index('\n\n');b=s.index('## 研究与因果解释');s=s[:a]+'''\n\n当前 [第三版正式执行](formal-results-2026-10-23.md)已收束：15 次研究、11 种作者方法、全部 first/final 操作已执行；有效科学评分为 14/15、8/9 格。Poisson G2 实际计时遇到后台 VPN CPU 峰值，性能留空且按用户要求不重测，完整有效科学验收未达成。6 次无有效提交、4 个无效研究 attempt 均保留。以下历史 pilot/校准的边界继续成立，但不再代表正式研究尚未开始。\n\n新增实测局限包括：原生工具调用长段重复；仅改变文件名掩盖相同计算；持续改变随机种子却不提交；源码目录约束与笼统的空 tar 反馈影响提交。62 次公开评估中 24 次导出失败，不能全部解释为数学能力不足。研究中没有据此改提示或替模型提交。详见[提交诊断](submission-diagnosis-2026-10-23.md)。\n\n'''+s[b:]
s=s.replace('可信代理已实测每请求4096、会话32768的输出额度和请求哈希门禁；','第一版可信代理曾实测每请求4096、会话32768的输出额度；第三版每会话累计输出上限为200000，并包含严格匹配的原生压缩请求和研究请求哈希门禁；')
s=s.replace('这些分支目前是合成测试证据。完整真实native pilot仅覆盖本机heat功能链路，正式三个任务的15会话没有执行。','这些分支原有合成测试证据。第三版的15次真实研究及全部隐藏操作现已执行；这不意味着所有异常恢复分支都由真实故障覆盖，也不抹除Poisson G2的无效性能窗口。')
s+='''\n\n## 本轮交付范围\n\n当前工作树包含冻结和执行所需的未提交修改；本轮没有新的 GitHub 提交、推送或发布。最终本地证据包与[交付审计](../logs/formal-execution-local-004/final-audit-001.json)保留失败、null成本、无效窗口及两个被修正的审计草稿。此前公开授权只适用于相应历史提交。私有数值数组未装入证据包，仍需本地原数据、固定镜像和依赖才能完整复现。\n''';updates['docs/limitations.md']=s
s=(ROOT/'docs/study.md').read_text();a=s.index('`runner.study` is');b=s.index('From `benchmark/`',a);s='# Formal study controller\n\n当前第三版执行已收束，见[正式结果](formal-results-2026-10-23.md)。15 次研究有效关闭、11 作者方法及全部 first/final 操作已执行；14 个有效科学结果，Poisson G2 计时无效留空，不重测。用户减少重试指令之后未新增关联研究重试。下文是控制器能力说明，不是重新启动实验的授权。\n\n'+s[a:b].replace('The 2026-10-23 [formal freeze](formal-freeze-2026-10-23.md) binds all 15 sessions to DeepSeek-V4.1-Flash-1017 and passes admission. No formal session has started.','The authorized [third freeze](budget-freeze-2026-10-23.md) binds the 15 sessions to DeepSeek-V4.1-Flash-1017 with a cumulative 200,000 output-token cap per session; all have closed.')+s[b:]
s=s.replace('A real formal matrix and final replay have not been executed or accepted.','The third frozen matrix and all required hidden operations have now executed. Full valid scientific acceptance was not achieved: one Poisson research performance window was invalid and retained without remeasurement.');updates['docs/study.md']=s
s=(ROOT/'docs/timing.md').read_text();s=s.replace('# T3计时实现与本机验证\n\n','# T3计时实现与本机验证\n\n2026-10-23 第三版 final-test 已执行：7 个 BCCBBC 组、42 个 W 批次，5 组性能有效；Poisson G2 的 first/final 两组因后台 VPN CPU 峰值而无效，性能留空且未重测。LU 另保留一次未开始测量的前置窗口拒绝，新合格准入后仅测一次。新窗口、哈希和逐组结果见[交付审计](../logs/formal-execution-local-004/final-audit-001.json)与[最终报告](formal-results-2026-10-23.md)。旧校准时间窗口没有复用。\n\n',1);s=s.replace('上述历史功能轮次没有模型调用或final-test成绩。','上述历史功能/校准轮次没有模型调用或final-test成绩；不包括本页顶部的新正式重放。');updates['docs/timing.md']=s
s=(ROOT/'docs/budget-freeze-2026-10-23.md').read_text();a=s.index('\n\n');b=s.index('\n\n用户在',a);s=s[:a]+'''\n\n本版已完成 15/15 研究关闭、11/11 作者方法和全部 first/final 操作。9 次研究有候选，6 次无提交；有效科学评分为 14/15，Poisson G2 计时无效留空、不重测。所有调度器已退出，本轮按用户要求收束。见[最终结果](formal-results-2026-10-23.md)与[当前状态](execution-status-2026-10-23.md)。'''+s[b:];s=s.replace('## 继续执行','## 历史执行入口（本轮已收束，不要重复启动）');updates['docs/budget-freeze-2026-10-23.md']=s
backup=OUT/'docs-before-final';backup.mkdir(exist_ok=False)
for name,content in updates.items():
    p=ROOT/name
    if p.exists():
        dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    p.write_text(content)
status={'status':A['status'],'all_planned_operations_attempted':True,'full_valid_scientific_acceptance':False,'valid_research_sessions':15,'research_attempts':19,'author_methods':11,'valid_scientific_sessions':14,'invalid_measurement_run_ids':A['invalid_measurement_run_ids'],'unattempted_operations':[],'pending_run_ids_interpretation':'Executed Poisson G2 lacks valid performance scoring; it is not an unstarted operation. Closed without retry under user direction.','audit':{'path':(OUT/'final-audit-001.json').relative_to(ROOT).as_posix(),'sha256':file_hash(OUT/'final-audit-001.json')},'publication':'local_only'}
write_json(REPORT/'execution-status.json',status)
print(json.dumps({'documents':list(updates),'execution_status':str(REPORT/'execution-status.json')}))
