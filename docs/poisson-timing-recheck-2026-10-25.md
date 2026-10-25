# Poisson G1/G2 独立计时补测（2026-10-25）

用户在首次对照发布后授权重放 Poisson G1/G2 已有候选，保留原拒绝记录，不重跑 Agent、不改冻结参数。此次两个评分操作均已结束：**G1 获得有效成绩，G2 再次因宿主干扰无效**。本轮并未补齐 G2 的有效计时。

| 会话 | 首次候选 | 最终候选 | 最终分数 / reward | 正式加速比 |
|---|---|---|---|---|
| Poisson G1 r1 | candidate-001：64.342487 分 | candidate-003 | **68.376175 / 1** | **4.144750×** |
| Poisson G2 r1 | candidate-001 | 同首次源码，显式复用 | **null / null** | **null** |

G1 的首次加速比为 3.811277×；首次与最终各执行一组完整 BCCBBC，即固定 Jacobi 基线与候选交错运行，各三批，每批 12 个 final-test 实例。G1 最终候选三个批次均数值正确，正式效率门槛仍为 1.5×，基线 max/min 时间比为 1.017704、候选为 1.041427。首次→最终提高约 4.034 分。G2 首次与最终源码相同，只执行一组 BCCBBC，复用标记不增加样本数。

## 原始拒绝、新窗口和准入规则

原 16:40 批次中，G1 在评分前被拒绝，G2 的测量受 node 活动和 swap-out 干扰；原账本、候选、结果及拒绝 JSON 均原样保留。冻结控制器的内置 retry 只适用于 baseline_unstable，而本次为用户新授权的独立宿主环境补测，因此未把旧原因改写成 baseline_unstable，也未修改冻结控制器来放行旧结果。

新控制器在测量前声明：每项至多检查三个新 30 秒准入窗口；未通过准入时不读隐藏测试；每项只有一次获准后的完整 first/final 测量，不按分数择优或连续重测。使用原 revision-3 Observer、每 2 秒采样、无新 swap-out、无超过 5% 单核占用的无关进程，以及原热状态、缓存策略、镜像、资源、评分与数据。没有停止或修改用户的 VPN/微信进程，没有放宽阈值。

| 窗口（北京时间） | 是否执行隐藏评分 | 结果与证据 |
|---|---|---|
| G1 window-001，18:34:11 关闭 | 否 | VPN 两进程约 5.35% / 7.78%，[前置拒绝](../logs/poisson-timing-recheck-2026-10-25/g1-window-001/acceptance.json) |
| G1 window-002，18:35:11 关闭 | 是 | 全窗口无违规、无观察错误、容器清理通过，[正式通过](../logs/poisson-timing-recheck-2026-10-25/g1-window-002/acceptance.json) |
| G2 window-001，18:35:42 关闭 | 否 | VPN 约 8.75% / 11.18%，微信约 6.32%，[前置拒绝](../logs/poisson-timing-recheck-2026-10-25/g2-window-001/acceptance.json) |
| G2 window-002，18:36:28 关闭 | 是 | iKuuuVPNCore 约 5.423% > 5%，[测量窗口拒绝](../logs/poisson-timing-recheck-2026-10-25/g2-window-002/acceptance.json) |

G2 的最终拒绝片段如下，字段摘自原始 acceptance；swap-in 仅记录为诊断，真正触发拒绝的是进程 CPU 阈值，不是这里的 35 页 swap-in：

```json
{"status":"rejected","evaluation_status":"invalid","issues":["unrelated_active_process"],"core_percent":5.423065670712305,"swap":{"Swapins":35,"Swapouts":0},"model_calls":0,"research_launches":0}
```

G1/G2 的完整 [operation-result](../logs/poisson-timing-recheck-2026-10-25/g1-window-002/operation-result.json)、[G2 无效 operation-result](../logs/poisson-timing-recheck-2026-10-25/g2-window-002/operation-result.json)、逐批 W/J 产物、原始区间、正式资格和宿主观察均归档；不能把 G2 无效计时或其诊断值当成正式分数。完整产物见 Release 独立命名的 `poisson-timing-recheck-20261025.tar.gz`，原对照及正式证据附件保留。

## 更新后的汇总与限制

采用 G1 本次有效观察后，15 个原研究会话仍为 **15 个独立样本、17 个研究 attempt**，有提交 15/15，有效最终成绩 **14/15，14 项 reward=1**，G2 保持 null。与原 formal-003 的 14 对可比较最终分数为 12 升、2 降；其中 6 项提升仍来自原无提交。首次→最终为 5 升、4 降、5 同源码、1 项不可比较。作者基线仍为 10 项有效、Jacobi 准入拒绝，本次没有补测作者方法。

原首次发布的 [13 项有效汇总](../results/thinking-control-2026-10-25/reviewed-comparison.json)不改写；当前合并视图为 [reviewed-results.json](../results/poisson-timing-recheck-2026-10-25/reviewed-results.json)，由 [analyze_poisson_timing_recheck.py](../tools/analyze_poisson_timing_recheck.py)从原始证据重建。它保留每项原结果、父拒绝记录、每个新窗口及来源 SHA256。

本轮 **0 模型调用、0 Agent 启动**，研究输出用量仍为全部 attempt 已知 925,815、charged 929,911。原 8,851 个文件哈希一致，原计划 SHA256 仍为 `25c3250f8615aa5a90a24206964533085b5448f06910f7e42a969e2f66763f0e`。[授权与预声明](../logs/poisson-timing-recheck-2026-10-25/authorization.json)、[完成与保全检查](../logs/poisson-timing-recheck-2026-10-25/completion.json)可追溯。

这是原结果发布后的新计时观察，不是新研究样本，也不是将旧拒绝窗口追认为有效。G1 的跨批次分差同时包含宿主时间窗口变化，不能单独归因于模型模式或算法。thinking/max 事后匹配、旧隐藏集、中途执行器修复等原有限制继续适用。G2 要取得有效计时，需要先消除 VPN 活跃负载，再获准开启新的明确记录的窗口；本次未循环重测到通过。
