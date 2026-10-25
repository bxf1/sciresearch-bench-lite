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

旧代理固定关闭 thinking 并丢弃 output_config。本次扩展保留默认关闭模式，只有新冻结计划启用 max：每个实际出站请求强制 enabled/max，剔除无效 temperature，并继续约束预算、固定目的地与系统/工具哈希。允许 thinking/signature 流式块；用量减少、超额度或协议异常仍停止接收。

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

## 分析边界

这是看到旧结果后追加的匹配对照，thinking 与 max 同时改变，且 temperature 的语义随模式变化。沿用已经使用过的隐藏集、先后运行条件、单宿主及小样本限制因果解释。完成后分别报告有效提交、有效评分、reward、首次/最终变化、输出用量、墙钟和失败开销；缺失或无效值保持缺失。
