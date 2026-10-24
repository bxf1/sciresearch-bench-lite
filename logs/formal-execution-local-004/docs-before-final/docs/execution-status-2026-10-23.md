# 第三版执行进度：研究 15/15，正在执行隐藏重放

全部 15 次研究已有效关闭：9 次有 first/final，6 次无有效提交；另保留 4 个无效 attempt。19 个 attempt 的清理、原 VM 身份、冻结源码及完整关闭门槛均通过核验。用户最新指令后新增关联重试为 0，见[隐藏阶段启动核验](../logs/formal-execution-local-004/hidden-preflight-001.json)。当前运行 `hidden_sequence.py`，日志为 `hidden-sequence-001.stdout.txt`；研究控制器已退出，不能再次启动。

以下为研究执行历史：

heat G1 r2 在约 1,536 秒时耗尽 200,000 输出 token，543 次请求全部成功，无评估、无 first/final，清理通过，保留正常无提交结果。第 12 项 heat G2 r2 随后正常超时关闭，1 次有效公开评估，first/final 均为 `candidate-001`，由 `deadline_fallback` 选取；732 次请求全部成功、输出 196,613 token，清理通过。第 13 项 heat G3 r3 随后以墙钟预算到达正常关闭，742 次请求全部成功、输出恰为 200,000 token，无评估、无有效提交，清理通过。第 14 项 heat G1 r3 随后在约 1,109 秒用满 200,000 输出 token，240 次请求全部成功，无评估、无有效提交，清理通过。当前为最后一项 heat G2 r3。

当前调度器为 `logs/formal-execution-local-004/retry_heat_g3_r2_transport.py`，heat G3 r2 a002 已有效关闭，由其启动的 `research_sequence.py` 正在继续剩余顺序，日志为 `research-sequence-005.stdout.txt`。旧恢复控制器已退出，不能重复启动。

用户最新要求“没研究出来的任务就正常关闭，无需过多重试”。从该指令起，不新增自动重试；无有效候选的正常预算结束保留为科学失败，真实 API/基础设施失败继续保留其分类，不改成有效科学结果。见[执行策略记录](../logs/formal-execution-local-004/retry-policy-user-update-001.json)。

heat G3 r2 a002 在约 1,792 秒时耗尽 200,000 输出 token，734 次请求全部成功、无公开评估、无 first/final，以 `research_timeout/no_valid_submission` 有效关闭，全部资源清理通过。这次关联重试在用户最新指令前已启动，之后不会为其无提交结果再跑。

heat G3 r2 a001 在末段出现两次上游传输失败，控制器按 `research_invalid/api_failed` 关闭。659 次成功请求输出 194,606 token，失败请求保守占用 5,394 token，charged 因而达到 200,000；失败请求真实用量未知，不能把 charged 当作实际输出。两次失败均无 HTTP 状态，底层异常类型未被旧处理器保留。容器和网络清理通过，一次只回复 OK 的恢复探测完整返回 HTTP 200 后，按原协议进行了关联重试。[调查验收](../logs/formal-execution-local-004/heat-g3-r2-transport-investigation/retry-acceptance.json)保存全部关系与哈希。

当前计划是 [research-run-plan-formal-003.json](../freezes/research-run-plan-formal-003.json)，每会话累计输出上限已提高至 **200,000 token**，单请求 4,096、研究 1,800 秒、20 次公开评估不变。预算修订、357 项测试和冻结归档见[第三版说明](budget-freeze-2026-10-23.md)。

ODE G1 a003 已正常完成：3 次公开评估，first/final 均为 `candidate-003`，83 次 API 请求全部成功，累计输出 185,235 token，清理通过。ODE G2 随后正常完成，4 次公开评估产物均有效，first/final 均为 `candidate-001`，364 次 API 请求全部成功，累计输出 158,843 token，清理通过。ODE G3 达到 1,800 秒时限后有效关闭：7 次公开评估、1 个产物有效候选，first/final 均为 `candidate-007`，final 按 `deadline_fallback` 选取。828 次请求成功，成功输出 141,704 token；截止时间断开 1 个在途请求，保守占用 4,096 token，不能视为实际用量。Poisson G3 随后正常超时关闭，3 次提交均在源码导出阶段失败，无有效 first/final；713 次请求成功，成功输出 177,200 token，截止时间断开 1 次在途请求（保守占用 4,096 token），清理通过。Poisson G2 已正常完成，8 次公开评估、6 个产物有效候选，first=`candidate-003`、显式 final=`candidate-007`，276 次请求全部成功、输出 154,918 token，清理通过。Poisson G1 a001 首个响应出现 `input_tokens: 434 → 306`，触发冻结用量守卫，已保留为基础设施失败；完整清理和冻结复核后，a002 已关联 a001 启动。a002 已正常完成：7 次公开评估、3 个产物有效候选，first=`candidate-005`、显式 final=`candidate-007`，158 次请求全部成功，输出 36,503 token，清理通过。当时恢复控制器为 `logs/formal-execution-local-004/retry_poisson_g1_usage.py`，随后进入剩余 heat 重复会话；前三个 heat 会话同样正常完成并保留有效提交：

| 组别 | 公开评估次数 | first | final | 成功输出 token | API 失败 |
|---|---:|---|---|---:|---:|
| G2 r1 | 7 | candidate-004 | candidate-007 | 122,638 | 0 |
| G3 r1 | 18 | candidate-017 | candidate-018 | 76,374 | 0 |
| G1 r1 | 4 | candidate-004 | candidate-004 | 74,313 | 0 |

这些是研究关闭与候选登记结果，**不是隐藏科学成绩**。全部 15 个研究会话有效关闭后，才执行 11 种作者方法以及研究 first/final 隐藏重放。目前隐藏成绩、组间科学比较和最终交付均未完成。自动进度报告中的 `scientific_sessions=0` 指尚未完成隐藏重放，是该报告检查点的口径，不能用作当前研究完成数。

## 已恢复执行与保留的 ODE 失败记录

用户已明确回复“已处理，继续原计划”。新的[合成恢复探测](../logs/formal-execution-local-004/api-recovery-001/synthetic-probe.json)返回 HTTP 200，完整结束且仅输出 1 token。冻结校验、VM 身份、资源和容器清理复核通过后，已启动 a003，父记录为 a002；[重试验收](../logs/formal-execution-local-004/api-recovery-001/retry-acceptance.json)绑定恢复探测及父记录哈希。当时控制器为 `logs/formal-execution-local-004/retry_ode_g1_api_recovered.py`，a003 已有效关闭后继续既定顺序；该旧控制器现已退出。启动前先检查 ledger 与进程，不能重复执行下方恢复命令。

ODE G1 a001 受 09:33:36–10:03:37 的宿主合盖睡眠干扰，已通过现有路径取消并保留为 `research_invalid/cancelled`。确认清理与 VM 身份后进行了关联重试 a002。

a002 在 253 次成功请求后遇到第 254 次请求 HTTP 402，记录为 `research_invalid/api_failed`，没有公开评估。成功请求的输出合计 69,828 token；失败请求被代理保守占用 4,096 token，因此 charged 为 73,924，这不代表实际计费 token。容器和网络清理均完成，调度器已退出。

[DeepSeek 官方错误码](https://api-docs.deepseek.com/quick_start/error_codes/)将 402 定义为余额不足。随后只读余额接口返回 `is_available=true`，但一次只要求回答 OK 的合成 Messages 探测仍返回 402。当时只能确认模型接口不可用，不能仅凭余额可用标志继续正式重试；因此暂停并请用户处理账户。该阻塞现已由用户确认及恢复探测解除。详见[调查记录](../logs/formal-execution-local-004/ode-g1-api-402-investigation/investigation.json)。

## 恢复操作记录（a003 已完成，不要重复执行）

账户问题处理后，先用极小合成请求确认 Messages API 已恢复，再核对 VM、容器清理及冻结校验。接着按当前最新失败父记录创建新 attempt：

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study start \
  --plan freezes/research-run-plan-formal-003.json \
  --run-id research-6615cd7900ba0750-ode-g1-r1 \
  --retry-of research-6615cd7900ba0750-ode-g1-r1-a002
```

它会创建 a003；不能复用 a001/a002 的会话或工作目录。新 attempt 有效关闭后，再继续 `logs/formal-execution-local-004/research_sequence.py` 中的原冻结顺序。前三个已完成研究不得重跑。首次恢复调度要使用新的 stdout 文件名，保留既有日志。后续运行请保持电脑开盖与稳定供电。

API 恢复前的检查点机器可读状态见 [execution-status.json](../results/formal-study-progress-003/execution-status.json)，逐 attempt 和公开评估见[进度报告目录](../results/formal-study-progress-003)。第三版正式 attempt 已知成功输出合计 345,874 token；所有金额仍为 null，先前版本、失败占用与合成探测需分别统计。原始失败与候选均保留，本次未对外发布。
