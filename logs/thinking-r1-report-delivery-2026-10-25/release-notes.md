## 最新作业报告：正文 r1，Heat 重复实验保留在附录

[当前报告](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/submission-report-2026-10-24.md)的正文只展示 Heat G1 r1、G2 r1、G3 r1，以及 ODE、Poisson 各组 r1，共 9 个会话。Heat 的 r2/r3 共 6 个会话移入同一 PDF 的附录，完整原始日志和关联重试保留。此为事后的统一展示规则，不按成绩挑选，不改变原 15 会话冻结计划。

**正文口径：9/9 有提交，8/9 正式成功，Poisson G2 计时无效。** 正文保留输出为 587,172 token，含旧失败的已知输出 616,777、charged 620,873。附录单列六个额外会话（309,038 输出 token）和完整批次统计，不混用分母。G2 的 2.488× 原始耗时比仍仅供诊断，不填正式成绩。

- [下载最新版 PDF（19 页，含附录）](https://github.com/bxf1/sciresearch-bench-lite/releases/download/v0.3-submission-20261024/sciresearch-thinking-r1-report-20261025.pdf)
- [下载离线 HTML](https://github.com/bxf1/sciresearch-bench-lite/releases/download/v0.3-submission-20261024/sciresearch-thinking-r1-report-20261025.html)
- [正文与附录证据索引](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/thinking-report-evidence-2026-10-25.md)
- [本版统计与交付核对](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/delivery-audit-thinking-r1-2026-10-25.md)

三张正文图、结果表、资源表、分析与端到端案例已按 r1 调整。正文案例使用 Heat G1 r1 a002，明确原 research_timeout、失败 parent 和无进展续接；原 Heat G1 r2 案例保留在附录 B。三任务基线及其计时拒绝保持原记录。

核验包含 77 个来源哈希、1,440 条保存的逐例评分记录、183 个本地链接、两组无交叉且合计 15 个会话、图表正文 run ID，以及源码快照和四段日志节选。干净副本核验、标准库表格重建与逐页排版检查通过。本次无模型调用、候选重跑或冻结参数变更。

源码提交：`d376b1731d50ac0f6f8ff8e9a639816aecf0addd`。新增独立附件 `thinking-r1-report-20261025.tar.gz`、manifest、SHA256SUMS 和 PDF/HTML。该增量包配合 main 与既有原始证据使用。全部既有 27 个附件保留，旧 PDF 不覆盖；原作者数据、完整实验、失败、重试及计时拒绝证据仍可下载。先前说明见 [release-before.json](https://github.com/bxf1/sciresearch-bench-lite/blob/main/logs/thinking-r1-report-delivery-2026-10-25/release-before.json)。历史标签的自动源码 ZIP 不是最新 main 报告。

正文每组仅一个 r1，不能据此判断稳定性或指导组普遍优劣；中途修复、旧隐藏集、供应商路由和计时干扰的限制继续披露。
