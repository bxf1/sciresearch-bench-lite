## 最终作业阅读版（2026-10-25）

[最终实验报告](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/submission-report-2026-10-24.md)已按背景、调研、设计、评测规则、实验结果、原因与预期分析、改进和复现重新整理。明确解释 G1/G2/G3、r1/r2/r3、attempt 与评分重放；15 格结果按任务、指导组、repeat 顺序排列，另保留实际执行序号。

新增 16 页 PDF、离线 HTML、3 张结果图、可重建排序数据和脚本。源码提交 `4b0436e4e9de0ab04513f8b263f4680cf65efb9a`。PDF 和 HTML 可直接下载；`final-report-readable-20261025.tar.gz` 是阅读与分析增量包，配套 manifest 和 SHA256SUMS，不替代已有实验和作者数据。

科学结果保持：原批次 6/15 成功；thinking/max 对照 15/15 有提交、14 项正式成功、G2 正式成绩仍为空。G2 数值通过 12/12，其独立补测原始中位耗时比 2.488× 明确仅作诊断，不换算为正式分数，也不计入成功数。此次整理无模型调用、无候选重跑、未改冻结参数。

此前全部 17 个附件及原始失败、重试、计时拒绝证据保留。下文为既有发布说明。

---

## Poisson 独立计时补测（2026-10-25，18:36 关闭）

[当前仓库](https://github.com/bxf1/sciresearch-bench-lite) · [补测报告与日志](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/poisson-timing-recheck-2026-10-25.md) · [最终报告](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/submission-report-2026-10-24.md) · [当前机器可读结果](https://github.com/bxf1/sciresearch-bench-lite/blob/main/results/poisson-timing-recheck-2026-10-25/reviewed-results.json)。本轮源码与结果提交：[`e20f776`](https://github.com/bxf1/sciresearch-bench-lite/commit/e20f7763c0c47b4970af819f6987464b527d8c1c)。

| 会话 | 最终成绩 | 计时结论 |
|---|---|---|
| Poisson G1 r1 | 68.376175 / reward=1 | 有效，加速比 4.144750×；首次为 64.342487 分、3.811277× |
| Poisson G2 r1 | null / null | 实测窗口 VPN 后台达 5.423% 单核占用，超过原 5% 阈值，再次无效 |

这次两个补测操作已结束，但**没有取得 G2 的有效计时**。G1/G2 各保留一次新前置拒绝，以及之后各一次完整获准测量。没有停止用户 VPN、放宽阈值或循环重测到通过。

- 用户在首次发布后明确授权重放已有 first/final 候选。0 Agent 启动、0 模型调用，原冻结参数、评分器、BCCBBC 顺序、资源及 8,851 个原证据文件哈希不变。
- 原正式批次、首次 thinking 对照和原拒绝不改写。计入 G1 新观察后，当前 thinking 对照为 **15/15 有提交、14/15 有效评分、14 项 reward=1，G2 仍 null**。作者基线仍 10 项有效、Jacobi 准入拒绝；本次未补测作者基线。
- 14 对可比较最终分数为 12 升、2 降，含 6 项原无提交；首次→最终为 5 升、4 降、5 同源码、1 不可比较。仍是原 15 个独立研究样本、17 个 research attempt，不新增科学样本或模型用量。
- 这是原结果发布后的新宿主计时观察。G1 跨批次分差同时含宿主窗口变化，不能单独归因于模型模式或算法；事后对照、旧隐藏集及中途执行器修复等限制继续适用。

### 新增附件（原 14 个全部保留）

- `poisson-timing-recheck-20261025.tar.gz`：804 文件、97,703,445 bytes，包含本轮拒绝、G1 有效重放、G2 无效重放、连续宿主观察和全部新数值产物；增量包配合 main 使用。
- `poisson-timing-recheck-manifest-20261025.json`：逐文件大小、SHA256、源码提交及范围。
- `poisson-timing-recheck-SHA256SUMS-20261025.txt`：归档与清单 SHA256。

归档 SHA256：`9bd6bcfaecc34e9951031b51a575c2e4d0c0ed13e360133449ffb599d0385675`。

`python3 tools/verify_delivery.py` 校验当前交付，`python3 tools/analyze_poisson_timing_recheck.py` 从已有证据重建合并视图。18,666 个交付文件、122 个文档链接、干净副本重建和拒绝证据篡改检查通过；凭据扫描通过。报告生成和交付核验不执行模型或候选。

**当前入口为 main；Release 历史标签源码及此前命名附件保持历史内容。**

---

以下保留首次 thinking/max 发布说明；其中“当前”指当时发布：

## Thinking/max 对照已完成（2026-10-25）

当前交付入口：[仓库 main](https://github.com/bxf1/sciresearch-bench-lite) · [最终报告](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/submission-report-2026-10-24.md) · [完整 thinking/max 报告与日志](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/thinking-control-2026-10-25.md)。本轮结果提交：[`2d13936`](https://github.com/bxf1/sciresearch-bench-lite/commit/2d13936bf6914716536867a7f01de1296766bb48)。

- 15/15 个研究会话已关闭并有有效公开提交；13/15 项独立最终评分有效，13 项 reward=1。Poisson G1/G2 因宿主计时准入拒绝，保持 null，不能记为零分。
- Heat 9 项 91.957–93.688；ODE 3 项 98.994–99.266；Poisson G3 为 44.169。作者基线本轮 10 项有效，Jacobi 准入拒绝；原正式批次 11 项基线结果保留。
- 原 formal-003 仍为 9/15 有提交、6 次 reward=1、8 次有效未成功、1 次计时无效。13 对可比较最终分数中 11 升、2 降，其中 6 项上升来自原无提交。新批次首次→最终为 4 升、4 降、5 同源码、2 不可比较。
- 15 个保留 attempt 输出 896,210 token；全部 17 个 attempt 已知输出 925,815、charged 929,911。两个原失败、关联重试、三次执行器修复以及 252 次无进展单 token 续接均保留。
- 这是事后匹配对照：thinking 与 max 同时改变，temperature 不生效，复用旧隐藏集且先后执行，中途修复执行器；不宣称单因素因果收益或全新盲测，不合并成 30 次同条件样本。原 500k 补跑仍取消。

### 新增附件

| 附件 | 内容 |
|---|---|
| thinking-control-evidence-20261025.tar.gz | 本轮增量源码、报告、17 次尝试、独立评分、完整原生轨迹、修复与拒绝窗口；8,785 文件、310,600,259 bytes |
| thinking-control-manifest-20261025.json | 逐文件大小/SHA256、源码提交与排除项 |
| thinking-control-SHA256SUMS-20261025.txt | 证据归档及文件清单的 SHA256 |

证据包 SHA256：`c956f8e465270c904e3c05655718807942428fe6b7923c5bd5fbe11295e0d98d`。

仓库 main 运行 `python3 tools/verify_delivery.py` 可核对原实验与新对照；`python3 tools/analyze_thinking_control.py` 从已有 JSON 重建精确配对表，不调用模型或执行候选。18,307 个交付文件及干净副本检查通过；凭据扫描通过。此次生成报告、校验和打包不是新增科学重放。

**本轮保留全部既有 11 个附件。增量包配合 main 及原作者数据使用；旧 submission-ready 附件和本标签自动生成的 Source code ZIP/TAR 均为历史快照。**

---

以下为 2026-10-24 历史交付说明；其中“最新”指该日期当时的版本：

## 最终作业交付版（2026-10-24）

提交入口：[GitHub 仓库](https://github.com/bxf1/sciresearch-bench-lite)。最终报告与数据整理提交：[`bf665bcb8a25c1d3e9249b0ea23b8a80290b1039`](https://github.com/bxf1/sciresearch-bench-lite/commit/bf665bcb8a25c1d3e9249b0ea23b8a80290b1039)。

- [最终实验报告](https://github.com/bxf1/sciresearch-bench-lite/blob/bf665bcb8a25c1d3e9249b0ea23b8a80290b1039/docs/submission-report-2026-10-24.md)：按调研、领域选择、三任务数据、环境评分、实验分析与局限组织。
- [调研与逻辑图](https://github.com/bxf1/sciresearch-bench-lite/blob/bf665bcb8a25c1d3e9249b0ea23b8a80290b1039/docs/survey.md)：ASI-Bench、Terminal-Bench-Science、AI Scientist v2、ScienceAgentBench、MLGym、DGM。
- [数据索引](https://github.com/bxf1/sciresearch-bench-lite/blob/bf665bcb8a25c1d3e9249b0ea23b8a80290b1039/data/README.md)：90 例、9 个 task/split、1,364 个原数据文件哈希；仓库内提供 18 个 dev 实例。
- [真实日志](https://github.com/bxf1/sciresearch-bench-lite/blob/bf665bcb8a25c1d3e9249b0ea23b8a80290b1039/docs/evidence.md)：资源验收、公开反馈、候选登记、独立评分、计时拒绝和冻结测试。
- [复现指南](https://github.com/bxf1/sciresearch-bench-lite/blob/bf665bcb8a25c1d3e9249b0ea23b8a80290b1039/docs/reproduction.md)：交付核验、固定依赖、三任务基线、已有候选重放及正式研究入口。

### 实验结论与边界

11 种作者基线已完成。原正式 15 次研究中 9 次有提交、6 次正常无提交；有效评分 14/15，包含无提交零分。最终为 **6 次 reward=1、8 次有效未成功、1 次计时无效**，不将有效评分率解释为成功率。

Heat G3 r1 从 21.394 分 / 0/12 通过，提升到 91.532 分 / 12/12 通过。源码差异、公开反馈和三次独立隐藏重放均已归档。8 个可比较会话中 2 次改进、1 次退化、5 次源码不变；不据小样本宣称组间优势。

500,000 token 选择性补跑已按用户要求取消，无新增有效科学结果；原 Poisson G2 的无效计时仍为 null。失败尝试和拒绝窗口保留，不再排队补跑。此次交付整理没有新增模型调用或候选执行。

### 下载与完整性

| 附件 | 用途 |
|---|---|
| **submission-ready-20261024.tar.gz** | 最新完整 Git 快照：代码、报告、公开任务数据、结果和已提交日志；12,725 个文件，283,451,577 bytes |
| submission-ready-manifest.json / submission-ready-integrity.json | 最新归档逐文件清单、提交 SHA、大小与 SHA256 |
| author-data-v0.3.tar.gz / author-data-integrity.json | 原 90 例完整作者数据、真值、QC 与生成记录；27,088,532 bytes |
| evidence.tar.gz / file-manifest.json / integrity.json | 原正式全量证据，9,252 个文件，489,437,835 bytes |
| final-report-20261024.tar.gz / final-report-manifest.json / final-report-integrity.json | 此前报告与取消补跑记录，保留历史附件 |

最新完整快照 SHA256：

```text
d6f3839e364d0ff87f8cac48702bfbbca11c7ee2c8ae1b8566cfd83b69906156
```

解压最新快照后执行：

```bash
cd sciresearch-bench-lite
python3 tools/verify_delivery.py
```

已在不含 .git、.venv 或未提交数据的解压副本中通过核验，并确认故意改动公开输入会被校验拒绝；使用同一宿主 Python，属于交付一致性审计，不是跨机器科学复现。原作者数据包另行逐文件校验通过。所有此次待发布文件完成已知凭据及常见凭据格式扫描。

**本 Release 标签保留初次提交，页面自动生成的 Source code ZIP/TAR 仍是历史源码。最新交付请使用 main 或上表中命名的 submission-ready 附件。** 原有 8 个附件保留不覆盖。完整作者数据仅供作者与可信评分程序复现，研究 Agent 仍只能访问对应 public-dev。
