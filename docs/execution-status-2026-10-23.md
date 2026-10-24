# 第三版执行已收束：15 次研究，1 项计时无效

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
