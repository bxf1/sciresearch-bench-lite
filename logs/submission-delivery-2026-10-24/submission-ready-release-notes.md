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
