# SciResearch-Bench-Lite

**科学计算领域的 Auto Research Benchmark**：热方程初场恢复、稀疏动力学辨识、稀疏线性系统求解优化。包含任务数据、研究环境、11 种作者基线、独立数值评分、Agent 轨迹和实验分析。

**提交链接：[github.com/bxf1/sciresearch-bench-lite](https://github.com/bxf1/sciresearch-bench-lite)**

[最终实验报告](docs/submission-report-2026-10-24.md) · [Benchmark 调研](docs/survey.md) · [数据索引](data/README.md) · [真实日志与证据链](docs/thinking-report-evidence-2026-10-25.md) · [复现指南](docs/reproduction.md) · [Release 与完整附件](https://github.com/bxf1/sciresearch-bench-lite/releases/tag/v0.3-submission-20261024)

## 作业阅读入口

建议先读[最终实验报告](docs/submission-report-2026-10-24.md)：按背景、调研、实验设计、评测规则、实验结果、预期与原因分析、改进和复现组织，含三张结果图及本轮 15 个 thinking/max 会话数据。另提供[阅读打印版 PDF](output/pdf/sciresearch-thinking-report-20261025.pdf)与[离线 HTML 阅读版](docs/submission-report-2026-10-24.html)，HTML 图像内嵌；GitHub 上请下载后打开。

- **G1 / G2 / G3**：详细方法指导 / 方向指导 / 共同任务契约。
- **r1 / r2 / r3**：同一任务和指导组的第 1 / 2 / 3 次独立研究会话。Heat 每组有三次；ODE、Poisson 每组只有 r1。
- **a001 / a002**：同一会话的执行尝试和关联重试；提交后的三次评分重放也不是新的研究会话。
- 数据按 Heat → ODE → Poisson、G1 → G2 → G3、r1 → r2 → r3 排列，另列实际执行序号。[排序数据及来源哈希](results/thinking-report-2026-10-25/analysis.json)由脚本读取既有证据生成。

Poisson G2 的候选数值检查通过；独立补测的原始中位耗时比为 **2.488×（仅诊断）**。正式计时因宿主背景进程 5.423% 超过冻结的 5% 阈值而无效，正式分数继续为空。诊断比值没有换算为正式分数，也不计入成功数。

## 按题目要求阅读

| 要求 | 交付内容 |
|---|---|
| 调研 Auto Research、AI Scientist、Research Agent、RSI | [调研文档](docs/survey.md)：ASI-Bench、Terminal-Bench-Science 等 6 项工作，比较任务、工具、环境、评分和局限，附固定源码引用及逻辑图 |
| 选择一个科研领域 | 科学计算；三类问题分别考察逆问题稳定化、动力学结构识别和正确性约束下的效率优化 |
| 至少 3 条完整任务、数据与基线 | [任务卡](docs/task_cards.md)、[90 例数据清单](data/README.md)、[本轮 11 种方法的结果及拒绝索引](docs/thinking-report-evidence-2026-10-25.md#本批作者基线) |
| 可复现环境与自动独立评分 | [环境和复现](docs/reproduction.md)、[隔离协议](docs/protocol.md)、[评分代码](judge/)、[可信执行器](runner/) |
| 端到端验证、失败与可靠性分析 | [最终报告第 6–10 节](docs/submission-report-2026-10-24.md)、[原始日志节选](docs/thinking-report-evidence-2026-10-25.md) |

## 任务与数据

| 任务 | Agent 输入与产物 | 成功条件概要 | 数据 |
|---|---|---|---|
| [Heat](docs/heat.md) | 带噪稀疏时空观测 → 初场 `u0.npy` | 初场误差 ≤0.15，未来场误差 ≤0.03 | 6 dev + 12 calibration + 12 final |
| [ODE](docs/ode.md) | 带噪多初值轨迹 → 稀疏系数 `model.json` | 隐藏轨迹及向量场误差均 ≤0.05，非零系数 ≤10 | 6 + 12 + 12 |
| [Poisson](docs/poisson.md) | CSR 矩阵与四列 RHS → `solution.npy` | 残差 ≤1e-8、解误差 ≤1e-5；正式效率要求 speedup ≥1.5 | 6 + 12 + 12 |

每个 split 内三个预设难度均衡。90/90 例通过独立 QC；数据按数学规则生成，未按方法成绩筛选。仓库含 18 个公开 dev 实例；原 90 例完整输入、作者真值、QC 和生成记录在 Release 的 `author-data-v0.3.tar.gz`，提供 [1,364 个文件的 SHA256](data/file-manifest.json)。下载、校验与解压方法见[数据说明](data/README.md)。

Agent 只看到 public-dev，提交源码后由宿主生成不可改写快照。独立 W 容器运行候选，J 只读数值产物和真值，不执行候选代码；隐藏评分在研究关闭后进行。完整作者数据的公开下载不改变运行时隔离规则，不能将整个仓库或作者数据挂入研究容器。

## Thinking/max 实验结果

本版只展示 [thinking 冻结计划](freezes/research-run-plan-thinking-max-2026-10-25.json)下的结果：thinking=enabled、effort=max，每请求 4,096／每会话 200,000 输出 token，最多 30 分钟、20 次公开评估。

- **15/15 有提交，14/15 最终评分有效且成功。** Poisson G2 计时无效，正式成绩为空；不记零分、不估填。
- Heat 九次最终分为 91.957–93.688，ODE 三次为 98.994–99.266。Poisson G1 为 68.376（独立计时补测），G3 为 44.169；不同任务不计算总平均分。
- **三条任务均完成有效基线验证。** 本轮 11 种作者方法中 10 项有有效结果，Jacobi-CG 独立基线的准入拒绝留空；弱方法未成功也如实列出。
- 会话内 first → final 为 5 升、4 降、5 同源码、1 无法比较。Heat G1 r2 的真实端到端案例由 93.271 小幅提高到 93.627，首次和最终都通过 12/12。
- 15 个保留 attempt 输出 896,210 token；包括两个旧 attempt 后已知输出 925,815，代理 charged 929,911。三次执行器修复、两次关联重试及 252 次无进展续接单列。

本轮是事后追加的实验，沿用已使用过的隐藏集、串行执行且中途修复。不能据此宣称 thinking 的因果收益、指导组稳定优劣或全新盲测。

[完整排序数据](results/thinking-report-2026-10-25/analysis.json) · [15 行原始证据索引](docs/thinking-report-evidence-2026-10-25.md) · [计时补测与拒绝记录](docs/poisson-timing-recheck-2026-10-25.md)

## 上一版材料暂存

上一版跨批比较的报告、PDF、图表、数据、README 和生成脚本已保存为[独立快照](archives/pre-thinking-only-20261025/README.md)，附逐文件清单和 SHA256。原始实验、失败、修复、拒绝记录及全部原 Release 附件均保留，当前主报告不再混列历史非 thinking 成绩。历史专项文档用于溯源，不作为本版结果表。

[本次作业要求检查与修正清单](docs/delivery-audit-thinking-2026-10-25.md)记录证据审计、排版检查及仍保留的限制。

## 快速核验

先验证交付文件与结果一致性，只需 Python 3.10+ 标准库，无模型调用、无 Docker：

```bash
git clone https://github.com/bxf1/sciresearch-bench-lite.git
cd sciresearch-bench-lite
python3 tools/verify_delivery.py
```

该命令核对交付清单、90 例索引、仓库内公开数据、原 11 种基线、历史证据，以及当前 thinking 的 15 个会话终态、候选、评分、用量和图表来源哈希。可再运行 `python3 tools/audit_thinking_report.py` 查看本版专项审计。完整数据另行下载后可加 `--author-archive <文件路径>` 逐文件校验。

实际数值重放需要 **Python 3.12、锁定依赖与 Docker**。请按[复现指南](docs/reproduction.md)安装，再运行全部基线或已有候选；新机器须重新验收资源与计时环境。正式 Agent 研究另需模型凭据、研究镜像、受控代理与新的冻结计划。历史 freeze 绑定原机器和原实验，不能直接改哈希以绕过验收。

## 仓库结构

```text
authoring/          数据生成、独立 QC、作者真值构造
tasks/             三条 Harbor 任务包与 18 例 public-dev
data/              90 例索引、分布与完整归档文件哈希
baselines/         Heat 5 / ODE 3 / Poisson 3 种方法
environment/       固定数值镜像与研究环境
prompts/           三任务 G1/G2/G3 提示
public/            公开诊断与共享比较器
runner/ + judge/   可信登记、容器执行、独立自动评分
freezes/           原实验数据、源码、参数和环境冻结记录
results/           正式结果、逐例 CSV 与交付分析
research-runs/     研究事件、登记快照和评分记录
logs/              运行、隔离、资源、测试和发布证据
docs/              调研、设计、实验报告、日志导读与复现
tools/             交付表格生成和完整性核验
```

大型完整轨迹另存 Release：原始证据包约 467 MiB、作者数据约 27 MB；历史附件保留，最新交付包使用独立名称。Release 的历史标签保留初次提交，**当前交付以 main 为准；`submission-ready-20261024.tar.gz` 为 10 月 24 日历史快照，thinking 对照增量证据见 `thinking-control-evidence-20261025.tar.gz`**，不要将页面自动生成的旧标签源码 ZIP 当作最新报告。

Poisson 后续计时证据另存 `poisson-timing-recheck-20261025.tar.gz`，保留原拒绝窗口。G2 的正式性能需要新的合格宿主窗口验证；本轮报告整理只读取既有证据。当前 thinking 专版另存 `thinking-only-report-20261025.tar.gz`，配套独立 PDF、HTML、manifest 和 SHA256SUMS；与 main 及已有实验附件配合使用。`final-report-readable-20261025.tar.gz` 是保留的上一版阅读材料。

本项目只验证受控合成分布上的求解器研究，不声称原创科学发现或已实现真正 RSI；同宿主、小样本及模型路由可变等限制见[最终报告](docs/submission-report-2026-10-24.md)。历史日志保持原文，以本 README 和最终报告作为当前入口。
