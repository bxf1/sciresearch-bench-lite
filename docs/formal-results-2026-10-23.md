# 第三版正式执行结果：保留一次无效计时

2026-10-23，Asia/Shanghai。本轮执行已收束：**15/15 次研究、11/11 种作者方法、全部 15 个 first/final 包装结果已执行；有效科学评分为 14/15、覆盖 8/9 格。** Poisson G2 在计时期间遇到后台 VPN CPU 峰值，性能结果无效，score/reward/speedup 保持 null。按用户要求不追加重测，因此不能宣称完整 15/15 有效科学验收通过。

[机器可读报告](../results/formal-study-003/summary.json)中的 `pending_run_ids` 仅包含 Poisson G2：它表示尚无有效科学评分，**并非该会话未执行**。所有规定操作均已尝试，没有未启动的剩余操作。完整核对见[交付审计](../logs/formal-execution-local-004/final-audit-001.json)。

## 协议与分母

采用 [formal-003 计划](../freezes/research-run-plan-formal-003.json)，plan ID `research-6615cd7900ba0750`，SHA256 `47356b71b90acb1178dc86f94ec4f58041d933d00a67b4594cc0c697b568a033`。DeepSeek-V4.1-Flash-1017 / `deepseek-flash`、temperature=0、top_p=1、thinking=disabled；每请求最多 4,096 输出 token，每独立会话累计最多 200,000 输出 token，研究 1,800 秒、20 次公开评估。原生压缩计入同一预算。R 为 4 CPU/4 GiB，W 为 1 CPU/4 GiB、禁 swap、数值线程 1；模型、提示、工具、数据、评分和源码均按第三版冻结执行。

15 次研究包括 heat 每组 3 次、ODE/Poisson 每组各 1 次。9 次留下 first/final，6 次无有效提交。总共保留 19 个研究 attempt，其中 4 个因宿主睡眠、HTTP 402、用量计数守卫或上游传输错误无效；不把它们加入科学分母。用户要求减少重试之后，新增关联研究重试为 0。

隐藏阶段在全体研究关闭后开始。93 个全新 W 批次及 1,116 次实例执行均有可核对记录：heat/ODE 共 51 次独立重放（作者 24、研究 27）；Poisson 共 7 个 BCCBBC 组、42 批次，其中 5 组有效、Poisson G2 的 2 组因宿主窗口无效保留。5 个 first/final 同源码会话显式复用结果，不增加独立重放。无提交结果没有伪造候选或执行批次。实例、重复重放、候选和作者方法均不增加独立研究样本数。

## 组别结果

G1 为详细方法指导，G2 为方法方向，G3 为共同契约但无额外方法指导。下表含正常无提交的零分；无效计时不补零。heat 每组 n=3 只支持探索性比较，ODE/Poisson 每组 n=1 只支持描述。S3 不与 S1/S2 跨任务平均。

| 任务 | 组别 | 有效评分 / 计划 | final 中位数 | 范围 | reward=1 |
|---|---|---|---|---|---|
| heat | G1 | 3/3 | 0.000 | 0.000–93.631 | 1 |
| heat | G2 | 3/3 | 19.553 | 0.000–87.210 | 0 |
| heat | G3 | 3/3 | 0.000 | 0.000–91.532 | 1 |
| ode | G1 | 1/1 | 96.551 | 96.551–96.551 | 1 |
| ode | G2 | 1/1 | 98.793 | 98.793–98.793 | 1 |
| ode | G3 | 1/1 | 99.068 | 99.068–99.068 | 1 |
| poisson | G1 | 1/1 | 44.308 | 44.308–44.308 | 1 |
| poisson | G2 | 0/1 | — | — | — |
| poisson | G3 | 1/1 | 0.000 | 0.000–0.000 | 0 |

heat 的中位数受未提交会话明显影响，不能据此断言某种指导稳定更优。ODE 三个会话均 12/12 通过，分数分别 96.551、98.793、99.068；仅各一次研究，不能作稳定排名。Poisson G1 的 final 为 **12/12 正确、2.513× speedup、reward=1**；G2 保留数值记录但无有效性能结论；G3 无提交为正常零结果。

## 每次研究的 first/final

`—` 表示缺失或无效，不等于零。无提交时没有 first 分，final 按协议为零。Poisson G2 两个检查点原始数值检查均在每次候选批次通过 12/12，但宿主窗口不合格，正式汇总的性能分、reward 和通过数均保守留空。

| 会话 | first 分 | final 分 | final 通过数 / 12 | reward | 结果 |
|---|---|---|---|---|---|
| heat G2 r1 | 93.791 | 87.210 | 11 | 0 | 已重放 |
| heat G3 r1 | 21.394 | 91.532 | 12 | 1 | 已重放 |
| heat G1 r1 | 93.631 | 93.631 | 12 | 1 | 已重放 |
| ode G1 r1 | 96.551 | 96.551 | 12 | 1 | 已重放 |
| ode G2 r1 | 98.793 | 98.793 | 12 | 1 | 已重放 |
| ode G3 r1 | 99.068 | 99.068 | 12 | 1 | 已重放 |
| poisson G3 r1 | — | 0.000 | 0 | 0 | 无有效提交 |
| poisson G2 r1 | — | — | — | — | 计时无效，留空 |
| poisson G1 r1 | 37.096 | 44.308 | 12 | 1 | 已重放 |
| heat G3 r2 | — | 0.000 | 0 | 0 | 无有效提交 |
| heat G1 r2 | — | 0.000 | 0 | 0 | 无有效提交 |
| heat G2 r2 | 19.553 | 19.553 | 0 | 0 | 已重放 |
| heat G3 r3 | — | 0.000 | 0 | 0 | 无有效提交 |
| heat G1 r3 | — | 0.000 | 0 | 0 | 无有效提交 |
| heat G2 r3 | — | 0.000 | 0 | 0 | 无有效提交 |

逐例误差、分档、通过情况和 first→final 差值见 [cases.csv](../results/formal-study-003/cases.csv)、[case-deltas.csv](../results/formal-study-003/case-deltas.csv)；30 个逻辑检查点见 [checkpoints.csv](../results/formal-study-003/checkpoints.csv)。无效 Poisson G2 的原始正确性记录保留在[其重放包装](../research-runs/research-6615cd7900ba0750/final-replays/research-6615cd7900ba0750-poisson-g2-r1-a001/result.json)，不以被拒绝的计时估计正式性能。

## 作者方法与固定参考

11 种方法均完成规定重放，弱方法的正常失败保留。固定参考是 heat `tikhonov`、ODE `fixed`、Poisson `lu`，并非事后挑选最佳方法。

| 任务 | 方法 | 分数 | 通过数 / 12 | reward | speedup |
|---|---|---|---|---|---|
| heat | ls | 19.556 | 0 | 0 | — |
| heat | rank5 | 89.893 | 12 | 1 | — |
| heat | tikhonov（固定参考） | 93.271 | 12 | 1 | — |
| heat | discrepancy | 91.651 | 12 | 1 | — |
| heat | tsvd | 92.192 | 12 | 1 | — |
| ode | raw | 0.000 | 0 | 0 | — |
| ode | fixed（固定参考） | 95.389 | 12 | 1 | — |
| ode | search | 95.647 | 12 | 1 | — |
| poisson | cg | 0.000 | 12 | 0 | 0.199 |
| poisson | jacobi | 0.014 | 12 | 0 | 1.000 |
| poisson | lu（固定参考） | 38.976 | 12 | 1 | 2.249 |

heat 固定参考分为 93.271；ODE 固定参考分为 95.389；Poisson LU 为 2.249×、38.976 分。各研究与固定参考的逐会话、逐组及逐例差值见 [fixed-reference-runs.csv](../results/formal-study-003/fixed-reference-runs.csv)、[groups](../results/formal-study-003/fixed-reference-groups.csv)、[cases](../results/formal-study-003/fixed-reference-cases.csv)。Poisson G2 对照为 null；作者基线不扩充研究分母。

## 迭代与新增成本

8 次有候选且可比较的会话中，2 次提升、1 次退化、5 次源码不变。另 6 次无提交、1 次计时无效无法判断变化。不能把 first→final 对照解释为反馈的因果收益。

| 会话 | first → final 分数 | 分数变化 | 通过数变化 |
|---|---|---|---|
| heat G2 r1 | 93.791 → 87.210 | -6.581 | 12 → 11 |
| heat G3 r1 | 21.394 → 91.532 | 70.138 | 0 → 12 |
| poisson G1 r1 | 37.096 → 44.308 | 7.212 | 12 → 12 |

Poisson G1 的 speedup 从 2.163× 变为 2.513×。5 个同源码会话只复用同一结果，记为“未观察到迭代”；heat G2 r1 虽有后续候选，final 通过数从 12 降到 11，结果保留。

下表以首次有效候选完成时间为界，列出随后新增成本；跨越该时间边界的请求无法拆分 token，保留 null（表中 `—`），不估算补齐。

| 会话 | 首次有效后秒数 | 新增公开评估 | 新增候选 CPU 秒 | 新增输出 token |
|---|---|---|---|---|
| heat G2 r1 | 95.2 | 3 | 0.760 | — |
| heat G3 r1 | 62.1 | 1 | 0.248 | — |
| heat G1 r1 | 17.0 | 0 | 0.000 | — |
| ode G1 r1 | 5.4 | 0 | 0.000 | 487 |
| ode G2 r1 | 93.1 | 3 | 68.025 | 999 |
| ode G3 r1 | 88.7 | 0 | 0.000 | — |
| poisson G2 r1 | 616.2 | 5 | 6.059 | 125,364 |
| poisson G1 r1 | 148.7 | 2 | 2.900 | 7,975 |
| heat G2 r2 | 1,781.8 | 0 | 0.000 | — |

## 总成本与版本历史

第三版共 7,650 次已接受 API 请求，7,644 次成功、6 次失败请求的实际输出未知。15 次有效研究的已知成功输出为 **2,324,341 token**；包含 4 个无效 attempt 的已知成功输出为 **2,591,496 token**。代理 charged 为 **2,613,274**，差额 21,778 是保守失败额度，不是实测输出或金额。输入/cache 用量按字段保存在 [attempts.csv](../results/formal-study-003/attempts.csv)，不混作输出预算。所有金额为 null。

15 次有效研究墙钟合计 18,992.862 秒（5.276 小时）；全部 19 attempt 的研究墙钟合计 23,428.333 秒（6.508 小时，含睡眠干扰），不包含全部准备、等待账户处理与交付时间。公开评估可见的候选 CPU 合计 116.573 秒，24 个导出失败行没有 CPU 值，完整总额保持未知。隐藏 W 的 CPU 合计 285.577 秒，其中作者 49.783 秒、研究重放（含 T3 比较器）235.795 秒；计时无效批次的已发生资源消耗仍计入成本。所有单位均按原记录，不换算货币。

| 冻结版本 | attempt | 有效研究关闭 | 已知成功输出 | charged |
|---|---|---|---|---|
| 1 | 2 | 0 | 43,743 | 43,743 |
| 2 | 5 | 3 | 102,284 | 110,476 |
| 3 | 19 | 15 | 2,591,496 | 2,613,274 |

旧版因原生压缩修复与预算修订分别封存；不把不同冻结版本合并为同一科学比较。上表仅覆盖三版正式计划，排除 pilot、合成探测和当前 Codex 对话。[版本成本记录](../logs/formal-execution-local-004/version-cost-history-001.json)保留逐版计算口径。

## 无提交、接口问题与计时无效

6 次无有效提交：Poisson G3、heat G3 r2/r3、heat G1 r2/r3、heat G2 r3。原因不完全相同：有长段逐字重复工具调用，有仅递增文件名的同一计算，也有持续改变随机种子开展自建模拟但未转入提交。heat G1 r2 连续 515 次只改变文件名，结果文本相同；heat G1 r3 则使用 220 个不同种子产生不同模拟结果，不能混为相同计算。所有正常失败按预算关闭，未为表现不足加跑。

62 次公开评估中 23 次产物有效，24 次源码导出失败均只显示 `ReadError: empty file`。包含 8 次点路径、11 次绝对路径、4 次 `solve.py`、1 次 `out`。冻结路径守卫拒绝点路径段且要求目录，通用提示没有明确说明 `.` 不可用；宿主空 tar 错误掩盖了具体 exporter 错误。此接口局限影响提交，不能把无提交全归因于数学能力。研究期间未改提示、替模型提交或修改冻结实现。完整证据见[提交诊断](submission-diagnosis-2026-10-23.md)与[全矩阵导出审计](../logs/formal-execution-local-004/closed-source-export-audit-002.json)。

T3 使用新观察窗口，未复用旧校准时间。LU 第一次 30 秒前置检查遇到 VPN CPU 峰值，尚未读取隐藏成绩、未生成 LU attempt；保留拒绝窗口后，新准入通过，LU 仅测一次。Poisson G2 在实际测量中出现 VPN 进程约 6.406% 单核 CPU 的样本，超过既定 5% 门槛，两个检查点保守留空，不重测。没有改阈值、停止用户 VPN 或将无效速度升级为正式成绩。

| 操作 | 窗口结果 | 证据 |
|---|---|---|
| cg | passed | [记录](../logs/formal-execution-local-004/window-baseline-poisson-cg/acceptance.json) |
| jacobi | passed | [记录](../logs/formal-execution-local-004/window-baseline-poisson-jacobi/acceptance.json) |
| lu | host_preflight_rejected | [记录](../logs/formal-execution-local-004/window-baseline-poisson-lu/acceptance.json) |
| lu | passed | [记录](../logs/formal-execution-local-004/window-baseline-poisson-lu-preflight-002/acceptance.json) |
| poisson-g1-r1 | passed | [记录](../logs/formal-execution-local-004/window-final-poisson-research-6615cd7900ba0750-poisson-g1-r1/acceptance.json) |
| poisson-g2-r1 | rejected | [记录](../logs/formal-execution-local-004/window-final-poisson-research-6615cd7900ba0750-poisson-g2-r1/acceptance.json) |
| poisson-g3-r1 | passed | [记录](../logs/formal-execution-local-004/window-final-poisson-research-6615cd7900ba0750-poisson-g3-r1/acceptance.json) |

## 验证、局限与交付

[正式报告生成](../logs/formal-execution-local-004/report-generation-001.stdout.txt)成功；[交付审计](../logs/formal-execution-local-004/final-audit-001.json)核对所有引用哈希、first/final 复用、三次重放、BCCBBC 顺序、93 个不同工作容器、资源限制和清理，当前运行容器为 0。冻结时的 [357 项测试](../logs/formal-freeze-local-003/unit-tests-final.txt)通过，随后可信源码未改动。两个交付审计草稿对记录字段的假设错误已留档并修正，仅修审计脚本，没有重跑实验或修改结果。

**完整有效科学验收未达成**：Poisson G2 的性能结论仍缺失；用户要求减少重试后，本轮以保留无效测量收束。小样本、三类合成任务、单一宿主与供应商别名映射均限制外推，不能声称跨科学领域能力或指导效果的因果结论。详细边界见[局限](limitations.md)。

本地证据包为 [evidence.tar.gz](../logs/formal-execution-delivery-local-005/evidence.tar.gz)，[成员清单](../logs/formal-execution-delivery-local-005/file-manifest.json)及[完整性与凭据扫描](../logs/formal-execution-delivery-local-005/integrity.json)单独保存。原始版本、失败 attempt、无效窗口、候选和逐例表全部保留。私有数值数组仍在本机 `authoring/data/v0.3-local`，由冻结哈希绑定；证据包不包含这些数组、宿主依赖或 Docker 镜像，不能单独解压即完整重跑。**本轮没有 GitHub 提交、推送或发布。**
