最终实验报告已按用户要求整理，科学结论以原 formal-003 批次为准。

- [最终实验报告](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/submission-report-2026-10-24.md)：三任务、90 个实例、11 种作者基线、15 次正式研究的逐会话结果、迭代、失败和局限。
- 15 次研究中，6 次 reward=1、8 次有效未成功（含 6 次正常无提交）、1 次 Poisson G2 计时无效；14/15 有效评分不等于成功率。
- [调研与逻辑图](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/survey.md)：ASI-Bench 与 Terminal-Bench-Science 的论文/实现及设计比较。
- 2026-10-24 23:09（Asia/Shanghai）按用户要求取消无结果的补跑。最新 Poisson G3 使用 155,939 输出 token，未公开评估或登记有效候选；其余五项未启动。重复循环诊断和取消记录独立保留，不计入正式科学分母。
- Poisson G2 的新空闲窗口未准入，没有新的有效计时；原无效值继续留空。后续研究与计时队列已取消，监控已删除。

新增附件 `final-report-20261024.tar.gz` 包含最终报告、原正式结果表和补跑取消证据；`final-report-manifest.json` 与 `final-report-integrity.json` 提供文件和归档 SHA256。该包是报告与证据补充，不是独立完整运行环境。

原有五个附件保留且不覆盖：`evidence.tar.gz`（formal-003 完整证据）、`file-manifest.json`、`integrity.json`、`author-data-v0.3.tar.gz`（90 例作者数据、QC、生成熵）及 `author-data-integrity.json`。作者数据不可挂载到研究 Agent；公开数据与执行时隔离是不同要求。历史归档内状态为生成当时记录，以最新报告为当前交付入口。
