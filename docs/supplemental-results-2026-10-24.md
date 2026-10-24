# 50 万输出 token 补充实验

本批次由用户在 2026-10-24 明确授权：仅补跑原 6 个无有效提交会话，并重测 Poisson G2 已有候选的计时。已成功的研究不重复，原结果不替换。算法、公开数据、科学阈值与资源不优化。

冻结计划为 [`supplemental-500k-2026-10-24.json`](../freezes/supplemental-500k-2026-10-24.json)。首个 Poisson G3 会话因前一 Codex 聊天的宿主控制器中断而失去桥接；保留为 infrastructure-invalid。遗留容器被清理，全部可观测模型用量及日志保留。恢复计划为 [`recovery-001`](../freezes/supplemental-500k-2026-10-24-recovery-001.json)，只为该中断会话建立关联新 attempt，其余五个会话设置不变。

每会话输出上限 500,000 token，包含原生压缩；没有研究墙钟、累计请求数或累计公开评估数上限。单请求和单候选保护仍保留。运行控制器使用独立进程，聊天断线不应再直接终止它。

**2026-10-24 22:19 已按用户恢复授权重启：接口返回 HTTP 200，recovery-003 控制器运行中，尚无新增有效科学成绩。** 实验按冻结顺序串行执行，以保留 4 CPU/4 GiB 研究资源与候选 worker 的容量。全部研究关闭后才启动补充隐藏重放。不得把未关闭会话写成成功、无提交零分或隐藏测试通过。

| 补跑会话 | 原结果 | 本批次状态 |
|---|---|---|
| Poisson G3 r1 | 无有效提交 | recovery-003 新尝试运行中；此前无效尝试保留 |
| Heat G3 r2 | 无有效提交 | 排队，等待前序会话关闭 |
| Heat G1 r2 | 无有效提交 | 排队，等待前序会话关闭 |
| Heat G3 r3 | 无有效提交 | 排队，等待前序会话关闭 |
| Heat G1 r3 | 无有效提交 | 排队，等待前序会话关闭 |
| Heat G2 r3 | 无有效提交 | 排队，等待前序会话关闭 |
| Poisson G2 r1 | 计时无效，已有候选 | 先前准入失败；六个研究关闭后重新申请窗口 |

选择性补跑及扩大的预算不构成独立等预算比较。沿用同一隐藏集，不作新分布泛化或预算改进因果结论。原正式批次的 15 个研究结果始终保留在[历史正式报告](formal-results-2026-10-23.md)。

## 关联恢复会话的 API 故障

Poisson G3 的恢复会话在 12:10:46（Asia/Shanghai）关闭：286 次已接受请求中 285 次成功、1 次 HTTP 402。已知成功输出 60,285 token，charged 为 64,381；差额 4,096 是失败请求的保守额度，不代表实测输出。500,000 token 尚未耗尽，研究墙钟截止未触发，没有公开评估、first 或 final。状态为 `research_invalid/api_failed`，不能记作科学零分。

可信桥接与资源清理无错误，所有运行容器已清理。批次控制器按故障策略停止，后续五个 Heat 会话未启动；排队的隐藏评分也在研究屏障处退出，没有将未完成研究冒充已完成。原始记录见[结束结果](../research-runs/supplemental-500k-2026-10-24-poisson-g3-r1-retry-001/result.json)和[恢复批次账本](../research-runs/supplemental-500k-2026-10-24-recovery-001/manifest.json)。

该次 API 故障后未连续重试；在用户确认恢复后，按下述新计划接续。补跑和旧结果分开保存；本次提交继续提供原正式批次已经完成的全部基线与端到端实验。

## Poisson G2 计时补测的前置检查

2026-10-24 晚间，在确认原 15 次研究全部关闭、模型补跑已停止且运行容器为 0 后，为已有 G2 候选建立独立的计时观察窗口。30 秒前置观察仍未通过：WeChat 多次超过既定 5% 单核 CPU 门槛，另有一个进程退出时以 `(AMPLibraryAgent)` 名称记录的 CPU 样本；没有 swap-out 或观察器错误。

该窗口在候选执行和隐藏评分前被拒绝，`hidden_scores_accessed=false`、模型调用数为 0；因此没有新的速度或分数，不能以该次准入记录替换原无效计时。未关闭用户应用，也未放宽阈值。详见[准入记录](../results/supplemental-2026-10-24/original-poisson-g2-timing-only/timing/acceptance.json)。需在宿主空闲时重新获得合格窗口。

21:13 的最小合成探测仍收到 HTTP 402，见[接口探测](../logs/submission-delivery-2026-10-24/api-probe-2114.json)。该次故障后的账户恢复和后续尝试见下一节。

## 账户恢复后的接续

用户确认“已处理，可恢复补跑”后，[最小合成探测](../logs/supplemental-2026-10-24/api-recovery-probe.json)返回 HTTP 200（输出 2 token，无研究数据）。[recovery-002](../freezes/supplemental-500k-2026-10-24-recovery-002.json)首次启动在本地 Docker relay 健康检查处超时，模型研究尚未开始；[失败结果](../research-runs/supplemental-500k-2026-10-24-poisson-g3-r1-retry-002/result.json)和资源清理记录保留。随后以完全相同的冻结 relay 代码和额度完成[健康预检](../logs/supplemental-2026-10-24/relay-preflight-002.json)，模型调用为 0，容器及网络均已清理。

当前采用关联的 [recovery-003](../freezes/supplemental-500k-2026-10-24-recovery-003.json)。只更换 Poisson 的 attempt、run、session 标识并链接前一失败；五个未启动 Heat 会话、66 个冻结源码文件、输入、方法提示、模型参数和预算均保持一致。Poisson 以新会话从原始公开任务重新开始，此前已消耗用量仍分别记账。

[独立控制器](../logs/supplemental-2026-10-24/recovery_003_controller.py)顺序执行六项研究，全部关闭且通过屏障后沿用原评分实现。新结果写入 `results/supplemental-2026-10-24-recovery-003/`，G2 的旧拒绝窗口不覆盖。新窗口仍要求 30 秒空闲预检和连续观察；若不合格会保留拒绝证据，不放宽阈值。控制器运行时抑制系统空闲睡眠，聊天结束后可继续，但电脑关机或进程异常仍会中断。

本机进度可用 `.venv/bin/python tools/supplemental_status.py` 查看；`--plan` 可查看指定历史冻结计划。进程状态位于 `logs/supplemental-2026-10-24/recovery-003-state.json`，研究和评分的实际结束结果优先于本报告的启动快照。
