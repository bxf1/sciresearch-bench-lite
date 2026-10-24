# SciResearch-Bench-Lite

**科学计算领域的 Auto Research Benchmark**：热方程初场恢复、稀疏动力学辨识、稀疏线性系统求解优化。包含任务数据、研究环境、11 种作者基线、独立数值评分、Agent 轨迹和实验分析。

**提交链接：[github.com/bxf1/sciresearch-bench-lite](https://github.com/bxf1/sciresearch-bench-lite)**

[最终实验报告](docs/submission-report-2026-10-24.md) · [Benchmark 调研](docs/survey.md) · [数据索引](data/README.md) · [真实日志与证据链](docs/evidence.md) · [复现指南](docs/reproduction.md) · [Release 与完整附件](https://github.com/bxf1/sciresearch-bench-lite/releases/tag/v0.3-submission-20261024)

## 按题目要求阅读

| 要求 | 交付内容 |
|---|---|
| 调研 Auto Research、AI Scientist、Research Agent、RSI | [调研文档](docs/survey.md)：ASI-Bench、Terminal-Bench-Science 等 6 项工作，比较任务、工具、环境、评分和局限，附固定源码引用及逻辑图 |
| 选择一个科研领域 | 科学计算；三类问题分别考察逆问题稳定化、动力学结构识别和正确性约束下的效率优化 |
| 至少 3 条完整任务、数据与基线 | [任务卡](docs/task_cards.md)、[90 例数据清单](data/README.md)、[11 种基线及逐例结果](results/formal-study-003/baselines.csv) |
| 可复现环境与自动独立评分 | [环境和复现](docs/reproduction.md)、[隔离协议](docs/protocol.md)、[评分代码](judge/)、[可信执行器](runner/) |
| 端到端验证、失败与可靠性分析 | [最终报告第 5–9 节](docs/submission-report-2026-10-24.md)、[原始日志节选](docs/evidence.md)、[提交与循环诊断](docs/submission-diagnosis-2026-10-23.md) |

## 任务与数据

| 任务 | Agent 输入与产物 | 成功条件概要 | 数据 |
|---|---|---|---|
| [Heat](docs/heat.md) | 带噪稀疏时空观测 → 初场 `u0.npy` | 初场误差 ≤0.15，未来场误差 ≤0.03 | 6 dev + 12 calibration + 12 final |
| [ODE](docs/ode.md) | 带噪多初值轨迹 → 稀疏系数 `model.json` | 隐藏轨迹及向量场误差均 ≤0.05，非零系数 ≤10 | 6 + 12 + 12 |
| [Poisson](docs/poisson.md) | CSR 矩阵与四列 RHS → `solution.npy` | 残差 ≤1e-8、解误差 ≤1e-5；正式效率要求 speedup ≥1.5 | 6 + 12 + 12 |

每个 split 内三个预设难度均衡。90/90 例通过独立 QC；数据按数学规则生成，未按方法成绩筛选。仓库含 18 个公开 dev 实例；原 90 例完整输入、作者真值、QC 和生成记录在 Release 的 `author-data-v0.3.tar.gz`，提供 [1,364 个文件的 SHA256](data/file-manifest.json)。下载、校验与解压方法见[数据说明](data/README.md)。

Agent 只看到 public-dev，提交源码后由宿主生成不可改写快照。独立 W 容器运行候选，J 只读数值产物和真值，不执行候选代码；隐藏评分在研究关闭后进行。完整作者数据的公开下载不改变运行时隔离规则，不能将整个仓库或作者数据挂入研究容器。

## 已有实验结论

正式批次为 [formal-003](freezes/research-run-plan-formal-003.json)：同一模型路由、三种指导强度，Heat 每组 3 次，ODE/Poisson 每组各 1 次；每会话 200,000 输出 token、30 分钟、20 次公开评估。

- **三任务、11 种作者基线全部完成**。弱基线失败如实保留；Poisson 数值正确与效率达标分别统计。
- **15 次研究：9 次有提交、6 次正常无提交**。14/15 有有效评分，其中 **6 次 reward=1、8 次有效未成功**；Poisson G2 计时环境无效，成绩为 null。
- **三任务均有端到端 Agent 验证**。Heat G3 r1 的独立隐藏分数从 21.394 升至 91.532，通过数从 0/12 升至 12/12，首次和最终候选各重放 3 次；[真实登记与评分日志](docs/evidence.md)可追溯。
- 8 个可比较会话中 2 个改进、1 个退化、5 个源码不变。样本小，不能证明某指导组更优，也不将三任务分数直接平均。
- 原冻结版本测试日志为 **357 passed**；后续 token-only 支持版本为 360 passed。交付校验只核对文件和已存结果，不冒充新科学实验。

[15 次会话表](results/delivery-analysis/run-summary.csv) · [基线分难度表](results/delivery-analysis/baseline-by-difficulty.csv) · [完整正式结果与成本](docs/formal-results-2026-10-23.md)

选择性扩大到 500,000 token 的补跑已提前取消，没有新增有效科学结果；相关尝试、循环诊断及计时拒绝记录保留在[补充附录](docs/supplemental-results-2026-10-24.md)，不加入原等预算比较。

## 快速核验

先验证交付文件与结果一致性，只需 Python 3.10+ 标准库，无模型调用、无 Docker：

```bash
git clone https://github.com/bxf1/sciresearch-bench-lite.git
cd sciresearch-bench-lite
python3 tools/verify_delivery.py
```

该命令核对交付清单、90 例索引、仓库内公开数据、11 种基线、15 次研究和日志来源哈希。完整数据另行下载后可加 `--author-archive <文件路径>` 逐文件校验。

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

大型完整轨迹另存 Release：原始证据包约 467 MiB、作者数据约 27 MB；历史附件保留，最新交付包使用独立名称。Release 的历史标签保留初次提交，**当前交付以 main 和 `submission-ready-20261024.tar.gz` 内记录的提交为准**，不要将页面自动生成的旧标签源码 ZIP 当作最新报告。

本项目只验证受控合成分布上的求解器研究，不声称原创科学发现或已实现真正 RSI；同宿主、小样本及模型路由可变等限制见[最终报告](docs/submission-report-2026-10-24.md)。历史日志保持原文，以本 README 和最终报告作为当前入口。
