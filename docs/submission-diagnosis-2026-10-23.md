# 第二版正式研究的提交诊断

检查范围为第二版计划 `research-0301cbdf4d96c055` 的前三个 heat 会话。只读取已经结束的 public-dev 会话与可信代理记录，没有读取隐藏测试成绩。用户要求检查“无正常提交”的原因；检查后继续执行原冻结协议。

| 会话 | 实际发生的情况 | 分类与处理 |
|---|---|---|
| heat / G2 / r1 | 登记了 8 个产物有效候选；首次候选为 `candidate-001`。模型先 finalize 未登记的 `cand_final`，随后 finalize `candidate-006`、`candidate-008` 均获接口接受。冻结实现中的 `finalization_invalid` 为永久标记，关闭时仍选 `invalid_finalize`，最终候选为空。 | 正常完成研究，但最终选择违反协议。保留全部候选及错误记录，不重跑、不事后替选。 |
| heat / G3 / r1 | 初期自行编写的实验代码出现广播维度和矩阵乘法错误；随后调试正弦基矩阵时，连续 244 次调用相同命令，打印 `pi*outer(j,k)` 与除以 257 后的数值。每次工具调用 ID 不同，且均收到成功反馈。共 265 次 API 请求全部成功、请求正文哈希均不同；没有压缩请求，没有任何 `bench evaluate` 或 finalize。最终累计输出达到 32768 token。 | 模型选择的调试调用陷入重复，预算正常耗尽，无候选提交。未发现提交桥故障。保留结果，不增加预算或重跑。 |
| heat / G1 / r1 / a001 | 首次响应已返回两条工具调用，但流式计数被代理判为 `usage_decreased`，随后中止，工具未执行。 | 基础设施/上游协议失败，不计科学结果。原失败完整保留，按原协议创建一次关联的 a002 重试。 |

G3 的实际重复片段为：

```python
j = np.arange(1, 257)
k = np.arange(1, 33)
A = np.pi * np.outer(j, k)
print(A[0, 0], A[0, 1], A[0, 2])
print(np.pi * 1 * 1 / 257, np.pi * 1 * 2 / 257)
```

244 次均返回相同的正确执行输出。这说明模型没有继续修正或提交，而不是命令一直未完成。记录支持“重复的模型工具调用”这一直接原因；无法仅据这些客户端日志确定模型/供应商内部为何循环，也不能据此排除每一种 SDK 问题。

G1 的可信记录只保存了 `usage_decreased`，没有保存被拒绝的原始 SSE usage 帧或具体回退字段，因此不能声称已经定位到某个输入、缓存或输出计数器。代理记账的 4096 是失败请求的保守预算扣除值，**不是实测输出 token**。关联重试未改变计数守卫、提示或预算；其最新状态以 ledger 为准。

证据：[机器可读诊断](../logs/formal-execution-local-003/submission-diagnosis.json)、[finalize 逐次记录](../logs/formal-execution-local-003/first-run-finalization-audit.json)、[关联重试调查](../logs/formal-execution-local-003/heat-g1-retry-investigation.json)、[第二版 ledger](../research-runs/research-0301cbdf4d96c055/manifest.json)。原压缩哈希冲突已通过第二版修复验收，本次 G3 没有触发压缩，G1 失败也不是压缩策略拒绝。

## G1 关联重试的结果

`heat-g1-r1-a002` 的 91 次 API 请求全部成功，计数回退没有复现。它也在 32768 输出 token 用尽后正常关闭，没有登记候选。此次 91 条工具参数并非逐字重复：模型持续生成 `explore*.py` 试验脚本，把正则化参数不断减小，末段已试到 `1e-85`，仍未实现并登记完整候选。最后一条 `explore84.py` 写入命令因剩余输出不足而截断。

这属于探索未收敛、未完成提交的行为，与首次 a001 的基础设施故障需要分开统计。[重试诊断记录](../logs/formal-execution-local-003/heat-g1-retry-diagnosis.json)保留全部计数和原始日志哈希。三个 heat 首轮会话均已按协议关闭，执行顺序已进入 ODE；没有重跑 G2/G3，也没有修改模型、提示、预算或判定规则。


## 预算切换时的 ODE 补充记录

第二版 ODE G1 在 15 次成功请求（已知输出 5,244 token）后，第 16 次响应触发 `usage_decreased`，按原规则保守占用该次 4,096 token，总 charged 为 9,340。它执行了 18 个 bash 工具调用，持续拟合与精修轨迹参数，未调用公开评估；最后响应异常不能归为正常科学失败。缺少当时被拒绝 usage 帧的字段级证据，无法确定哪一计数下降。第二版已封存，不再启动旧预算会话。

用户随后要求每会话上限 20 万输出 token，现已建立[第三版冻结](budget-freeze-2026-10-23.md)。新版本同时增加只含字段名和整数的 usage 异常诊断，保持原拒绝规则和计费方式。


## 第三版首个正常提交

20 万输出预算下的首个 heat G2 会话已正常完成，7 次公开评估，first=`candidate-004`、final=`candidate-007`，累计输出 122,638 token，422 次 API 请求全部成功、容器清理完成。期间经历长段重复工具调用，随后恢复候选评估。详见[完整结束诊断](../logs/formal-execution-local-004/first-completion-diagnosis.json)。这说明新上限与原生压缩可以支持正常提交；单个新会话不能证明增大预算对提交或科学成绩的因果效果，隐藏成绩仍未访问。


## 第三版 ODE G1 恢复后的正常提交

账户问题处理并通过合成 HTTP 200 探测后，a003 正常完成，83 次 API 请求全部成功，累计输出 185,235 token。3 次公开评估中 1 次产物有效，first/final 均为 `candidate-003`；可信登记、桥接与资源清理通过。

原生记录包含 24 次因输出上限截断而拒绝执行的工具调用、20 次进程创建资源错误，以及 2 次原生压缩。中途只读 cgroup 样本为 18/128 个进程、无 OOM；这只能描述该采样时点，不能否定其他时刻的进程上限事件。模型后续自行完成了有效提交，未修改提示、单请求上限或资源配置。完整计数及哈希见[结束诊断 003](../logs/formal-execution-local-004/closed-submission-diagnosis-003.json)。

同一诊断还显示，a002 在 HTTP 402 前曾连续 242 次调用相同工具参数；这说明重复调用与最终账户故障应分别报告。前三个 heat、ODE a003 的有效提交均不代表隐藏科学通过。


## 第三版 ODE G2

ODE G2 在持续探索后完成 4 次公开评估，4 次产物均有效；first/final 均为 `candidate-001`。364 次 API 请求全部成功，累计输出 158,843 token。359 次 bash 和 2 次 edit 调用未出现连续逐字重复参数，最长相同调用连续次数为 1；有 2 次截断工具错误、2 次其他工具错误和 2 次原生压缩。不能仅凭“暂未提交”就归为同一类调用循环。见[结束诊断 004](../logs/formal-execution-local-004/closed-submission-diagnosis-004.json)。


## 第三版 ODE G3

ODE G3 在 1,800 秒时限到达时正常超时关闭，7 次公开评估中 1 次产物有效，first=`candidate-007`，final 由冻结 `deadline_fallback` 规则选为同一候选。828 次请求成功，成功输出 141,704 token；宿主截止时间断开最后一个在途请求（上游 HTTP 200），该次保守占用 4,096 token、实测输出未知，不能归为新的账户故障，也不触发重试。

连续 749 次相同 bash 调用都读取同一 public-dev 轨迹并打印相同 20 行数据，工具返回内容只有 1 种。它没有在等待一个输出持续变化的后台任务。后续模型自行开始公开评估并在时限内留下有效候选；最长重复段、4 次原生压缩和各类工具错误均保留。见[结束诊断 005](../logs/formal-execution-local-004/closed-submission-diagnosis-005.json)与[重复调用审计](../logs/formal-execution-local-004/ode-g3-repetition-audit.json)。


## 第三版 Poisson G3：路径拒绝与反馈不充分

Poisson G3 在 1,800 秒时限正常关闭，3 次公开提交均未完成源码快照，first/final 为空，选择原因是 `no_valid_submission`。713 次 API 请求成功，成功输出 177,200 token；时限关闭断开 1 次在途请求，保守占用 4,096 token，未知实际用量。最长连续相同工具调用为 223 次。未发现可信桥传输、代理协议或资源清理故障；此结果按冻结规则保留，不重跑。见[结束诊断 006](../logs/formal-execution-local-004/closed-submission-diagnosis-006.json)。

具体提交路径依次为 `.`、`solve.py`、`.`。冻结路径检查拒绝点路径段，并要求真正的目录；`solve.py` 是文件。源码导出器在写 tar 前失败，而宿主先读 tar 的路径抛出 `ReadError: empty file`，使更具体的 exporter stderr 未能传给模型。模型收到的是笼统的源码准备失败。共同提示只写 `<relative-source-dir>`，没有明确说明 `.` 不被接受；因此这是实际的接口可用性局限，不能把这次无候选简单解释成数学求解能力不足。

已用不执行任何代码的离线样例核对：`.` 被拒绝、`solve.py` 文件被拒绝、含 `solve.py` 的 `candidate` 子目录被接受。有效证据为[路径诊断 002](../logs/formal-execution-local-004/poisson-g3-source-path-diagnosis-002.json)；首个临时样例因 macOS 非规范路径导致对照也失败，已明确标为无效，不能用作验证。没有向研究容器补充提示、替模型提交或改写冻结源码。后续协议应明确源码目录格式并完整返回有界的导出错误；本轮结果保留这一局限。


## 第三版 Poisson G2

Poisson G2 正常完成，8 次公开评估中 6 次产物有效，first=`candidate-003`、显式 final=`candidate-007`。276 次请求全部成功，输出 154,918 token，清理通过。最长相同调用连续 107 次；原生压缩 4 次、截断工具错误 1 次、其他工具错误 4 次。它最终进行了多次有效评估并明确选择了 final；first→final 的科学与性能变化尚待隐藏重放。见[结束诊断 007](../logs/formal-execution-local-004/closed-submission-diagnosis-007.json)。


## 第三版 Poisson G1 a001：首次得到字段级用量证据

首个上游 HTTP 200 响应被冻结的单调性守卫拒绝，新诊断明确记录 `input_tokens` 从 434 降到 306，原因 `usage_decreased`。没有成功请求或公开评估，输出实测未知；4,096 token 是保守预算占用，不是实测输出或账单。该字段证据只定位计数变化，不能证明供应商为何调整计数，也不能反推此前第二版两次同名失败的字段。

容器、网络和工作容器全部清理，VM、资源和冻结校验通过后，在不更改守卫、模型、提示、预算或评分的情况下创建一次关联 a002。原失败与字段级证据见[关联重试验收](../logs/formal-execution-local-004/poisson-g1-usage-investigation/retry-acceptance.json)。


## 第三版 Poisson G1 关联重试结果

a002 的 158 次 API 请求全部成功，`usage_decreased` 未复现。7 次公开评估中 3 次产物有效，first=`candidate-005`，显式 final=`candidate-007`，输出 36,503 token；最长相同工具调用连续 44 次，原生压缩 3 次。可信登记、桥接与清理通过。见[结束诊断 009](../logs/formal-execution-local-004/closed-submission-diagnosis-009.json)。首轮 9 格已完成研究，全部 15 次研究关闭前仍不访问隐藏成绩。


## 首轮 9 格的源码导出失败汇总（非最终全矩阵统计）

首轮已关闭的研究及其失败 attempt 共记录 61 次公开评估，61 次源码导出请求均可追溯。其中 24 次在导出阶段失败，全部向模型反馈 `ReadError: empty file`。失败路径包括 8 次 `.`、11 次绝对路径、4 次 `solve.py`、1 次 `out`。点路径段和绝对路径被冻结路径守卫明确拒绝；仅凭记录中的名字，不能把其他路径的失败全部断言为同一原因。共同提示明确要求相对源码目录，但未明确解释点路径的限制，桥接反馈又没有保留详细的导出错误。

因此这些记录同时反映提交接口的使用情况与反馈可用性，不能全部当作数学求解失败。没有据此更改既有候选、研究分母或冻结判定。逐次请求与哈希见[源码导出审计 001](../logs/formal-execution-local-004/closed-source-export-audit-001.json)；最终报告应在 15 次研究全部关闭后重新汇总。


## 第三版 heat G3 r2 a001：接近预算上限时的传输失败

该 attempt 没有公开评估，659 次成功请求输出 194,606 token；另两次 `upstream_transport_error` 的有效额度分别为 4,096、1,298 token，均无 HTTP 状态和完整用量，保守占用共 5,394 token，令 charged 达到 200,000。此前进度中按 charged 口径称“达到 20 万输出”不够准确：已知成功输出为 194,606，失败部分真实用量未知。

宿主时间截止未触发。冻结控制器按终态传输错误将其关闭为 `research_invalid/api_failed`，不能改记为正常预算耗尽的科学结果。原始成本和失败完整保留；一次极小恢复探测返回 HTTP 200 且完整结束，清理、VM 和冻结复核通过后，创建一次关联 a002。底层传输异常类型未被冻结的通用错误处理器保存，不能断言具体网络原因。见[调查与重试验收](../logs/formal-execution-local-004/heat-g3-r2-transport-investigation/retry-acceptance.json)及[结束诊断 010](../logs/formal-execution-local-004/closed-submission-diagnosis-010.json)。


## 第三版 heat G3 r2 a002：预算正常用尽，保留无提交

在用户最新“无需过多重试”指令前已启动的 a002，于约 1,792 秒时用满 200,000 输出 token。734 次请求全部成功，没有公开评估或有效候选；可信控制器以 `research_timeout` 关闭，选择原因 `no_valid_submission`，清理通过。这是正常预算结束，不再因无产出重跑。

原生记录有 713 次 bash 调用，最长连续相同调用为 704 次，12 次原生压缩；这仅刻画工具调用行为，不推断模型内部思路。前三版预算和上下文策略不同，且会话是独立采样，不能把它与旧版差异解释为预算修订的因果效果。见[结束诊断 011](../logs/formal-execution-local-004/closed-submission-diagnosis-011.json)。

截至该次关闭，第三版共 10 次有效研究关闭，其中 8 次有 first/final、2 次无有效提交；另保留 4 个无效 attempt。14 个已关闭 attempt 的已知成功输出共 1,594,883 token，charged 共 1,616,661 token；差额是保守失败额度，真实失败用量与金额仍未知。以上为阶段统计，后续研究与隐藏重放尚未完成。


## 第三版 heat G1 r2：文件名变化掩盖了重复代码

heat G1 r2 在约 1,536 秒时用满 200,000 输出 token，543 次 API 请求全部成功；没有公开评估或 first/final，正常 `research_timeout/no_valid_submission` 关闭，清理通过，不再重试。见[结束诊断 012](../logs/formal-execution-local-004/closed-submission-diagnosis-012.json)。

其 523 次 bash 调用原始参数各不相同，因此逐字匹配的最长连续重复只有 1 次。进一步仅规范化 `explore<数字>.py` 文件名后发现：连续 515 次调用的其他字节完全相同，均计算并打印同一组 public-dev 谱诊断；515 次工具结果文本也只有一个哈希。可观察到的变化是文件名递增，没有相应的分析代码或结果变化。这说明逐字调用去重会漏掉此类重复，不能把所有“唯一调用”都解释成新的研究探索；不据此推断模型内部原因。完整规则、命令与源日志哈希见[文件名重复审计](../logs/formal-execution-local-004/heat-g1-r2-filename-repetition-audit.json)。


## 对 ODE G2 的补充核查：唯一参数不等于独立探索

在 heat G1 r2 发现文件名递增后，对已关闭的 ODE G2 作同样的有界检查：仅替换 `explore<数字>.py`、`diag<数字>.py` 文件名，359 个原本唯一的 bash 参数缩减为 67 种；最常见的三种分别出现 79、79、69 次，每种对应的工具结果文本各只有一个哈希。它们并非相邻逐字重复，因此原“最长连续逐字重复为 1”的统计仍成立，但不能据此判断没有反复执行。ODE G2 最终仍完成了 4 次有效公开评估；重复行为和有效提交应分别描述。见[文件名重复审计](../logs/formal-execution-local-004/ode-g2-filename-repetition-audit.json)。该规则是事后诊断，不是对所有工具调用的完整语义去重。


## 第三版 heat G2 r2：一次有效提交后正常超时

heat G2 r2 完成 1 次公开评估且产物有效，first/final 均为 `candidate-001`，在 1,800 秒时限后按 `deadline_fallback` 选择。732 次 API 请求全部成功，成功输出及 charged 均为 196,613 token，没有在途失败计费；控制器明确记录墙钟预算到达，清理通过。没有因为缺少后续候选而重跑。

691 次 bash 调用中最长连续相同参数为 678 次，原生压缩 21 次。与无提交会话相比，它至少留下了一个可重放候选；first/final 为同一候选，不能据此主张迭代收益。见[结束诊断 013](../logs/formal-execution-local-004/closed-submission-diagnosis-013.json)。截至此时，12 次有效研究关闭中 9 次有 first/final、3 次无有效提交；隐藏重放尚未启动。


## 第三版 heat G3 r3：达到预算，无有效提交

heat G3 r3 正常超时关闭，可信原因记录为 `host/native research wall budget reached`（约 1,802 秒写入关闭记录）。742 次 API 请求全部成功，累计输出恰为 200,000 token；没有公开评估或 first/final，`no_valid_submission` 保留，清理通过。722 次 bash 调用中最长连续相同参数为 705 次，原生压缩 11 次。见[结束诊断 014](../logs/formal-execution-local-004/closed-submission-diagnosis-014.json)。本次没有追加重试；截至此时 13 次有效研究关闭中 9 次有候选、4 次无有效提交。


## 第三版 heat G1 r3：持续改变种子做模拟，未转入提交

heat G1 r3 在约 1,109 秒耗尽 200,000 输出 token，240 次 API 请求全部成功；没有公开评估或 first/final，正常 `research_timeout/no_valid_submission` 关闭，清理通过。230 次 bash 参数各不相同，原生压缩 6 次。见[结束诊断 015](../logs/formal-execution-local-004/closed-submission-diagnosis-015.json)。

进一步检查自建 `sim<数字>.py` 命令，221 次匹配调用使用 220 个不同随机种子（1–220），工具结果文本有 220 个不同哈希；214 次包含相同的四值 alpha 网格，但种子在变化。样本结果实际输出不同模拟误差，因此不能将其归为只改文件名、反复得到同一结果的计算。本次可观察到的是持续开展自建模拟，却未在预算内提交求解器。完整提取规则、调用与哈希见[模拟审计](../logs/formal-execution-local-004/heat-g1-r3-simulation-audit.json)。这类无提交与重复调用、源码目录拒绝、API 故障应分别报告。未据此追加研究 attempt。


## 第三版完整研究矩阵：15 次研究关闭

最后的 heat G2 r3 在约 1,371 秒耗尽 200,000 输出 token，476 次 API 请求全部成功，无公开评估或 first/final；正常 `research_timeout/no_valid_submission` 关闭，清理通过。438 次 bash 调用中最长连续相同参数为 380 次，原生压缩 20 次。见[全体关闭诊断 016](../logs/formal-execution-local-004/closed-submission-diagnosis-016.json)。

完整矩阵包含 15 次有效研究关闭，其中 9 次有 first/final、6 次无有效提交；另保留 4 个无效 attempt，总共 19 个 attempt。15 次有效研究的已知成功输出为 2,324,341 token，含失败 attempt 的已知成功输出为 2,591,496 token；全部 charged 为 2,613,274 token，差额 21,778 是保守失败额度，真实失败用量和金额仍未知。各会话累计输出上限均为 200,000，不是整套矩阵的总上限。

全矩阵共 62 次公开评估、23 次产物有效；62 次源码导出请求中仍有 24 次失败，向模型反馈均为 `ReadError: empty file`。路径计数与此前一致：8 次 `.`、11 次绝对路径、4 次 `solve.py`、1 次 `out`。完整请求及哈希见[全体源码导出审计 002](../logs/formal-execution-local-004/closed-source-export-audit-002.json)。这些问题、反复计算以及持续模拟但未提交分别保留，不能混称数学失败。隐藏科学成绩由后续独立重放决定。

[启动核验](../logs/formal-execution-local-004/hidden-preflight-001.json)确认全部研究先关闭、所有资源已清理、同一 VM 与冻结计划有效后，才启动隐藏重放；用户“无需过多重试”指令之后，新增关联研究重试为 0。
