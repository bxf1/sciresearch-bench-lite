# SciResearch-Bench-Lite

**科学计算领域的 Auto Research Benchmark。** 本项目研究：AI 能否在有限预算内选择方法、编写代码、执行实验，并根据反馈改进求解结果？实现了热方程初场恢复（Heat）、稀疏动力学辨识（ODE）和稀疏线性系统求解优化（Poisson）三条完整任务，包含数据、运行环境、作者基线、独立评分和原始日志。

**作业提交链接：[github.com/bxf1/sciresearch-bench-lite](https://github.com/bxf1/sciresearch-bench-lite)**

**最终报告 PDF（19 页，含附录）：[在线查看](output/pdf/sciresearch-thinking-r1-report-20261025.pdf) · [直接下载](https://github.com/bxf1/sciresearch-bench-lite/releases/download/v0.3-submission-20261024/sciresearch-thinking-r1-report-20261025.pdf)**

报告、代码、实验结果及日志索引均在仓库中；完整作者数据和大型原始日志包位于本仓库的 [Release](https://github.com/bxf1/sciresearch-bench-lite/releases/tag/v0.3-submission-20261024)。分享仓库链接即可访问全部交付材料。

## 建议阅读顺序

1. **看完整方案与结论：** [最终报告](docs/submission-report-2026-10-24.md)或上方 PDF，依次介绍背景、调研、任务与实验设计、评测规则、实验结果、原因分析、是否符合预期及后续改进。
2. **核对数据与日志：** [任务数据索引](data/README.md)、[正文与附录结果数据](results/thinking-r1-report-2026-10-25/analysis.json)、[逐会话原始证据索引](docs/thinking-report-evidence-2026-10-25.md)。
3. **运行与复现：** 先执行下方快速核验，再按[复现指南](docs/reproduction.md)安装环境、运行基线或重放候选。

也提供[离线 HTML 报告](docs/submission-report-2026-10-24.html)，图像已内嵌，下载后可用浏览器阅读。

## 作业要求与交付内容

| 作业要求 | 已完成内容与入口 |
|---|---|
| 调研 Auto Research、AI Scientist、Research Agent、RSI 及相关 Benchmark | [调研文档](docs/survey.md)：比较 ASI-Bench、Terminal-Bench-Science 等 6 项工作的任务、环境、工具、指标、自动评分和局限 |
| 选择一个具体科研领域 | 科学计算：逆问题稳定化、动力学结构识别、正确性约束下的求解效率优化 |
| 至少 3 条完整任务，完成数据、环境和基线验证 | [三条任务卡](docs/task_cards.md)、[90 例合成数据与质量检查](data/README.md)、[11 种作者方法及结果](docs/thinking-report-evidence-2026-10-25.md#本批作者基线)；三任务均有有效基线验证 |
| 可运行、可自动评分、可复现，并隔离隐藏测试 | [环境与复现](docs/reproduction.md)、[隔离协议](docs/protocol.md)、[可信执行器](runner/)、[独立评分程序](judge/) |
| 至少一条任务完成 Agent 到自动评分的端到端验证 | 最终报告以 Heat G1 r1 为完整案例，覆盖公开实验、提交登记、隐藏评分、原始日志和故障说明 |
| 分析难度、失败、可靠性、局限与改进方向 | [最终报告第 6–11 节](docs/submission-report-2026-10-24.md)；原始失败、重试和计时拒绝记录保留 |

## 三条任务与数据

| 任务 | Agent 需要完成什么 | 成功条件概要 | 每任务数据划分 |
|---|---|---|---|
| [Heat：热方程初场恢复](docs/heat.md) | 从带噪稀疏温度观测恢复初始温度分布，输出 `u0.npy` | 初场相对误差 ≤0.15，未来场误差 ≤0.03 | 6 公开开发 + 12 作者校准 + 12 最终测试 |
| [ODE：稀疏动力学辨识](docs/ode.md) | 从带噪轨迹识别简洁的动力学方程，输出 `model.json` | 隐藏轨迹及向量场误差均 ≤0.05，非零系数 ≤10 | 同上 |
| [Poisson：稀疏求解优化](docs/poisson.md) | 正确且高效地求解四个右端项，输出 `solution.npy` | 残差 ≤1e-8、解误差 ≤1e-5，并在合格计时环境达到 ≥1.5× 加速 | 同上 |

三任务共 **90 个合成实例**，每个划分内的易、中、难数量均衡，90/90 通过独立质量检查（QC）。仓库直接包含 18 个公开开发实例；完整 90 例输入、作者参考真值、QC 和生成记录通过 Release 的 `author-data-v0.3.tar.gz` 提供，附 [1,364 个文件的哈希清单](data/file-manifest.json)。下载和验证方法见[数据说明](data/README.md)。

Agent 研究时只接触公开数据。提交后，宿主保存不可改写的源码快照；全部研究关闭后，由独立容器运行候选，另一评分容器读取数值产物和隐藏真值判分。**成绩由独立程序验证，不能由 Agent 自报。** 作者数据公开用于复核，但不能挂入研究容器；已经公开的旧隐藏集也不能再称为全新盲测集。

## 实验设计与编号

当前报告只展示 **thinking=enabled、effort=max** 的实验。模型路由为 `deepseek-flash`，通过 Harbor / 原生 Pi 执行；供应商内部模型修订不能独立锁定。每会话最多 **30 分钟、20 次公开评估、200,000 输出 token**，每请求最多 4,096 输出 token；累计额度包含 thinking 和原生上下文压缩。详细配置见[冻结计划](freezes/research-run-plan-thinking-max-2026-10-25.json)及最终报告第 4 节。

| 编号 | 含义 |
|---|---|
| G1 | 共同任务说明 + 详细方法指导 |
| G2 | 共同任务说明 + 研究方向，不给具体算法名 |
| G3 | 共同任务说明，Agent 自行选择方法；仍有目标、输入、工具和输出要求 |
| r1 / r2 / r3 | 同一任务、同一指导组的第 1 / 2 / 3 次独立研究，从新工作区开始，不继承上次候选 |
| a001 / a002 | 同一研究会话的原执行尝试 / 关联重试；重试不另算独立科学样本 |

例如，**Heat G2 r1** 是“热方程任务、方向指导组、第 1 次独立研究”。Heat 每组运行三次，ODE 与 Poisson 每组运行一次，共 15 个研究会话。

正文统一按 **Heat → ODE → Poisson、G1 → G2 → G3** 展示各组 r1，共 9 个会话（M01–M09）；Heat 的 r2/r3 共 6 个会话在附录（A01–A06）。这是报告展示规则，没有按成绩挑选，也没有把原实验改写成只运行 9 次。候选提交后的三次评分重放也不另算研究会话。

## 主要结果：正文的 9 个 r1 会话

下表是最终候选的独立评分，保留三位小数。各任务采用不同评分公式，**不跨任务计算平均分或比较分数高低**。

| 任务 | G1 r1 | G2 r1 | G3 r1 | 结果说明 |
|---|---:|---:|---:|---|
| Heat | 93.388 | 93.328 | 93.041 | 三组均满足最终测试成功条件 |
| ODE | 99.266 | 99.266 | 98.994 | 三组均满足最终测试成功条件 |
| Poisson | 68.376 | — | 44.169 | G1、G3 成功；G2 数值正确，但正式计时无效 |

**正文 9/9 形成已登记提交，8/9 获得有效且成功的最终成绩。** `—` 表示没有有效成绩，不是零分。Poisson G1 使用独立计时补测结果；G2 的宿主背景活动超过冻结阈值，补测原始耗时比 **2.488× 仅作诊断**，未转换为正式分数或计入成功数。证据见[计时补测与拒绝记录](docs/poisson-timing-recheck-2026-10-25.md)。

从首次候选到最终候选，正文 9 个会话有 **3 次改善、2 次退化、3 次源码未变、1 次无法比较**。这说明反馈迭代可以改善方法，也可能使结果退化。本批 11 种作者方法中，10 项有有效结果，Jacobi-CG 独立基线窗口准入拒绝；三条任务仍均完成有效基线验证。

正文每组只有一次结果，不能据此判断组别稳定优劣。完整 15 会话的统计、Heat 重复实验、token 与时间开销、两次关联重试及中途基础设施修复均见报告及附录。原失败和无进展续接如实保留，不重算为额外成功样本。[排序数据](results/thinking-r1-report-2026-10-25/analysis.json)保留完整精度、实际执行序号和来源哈希，可经[原始证据索引](docs/thinking-report-evidence-2026-10-25.md)追溯。

## 快速核验与复现

**只检查交付材料与结果一致性**：需要 Python 3.10+ 标准库，不需要 Docker 或模型凭据。

```bash
git clone https://github.com/bxf1/sciresearch-bench-lite.git
cd sciresearch-bench-lite
python3 tools/verify_delivery.py
```

该命令检查交付文件哈希、数据索引、公开输入、基线和历史证据，以及本轮会话终态、候选、评分、用量和图表来源。可运行 `python3 tools/audit_thinking_report.py` 查看专项审计。完整作者数据需另行下载，再用 `--author-archive <文件路径>` 校验；仅克隆仓库的检查不会声称验证了未下载的完整数据包。

**实际执行数值实验**：需要 Python 3.12、锁定依赖和 Docker。按[复现指南](docs/reproduction.md)安装环境后，可以运行三任务基线或重放已提交候选，这些操作不调用模型。新 Agent 研究另需模型凭据、研究镜像、资源验收及新冻结计划。新机器必须重新验收计时环境，不能直接继承本机速度结论；文件核验也不等于重新完成数值实验。

## 交付文件位置

```text
output/pdf/        最终报告 PDF（当前版本见页首链接）
docs/              报告、调研、设计、评分说明、日志导读和复现指南
tasks/             三条任务包与 18 例公开输入
data/              90 例数据索引、划分统计与完整数据哈希
authoring/         数据生成与独立质量检查
baselines/         Heat 5 / ODE 3 / Poisson 3 种作者方法
environment/       固定运行环境与依赖
prompts/           三任务 G1/G2/G3 提示
public/            公开评估工具
runner/ + judge/  可信执行器与独立自动评分
freezes/           数据、源码、参数和环境冻结记录
results/           实验结果与机器可读分析
research-runs/     研究事件、候选快照和评分记录
logs/              运行、失败、重试、资源与核验证据
tools/             报告表格生成与完整性核验
archives/          历史阅读材料快照
```

**当前交付使用 `main` 分支。** [Release](https://github.com/bxf1/sciresearch-bench-lite/releases/tag/v0.3-submission-20261024) 中保留不同阶段的附件，按用途下载：

| 附件 | 用途 |
|---|---|
| `sciresearch-thinking-r1-report-20261025.pdf` | 当前最终报告，与仓库 PDF 一致 |
| `thinking-r1-report-20261025.tar.gz` | 当前报告、图表、排序分析与生成脚本的阅读包 |
| `author-data-v0.3.tar.gz` | 完整 90 例数据、作者真值、QC 和生成记录 |
| `thinking-control-evidence-20261025.tar.gz` | thinking 批次全部 17 个 attempt 的轨迹、独立评分及修复记录 |
| `poisson-timing-recheck-20261025.tar.gz` | Poisson 独立计时补测及拒绝证据 |

各包提供对应文件清单和 SHA256 校验。实验增量包应与 main 和作者数据配合使用。[交付核对清单](docs/delivery-audit-thinking-r1-2026-10-25.md)记录正文/附录统计口径及图表、日志、PDF 的对应关系。

<details>
<summary>历史版本与归档说明</summary>

上一版跨批比较材料已[独立暂存](archives/pre-thinking-only-20261025/README.md)。原始实验、失败、修复、拒绝记录及旧 Release 附件保留，当前报告不混列历史非 thinking 成绩。

Release 标签对应初次发布，页面自动生成的标签源码 ZIP 不代表最新 main。`submission-ready-20261024.tar.gz` 是 10 月 24 日历史快照，`evidence.tar.gz` 是原批次完整证据包；`thinking-only-report-20261025.tar.gz` 和 `final-report-readable-20261025.tar.gz` 是先前阅读版本。历史记录中的“未发布”等表述保留当时原文，当前入口以本 README 和页首 PDF 为准。

</details>

本项目验证的是受控合成问题上的求解器研究流程。小样本、同宿主运行、已使用过的隐藏集、中途基础设施修复及供应商模型路由变化限制了结论；不据此宣称 thinking 的因果收益、原创科学发现或真正的递归自我改进（RSI）。具体分析与改进方向见最终报告。
