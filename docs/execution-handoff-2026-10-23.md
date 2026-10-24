# SciResearch-Bench-Lite v0.3：执行收束与交付索引

2026-10-23（Asia/Shanghai）。原交接任务已执行并按用户“没研究出来的任务就正常关闭，无需过多重试”要求收束。**15 次研究全部关闭、11 种作者方法全部重放、15 个研究 first/final 操作全部执行。** 有效科学评分为 14/15、8/9 格；Poisson G2 因实际计时窗口不合格留空，完整 15/15 有效科学验收未达成，未追加重测。

## 当前状态

| 项目 | 结果 |
|---|---|
| 资源验收 | 原 15/15 通过；原 VM 身份保持，最终容器为 0 |
| T3 校准 | 原三组 216/216 检查通过；未复用旧时间窗口 |
| 冻结 | 第三版 `research-6615cd7900ba0750`，每会话 200,000 输出 token |
| 研究 | 15/15 有效关闭；9 有候选、6 无提交；另保留 4 个无效 attempt |
| 作者方法 | 11/11 完成，均有有效结果，科学零分保留 |
| 研究隐藏操作 | 15/15 已执行；14 有效、Poisson G2 计时无效 |
| 报告与归档 | [最终报告](formal-results-2026-10-23.md)、[审计](../logs/formal-execution-local-004/final-audit-001.json)、[本地归档](../logs/formal-execution-delivery-local-005/integrity.json) |
| 对外发布 | 本轮没有提交、推送或发布 |

## 读取入口与禁止重复执行

正式计划：[formal-003](../freezes/research-run-plan-formal-003.json)，SHA256 `47356b71b90acb1178dc86f94ec4f58041d933d00a67b4594cc0c697b568a033`。最终 ledger：[manifest](../research-runs/research-6615cd7900ba0750/manifest.json)，SHA256 `baf192d8ee63e29bcd0e7267928a38d5aa1c8b6af5b3fb35991b617bcd5b8008`。所有研究、隐藏和恢复控制器均已退出。不要重新运行启动或恢复脚本，不再增加研究 attempt；无提交和科学零分均保留。

[summary.json](../results/formal-study-003/summary.json)中的 `pending_run_ids` 只列出已测量但性能无效的 Poisson G2，不能误解为尚未执行。当前没有未启动的规定操作。按用户最新要求，本轮不再为其重测；如以后要开展新工作，应先明确新的授权和协议范围，不能改写原记录。

只读重建报告可使用新输出目录：

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study_report \
  --project . --plan freezes/research-run-plan-formal-003.json \
  --manifest research-runs/research-6615cd7900ba0750/manifest.json \
  --output results/formal-study-review-new
```

不要 reset、clean、重新生成数据/计划、覆盖既有输出或把当前未提交工作切回旧版本。报告重建不调用模型或求解器，但必须保留原哈希引用。

## 证据边界

heat/ODE 的作者及不同候选各三次独立重放；同会话同源码显式复用。Poisson 每个不同方法/检查点一个 BCCBBC 组，合计 7 组，其中 G2 的 2 组性能无效。93 个 W 批次、1,116 次实例执行全部留档，不能作为 1,116 个独立研究样本。

T3 窗口保留一个 LU 前置检查拒绝（当时未读隐藏成绩、未创建 attempt），随后 LU 首次正式测量通过；Poisson G2 实际测量遇到 VPN CPU 峰值，留空且不重测。所有窗口与旧版本失败证据均保留。

[无提交诊断](submission-diagnosis-2026-10-23.md)区分反复相同计算、持续不同随机模拟、源码目录拒绝及 API/基础设施故障。冻结期间未修改提示或替模型完成提交。金额未知，失败占用不冒充实际 token，成本按版本分开。

[本地证据包](../logs/formal-execution-delivery-local-005/evidence.tar.gz)含源码、候选、结果、清单、逐例表与诊断；私有数值数组继续留在 `authoring/data/v0.3-local` 并由冻结哈希绑定，不包含在包中。宿主依赖、Docker 镜像和数据都仍是完整复现所需条件。原 8 个其他服务容器按已有授权保持停止，数据卷未删除。

原交接文字与历史执行步骤保留于[整理前快照](../logs/formal-execution-local-004/docs-before-final/docs/execution-handoff-2026-10-23.md)，版本修订见[原生压缩修复](compaction-freeze-2026-10-23.md)与[20 万预算冻结](budget-freeze-2026-10-23.md)。这些历史启动命令不是当前待办。
