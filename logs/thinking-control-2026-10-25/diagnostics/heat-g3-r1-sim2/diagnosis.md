# Heat G3 r1：sim2.py 死循环诊断

核对时间：2026-10-25 11:54（北京时间）。仅使用公开输入、研究脚本快照、进程采样及执行日志；未读取隐藏评分。

## 结论与证据

研究 Agent 于 11:36:14 执行 `cd /workspace && python sim2.py > sim2_out.txt 2>&1; cat sim2_out.txt`，自行指定工具超时 900 秒。脚本用 32 个正弦基函数和自生成的合成数据比较 Heat 反演估计方法。

`sim2.py` 第 54–59 行的 `constrained()` 求根循环存在不可终止分支：当初始 `f(0)<0` 且 `f(lo/2)<0` 时，`hi=mid` 将负数边界不断移向 0，`f(mid)` 始终为负，不能触发 `break`。浮点数最终固定为负零，循环仍继续。

用原随机种子 2024 和公开输入做有界复现，在完成前 600 次 mean 方法随机抽样后，con 方法首个公开 case 的第 4 个合成样本触发该分支。`f(0)=-0.008901450630764085`，首个中点 `f=-0.003267030757015732`；64 次有界迭代后仍为负，继续二分会固定于负零。详细数值见 `diagnosis.json`，有界诊断程序见 `bounded_diagnosis.py`。

现场 Python 持续占用约一个 CPU 核；两次采样间 CPU 时间继续增长，但 I/O 计数和 124 字节输出的 SHA256 均不变。输出停在已完成的第一组 mean 方法汇总。该判断依据源码、有界复现及现场证据，不是仅凭 CPU 使用率，也未通过调试器读取运行时栈。

## 随后退出的直接原因

- 11:51:14：原生工具记录 `Command timed out after 900 seconds`，原工具超时结束本次命令。
- 紧接着下一次模型请求返回 HTTP 200，但 relay 检测到输入用量字段从 268 降至 140，记录 `protocol_error / usage_decreased` 并关闭会话。
- 此 attempt 被既有机制登记为 `infrastructure_failed`，控制器随后停止，容器清理完成。不能把它记为正常研究完成或科学零分。
- 本会话公开评估 0、first/final 候选均无。已知输出 25,070 token；失败请求保守扣减 4,096 后，记账额度共 29,166。
- 全批次当前为 1 个正常关闭并登记候选（Heat G2 r1）、1 个基础设施无效、13 个尚未启动；未执行隐藏评分。

冻结计划、运行中研究脚本、额度和提示均未修改；未向研究 Agent 反馈诊断，未人工发送终止信号，未重跑任何会话。只在本诊断目录保存了公开证据快照及独立有界诊断。基础设施恢复仍需另行核对协议错误，并保留原 attempt。

证据路径（相对 benchmark 根目录）：

- `research-runs/research-98719c3c1cf3fc92-heat-g3-r1/auxiliary-agent/pi/sessions/2026-10-25T03-32-50-423Z_01a1711e-4077-76ca-b22d-4d67afe5ef85.jsonl`
- `research-runs/research-98719c3c1cf3fc92-heat-g3-r1/relay-evidence/evidence/events.jsonl`
- `research-runs/research-98719c3c1cf3fc92-heat-g3-r1/result.json`
- `logs/thinking-control-2026-10-25/controller.stdout.log`
