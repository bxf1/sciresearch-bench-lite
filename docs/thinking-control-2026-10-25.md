# Thinking/max：15 会话匹配对照

2026-10-25（Asia/Shanghai）。本批已授权并冻结，实验进行中；尚无完整对照结论。原 formal-003 的 15 次结果保持原记录，不用新结果替换旧失败。

## 研究问题与条件

在相同任务、提示、数据、顺序、资源和累计输出额度下，启用 thinking 并将 effort 设为 max 后，提交率、隐藏科学成绩、first→final 变化与成本如何变化？

| 参数 | 原 formal-003 | 新对照 |
|---|---|---|
| 模型路由 / 公开版本 | deepseek-flash / DeepSeek-V4.1-Flash-1017 | 相同；重新核对公开映射 |
| thinking | disabled | enabled |
| output_config.effort | 未设置 | max |
| temperature | 0 | 不支持，省略并记录 null |
| top_p | 1.0 | 1.0 |
| 每会话累计输出 | 200,000 token | 200,000 token，包含 thinking 和原生压缩 |
| 每请求输出上限 | 4,096 token | 相同 |
| 研究上限 | 1,800 秒 / 20 次公开评估 | 相同，任一预算先到则停止 |
| 会话矩阵 | Heat 每组 3 次；ODE/Poisson 每组 1 次 | 相同 15 格，新会话与空白工作区 |
| 数据、提示、独立评分、容器资源 | 原冻结 | 相同；不反馈旧答案或隐藏分数 |

新计划：[`research-98719c3c1cf3fc92`](../freezes/research-run-plan-thinking-max-2026-10-25.json)。原计划：[`research-6615cd7900ba0750`](../freezes/research-run-plan-formal-003.json)。新旧结果按 task/group/repeat 配对；不合并为 30 次同条件样本。

DeepSeek 的 [thinking 文档](https://api-docs.deepseek.com/guides/thinking_mode/)说明 Anthropic 格式使用 `thinking.type=enabled` 和 `output_config.effort=max`，且 thinking 模式下 temperature 不生效。[兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)指出 `budget_tokens` 被忽略，因此使用可信代理对完整输出 usage 计量，不能用该字段代替 20 万累计预算。

## 参数实际生效的证据

旧代理固定关闭 thinking 并丢弃 output_config。本次扩展保留默认关闭模式，只有新冻结计划启用 max：每个实际出站请求强制 enabled/max，剔除无效 temperature，并继续约束预算、固定目的地与系统/工具哈希。允许 thinking/signature 流式块；输出用量减少、超额度或协议异常仍停止接收。输入/缓存用量修正的后续兼容性修复见下节。

原生 Pi 的客户端默认保持不变，实际 API 条件由可信代理强制设置。不能只看客户端的 `reasoning_effort=off` 判断服务器请求；每次请求的可信事件另存 `effective_thinking` 与 `effective_output_config`。

- [363 项完整测试](../logs/thinking-control-2026-10-25/unit-tests-final.txt)通过，包含原关闭模式兼容、thinking 流、总额度耗尽和错误 effort 拒绝。
- [真实计数题探测](../logs/thinking-control-2026-10-25/live-reasoning-roundtrip/result.json)产生 769 字符非空 thinking；后续工具请求保留思考块，两个请求输出共 359 token，正常得到最终回答。
- [真实初始/增量压缩探测](../logs/thinking-control-2026-10-25/live-smoke-result.json)通过，实际请求使用 enabled/max；这些探测只用合成对话，不计入 15 次科学研究。
- [冻结验收](../logs/thinking-control-2026-10-25/validation.json)核对全部 15 个会话配置；[变更影响](../logs/thinking-control-2026-10-25/revision-impact.json)证明数值、公共诊断及任务包未改变。

上述证据确认出站参数和返回思考内容，不能独立测量供应商内部实际投入的推理计算量。

## 执行与评分

控制器串行执行研究，全部 15 会话关闭后才运行隐藏评分与作者基线。Heat/ODE 独立重放三次；Poisson 仍需新的连续宿主观察和 BCCBBC 配对测量，计时准入失败保留为无效，不用零分替代。

查看进度（不访问隐藏数据或凭据）：

```bash
.venv/bin/python logs/thinking-control-2026-10-25/status.py
```

状态与进程位于 `logs/thinking-control-2026-10-25/`，最终结果目标为 `results/thinking-control-2026-10-25/`。控制器退出、HTTP 错误或停滞需独立核查；正常无提交与科学失败不重跑。研究期间不调整冻结设置或向 Agent 追加指导。

## 2026-10-25 relay 故障与关联重试

Heat G3 r1 的 `a001` 在自行编写的 `sim2.py` 中触发不可终止的求根循环，随后由 Agent 原先设置的 900 秒工具超时结束命令。下一次模型请求返回 HTTP 200，但输入用量从 268 修正为 140，旧 relay 将所有用量字段都按递增累计量校验，因此以 `usage_decreased` 拒绝该流。attempt 被登记为 `infrastructure_failed`，没有公开评估或候选。已知输出为 25,070 token，计入失败请求的保守扣减后为 29,166；这些失败开销必须保留在对照报告中。

用户明确授权修复 relay、保留失败记录、以新 attempt 重试并继续剩余实验。修复仅将输入/缓存字段改为保留最新合法值，并在 `input_usage_revisions` 记录下调次数和前后计数；输出 token 仍需单调递增且不超过预留量，流不完整或违规仍全额扣除本次预留量。输入字段不参与输出预算退款。原失败事件没有被重新解释为成功。

原冻结计划文件及 SHA256 `25c3250f8615aa5a90a24206964533085b5448f06910f7e42a969e2f66763f0e` 保持不变。[基础设施修复附录](../freezes/research-98719c3c1cf3fc92-relay-usage-repair.json)绑定原计划、源码修复前后哈希、授权、补丁及验收证据，只准入 `runner/model_relay.py` 和支持该附录校验的 `runner/run_plan.py`。其余工具源码、数据、提示、顺序、评分、资源和预算继续按原冻结检查。

- [完整回归测试](../logs/thinking-control-2026-10-25/recovery-001/unit-tests.txt)：369 项通过，2 项既有弃用警告；覆盖输入修正、非法计数、输出倒退、不完整流、共享预算和附录边界。
- [真实合成探测](../logs/thinking-control-2026-10-25/recovery-001/live-probe/result.json)：2 个 enabled/max 请求、508 输出 token，非空 thinking 和工具续接通过。该探测不计入科研结果；故障中的 268→140 变化另由离线回归用例覆盖，未声称重放了原完整网络流。
- [配置与证据验证](../logs/thinking-control-2026-10-25/recovery-001/validation.json)：15 个配置通过；重试只改变 attempt、父 attempt 和会话 ID；原失败相关 101 个文件及记录哈希保持一致。
- [恢复控制器模拟](../logs/thinking-control-2026-10-25/recovery-001/controller-simulation.json)：确认关联重试后按序继续、失败时停止、已完成 attempt 不重跑；没有调用模型或隐藏评分。

12:05（北京时间）已启动 `research-98719c3c1cf3fc92-heat-g3-r1-a002`，父 attempt 为 `...-a001`，使用新的空白研究工作区。此前脚本的诊断没有反馈给研究 Agent。Heat G2 r1 的已完成结果保留，之后依原顺序执行其余 13 个会话。当前控制器为 `controller-recovery-001.py`，当前进程记录和输出在 `logs/thinking-control-2026-10-25/recovery-001/`；旧控制器、启动记录和失败证据均保留。全部研究关闭前仍不执行隐藏评分。

报告须注明执行期间发生过基础设施修复；不能把原失败与重试作为两个独立科学样本，也不能省略此前死循环这一研究行为。

## 分析边界

这是看到旧结果后追加的匹配对照，thinking 与 max 同时改变，且 temperature 的语义随模式变化。沿用已经使用过的隐藏集、先后运行条件、单宿主及小样本限制因果解释。完成后分别报告有效提交、有效评分、reward、首次/最终变化、输出用量、墙钟和失败开销；缺失或无效值保持缺失。
