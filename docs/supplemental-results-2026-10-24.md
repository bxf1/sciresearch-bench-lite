# 补跑取消与诊断记录

**2026-10-24 23:09（Asia/Shanghai），用户要求停止没有结果的补跑，直接整理之前的实验报告。当前补充批次已关闭，不再运行或排队；最终科学结果以原正式批次为准。**

| 补跑会话 | 收束状态 | 已知输出 token | 公开评估 / 有效候选 |
|---|---|---:|---|
| Poisson G3 r1，最新关联尝试 | 用户主动终止，非预算正常完成 | 155,939 | 0 / 0 |
| Heat G3 r2 | 未启动即取消 | 0 | 未执行 |
| Heat G1 r2 | 未启动即取消 | 0 | 未执行 |
| Heat G3 r3 | 未启动即取消 | 0 | 未执行 |
| Heat G1 r3 | 未启动即取消 | 0 | 未执行 |
| Heat G2 r3 | 未启动即取消 | 0 | 未执行 |
| 原 Poisson G2 计时补测 | 先前空闲准入失败；后续取消 | 无模型调用 | 无有效新计时 |

Poisson 最新尝试的 652 次请求全部成功，代理 charged 与已知输出均为 155,939；500,000 上限尚未用尽，研究总墙钟没有截止。运行层记录 `research_invalid / cancelled`，registry 已关闭，first/final 均为空。作者层记录为 `cancelled_by_user`；不把提前取消算成新的科学零分，不给未启动项目赋零分。

已核实控制器退出，研究容器、sidecar 和专用 relay 网络全部清理，清理错误为 0；定期检查已删除。补跑隐藏重放未执行。原 15 次研究、11 种作者基线和先前全部失败记录均保留。

证据：[取消请求](../logs/supplemental-2026-10-24/user-stop-request.json)、[取消确认与六项状态](../logs/supplemental-2026-10-24/user-stop-confirmation.json)、[最新尝试结束结果](../research-runs/supplemental-500k-2026-10-24-poisson-g3-r1-retry-003/result.json)、[最终交付汇总](../results/submission-2026-10-24/final-summary.json)。

## 重复循环的实证

对已关闭的原生 session 日志，按 assistant 的每个 `toolCall` 计数一次；以工具名和完整 JSON 参数做精确匹配，不进行文件名或代码语义归一化。

- 共 648 次工具调用、648 个不同调用 ID，只有 66 种工具及参数组合。
- 三个诊断命令分别重复 424、107、53 次，合计 584 次，占所有工具调用约 90.1%。
- 最长连续重复为 236 次；终止前的最后 107 次也逐字相同。
- 重复块的工具结果各只有一个内容哈希，且没有工具错误；不同调用 ID 与上游响应 ID 支持这些是重新发起的调用，不是日志重复打印。
- 模型写过 `solve.py` 并进行过自测，但 `bench evaluate` 和 `bench finalize` 调用均为 0。

主要重复内容是构造多重网格层级后反复打印层级信息、函数常量及变量名；末尾持续打印相同的四层结构。没有进入可信候选登记，所以没有公开评估和有效提交。接口 HTTP 200 与工具成功只能说明调用链存活，不能说明研究持续取得进展。该诊断不确定模型、供应商或 SDK 内部为何出现循环，也不将尚未调用的提交桥判为故障。

完整命令、时间、原生日志行号、调用与响应去重计数及文件 SHA256 见[重复审计](../logs/supplemental-2026-10-24/repetition-audit-final.json)。冻结源码、提示、阈值和预算在诊断及停止过程中未更改，未向模型注入纠正指导。

## 尝试历史与计时边界

1. [原补跑计划](../freezes/supplemental-500k-2026-10-24.json)的首个 Poisson 会话因宿主控制器中断保留为基础设施无效，日志及用量保留。
2. [recovery-001](../freezes/supplemental-500k-2026-10-24-recovery-001.json)在供应商 HTTP 402 后停止：285 次请求成功、1 次失败；已知输出 60,285，charged 64,381，差额 4,096 是失败请求保守额度。
3. 用户处理账户后，[最小探测](../logs/supplemental-2026-10-24/api-recovery-probe.json)返回 HTTP 200。[recovery-002](../freezes/supplemental-500k-2026-10-24-recovery-002.json)在 relay 健康检查处超时，尚未调用研究模型；后续[零模型调用预检](../logs/supplemental-2026-10-24/relay-preflight-002.json)通过并完成清理。
4. [recovery-003](../freezes/supplemental-500k-2026-10-24-recovery-003.json)沿用完全相同的研究设置，最新 Poisson 会话出现上述重复，最终由用户终止。五个 Heat 会话未启动。

Poisson G2 曾独立尝试 30 秒主机空闲预检，因 WeChat 等后台进程超过原定 CPU 门槛被拒绝；在候选执行和隐藏评分前停止，`hidden_scores_accessed=false`。原无效计时不覆盖，阈值不放宽，也未停止用户应用。见[计时准入记录](../results/supplemental-2026-10-24/original-poisson-g2-timing-only/timing/acceptance.json)。本次取消后没有再开启新窗口。

这批选择性、提前终止的补跑不构成完整的 50 万 token 实验，也不进入原正式比较。最终报告见[最终实验报告](submission-report-2026-10-24.md)，原始正式证据见[历史正式结果](formal-results-2026-10-23.md)。
