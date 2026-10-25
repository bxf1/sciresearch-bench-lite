## 最终作业报告：thinking/max 专版（2026-10-25）

[当前主报告](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/submission-report-2026-10-24.md)已按作业要求复核；主报告、README、表格、图表、作者基线和端到端案例只展示 thinking/max 本批结果。解释 G1/G2/G3 与 r1/r2/r3，按任务、指导组、repeat 排序，并保留实际执行序号。

**结果：15/15 有提交，14 项正式有效且成功，Poisson G2 正式计时无效。** G2 数值通过 12/12，独立补测原始耗时比 2.488× 仅作诊断，不换算成绩。作者基线 10 项有效、Jacobi-CG 独立准入拒绝，三条任务均有基线与端到端验证。修复、关联重试和无进展续接完整保留。

- [下载 16 页 PDF](https://github.com/bxf1/sciresearch-bench-lite/releases/download/v0.3-submission-20261024/sciresearch-thinking-report-20261025.pdf)
- [下载离线 HTML](https://github.com/bxf1/sciresearch-bench-lite/releases/download/v0.3-submission-20261024/sciresearch-thinking-report-20261025.html)
- [15 行原始证据索引](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/thinking-report-evidence-2026-10-25.md)
- [作业要求检查与修正清单](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/delivery-audit-thinking-2026-10-25.md)
- [上一版材料暂存](https://github.com/bxf1/sciresearch-bench-lite/tree/main/archives/pre-thinking-only-20261025)：21 个文件与逐文件 SHA256，含上版报告、PDF、图表、分析和生成脚本。

本次审计核对 77 个来源哈希、1,440 条保存的逐例评分记录、178 个本地链接和全部图表/日志节选；这些是已有重复记录的复核，不是新增实验。干净副本验证与数据表重建通过，无模型调用、无候选执行、未改冻结参数。

报告源码提交：`1c8b452c6ea7c29c655cbda2f4f999fc15c7f575`。新增 `thinking-only-report-20261025.tar.gz`、同名 manifest 与 SHA256SUMS，另提供 PDF/HTML。增量包包含当前报告、图表、机器可读数据、审计脚本和上一版快照；与 main、作者数据及既有实验附件配合使用。

全部既有 22 个附件保留，包含作者数据、完整原始实验、thinking 轨迹、修复、失败和计时拒绝。先前发布说明保存在 [release-before.json](https://github.com/bxf1/sciresearch-bench-lite/blob/main/logs/thinking-report-delivery-2026-10-25/release-before.json)。历史标签的自动源码 ZIP 不是当前 main 报告版本；旧阅读附件属于历史快照。

局限：小样本、已使用过的隐藏集、模型路由内部版本不可锁定、中途执行器修复和宿主计时干扰；本版不宣称 thinking 的因果收益或真正 RSI。
