完整交付：科学计算 Auto Research Benchmark，三任务、90 个实例、11 种作者基线、15 次原正式研究。

- 提交报告：docs/submission-report-2026-10-24.md
- 调研及 ASI-Bench / Terminal-Bench-Science 逻辑框图：docs/survey.md
- 原正式评分有效 14/15；其中包括无提交零分，Poisson G2 无有效计时。
- 50 万输出 token 选择性补跑：首个恢复会话因 HTTP 402 中止，后续五次未启动；G2 新计时前置窗口未准入。没有虚构新增成绩。
- evidence.tar.gz：原 formal-003 完整证据，9,252 文件，SHA256 见 integrity.json。
- author-data-v0.3.tar.gz：90 例作者数据、QC 和生成熵；只能供作者/可信评分器使用，不可挂载到研究 Agent。
- file-manifest.json / integrity.json / author-data-integrity.json：文件及压缩包完整性记录。

历史证据包内 local_only 表示生成时状态；本次按用户明确授权公开发布，原归档字节未改变。无供应商凭据或短期会话令牌。
