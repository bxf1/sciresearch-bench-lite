# 2026-10-23 正式执行：原生上下文压缩与冻结策略冲突

当前执行已按用户授权切换至[每会话 200,000 输出 token 的第三版冻结](budget-freeze-2026-10-23.md)，计划为 `research-run-plan-formal-003.json` / `research-6615cd7900ba0750`。先检查第三版 ledger；下文旧版配置与状态保留其历史范围。

此阻塞已通过用户授权的[第二版冻结](compaction-freeze-2026-10-23.md)修复并验收；正式研究已按新身份启动。下文保留诊断过程。

已按交接启动正式执行，但当前 **0/15 个有效研究会话、0/9 格、隐藏重放 0 次**。第一个预声明 run `research-5db960ec2eb8d256-heat-g2-r1` 的原始 attempt 和一次关联重试均为 `infrastructure_failed`。它们不是正常无提交的科学零分，不能纳入科学结果分母。其余会话未启动。

启动时的冻结校验、不可变镜像、Python/NumPy/SciPy/Harbor 版本、实际 Docker 6 vCPU / 10,401,181,696 字节、VM boot ID 和专用凭据可用性均通过。仍使用 DeepSeek-V4.1-Flash-1017；没有修改模型、采样、任务提示、数据、评分或任何冻结源码。见[启动核验](../logs/formal-execution-local-001/preflight.json)。

| attempt | 父 attempt | 成功 API 请求 | 已计输出 token | 宿主 attempt 秒数 | 候选 / 公开评估 |
|---|---|---:|---:|---:|---:|
| heat-g2-r1-a001 | 无 | 41 | 11,064 | 156.566 | 0 / 0 |
| heat-g2-r1-a002 | a001 | 111 | 32,679 | 396.767 | 0 / 0 |

两次共 152 次成功请求、43,743 个已计输出 token。实付金额未核实，仍为 null。两次 registry 均关闭，first/final 均 null；清理和文件桥无错误，运行容器为 0。精确计数、证据哈希和重试关系见[机器可读执行状态](../logs/formal-execution-local-001/execution-status.json)及[ledger](../research-runs/research-5db960ec2eb8d256/manifest.json)。

## 已证实原因

模型重复探索操作，导致上下文持续增长：a001 有 31 次参数完全相同的工具调用；a002 反复写入和执行内容相同、文件名序号递增的 `explore<N>.py`。原生 Pi 随后记录 `compaction_start`，原因 `overflow`；它的摘要请求使用固定摘要系统提示，并省略 `tools`。该请求的 system SHA256 为 `2b61101f62e3b292e99d434018dbe204cc389850f12730d2a33aaca40cba077c`，与 Pi 0.84.1 缓存包源码中的固定摘要提示逐字核算相符。

正式代理只接受研究请求的单一 system/tools 哈希对，因此两次都记录 `request_policy_rejected`，不匹配字段为 system、tools，随后进入 `failed_closed`。这是原生摘要请求与冻结策略之间的兼容性缺陷；现有守卫按配置正确拒绝，没有被绕过。

原始 `host-termination.json` 的 reason 写作 `relay could not persist trusted evidence`，这是控制器对 `failed_closed` 的过宽错误描述。可信代理的 `evidence_error=false`，并完整保留了策略拒绝事件；不能将其解释为实际磁盘写入失败，也不改写原始 reason。

离线源码还确认，自定义模型未提供元数据时 Pi 默认 contextWindow=128000、maxTokens=16384。这解释了压缩触发的运行背景，但本轮没有调整这些值。未证明模型重复调用本身由代理造成，也没有将重复调用改写为基础设施错误；基础设施分类依据实际压缩请求失败。

## 已授权的最小修订

用户已在本会话明确回复“授权新版本修复并继续（推荐）”。该授权允许建立新的冻结版本，保留原计划和两个失败 attempt，沿用模型、研究提示、数据、评分、预算及顺序。下列原型和诊断记录保留其产生时的状态；当前已接入完整执行链路，354 项测试通过，三个固定镜像的离线策略捕获及两次真实原生摘要请求通过，完整 Harbor 冒烟验收进行中。新版本最终状态以 `logs/formal-freeze-local-002/validation.json` 为准。

[隔离原型补丁](../logs/formal-execution-local-001/proposal/relay-prototype.patch)提出增加第二种精确请求规则：固定 Pi 摘要 system 哈希，同时要求 `tools` 字段完全不存在。研究请求继续匹配原 system/tools 哈希对。两类请求共享相同模型、采样、4096 单次输出上限、32768 会话输出总额及原请求/时间限额；事件记录其请求类别。哈希匹配只证明请求形状符合规则，不证明请求由某个特定进程发出。

[12 项离线检查](../logs/formal-execution-local-001/proposal/check-result.json)通过：重现旧拒绝、默认保持旧守卫、接受正确摘要、拒绝未知提示/混配工具/空或 null 工具、验证两类请求共享总预算及事件可追溯性。原型只存在于 logs 中，未应用到 `runner/`。这不等同于完整集成或原生模型验收。

后续[3 项原生链路检查](../logs/formal-execution-local-002/probe-001/result.json)也通过：在 `network=none` 的容器内，运行固定缓存包的 Pi `generateSummaryWithUsage` 和实际 Anthropic SDK，经真实本地 HTTP/SSE 链路连接隔离原型及模拟上游。旧规则拒绝原生摘要，新规则接受首次摘要和更新摘要；核验了实际 system 哈希、tools 字段缺失、4096 单请求截断及输出计数。真实提供商请求为 0，未读取研究对话或隐藏数据。这补充了原生序列化和传输兼容性证据，仍不是完整 Harbor 会话或真实模型 smoke。

若批准，应完成 CLI/transport/session admission 接线、离线原生摘要策略捕获、预算/拒绝回归和原生 smoke，再建立新版本的任务 freeze 与 15 会话计划。沿用三任务、三组、顺序、模型、提示、数据、数值镜像、评分与研究预算；记录与旧计划的继承关系。旧冻结和两个失败 attempt 必须保留。新的正式会话必须使用新身份，不把已有失败改成成功，也不复用对话。

交接文档第 6A 明确要求“不要重新运行 draft/freeze 生成器”。因此本轮只准备原型和证据，已请求用户授权新版本；未重生成计划、放宽当前守卫或启动第三次盲目重试。

## 当前交付与未完成工作

[进度报告](../results/formal-study-progress-002/summary.json)和[attempt 成本表](../results/formal-study-progress-002/attempts.csv)保留两次基础设施失败、全部 15 个待执行 run，以及 11 个尚未执行的作者方法。该报告属于进度快照，不是正式科学结论。运行中尝试生成的首份进度报告被终态校验拒绝，其日志也保留。

已准备串行执行包装器和实际隐藏重放的连续观察包装器，但后者尚未实跑验收。15 个有效研究会话、11 种作者方法与 first/final 隐藏重放、新 T3 独占窗口以及最终科学报告仍待完成。没有访问隐藏求解成绩，没有提交或对外发布。

三次只读源码探针未获取目标文件：前两次假设原生 Pi 位于原始 R 镜像，第三次确认目录不存在。R 镜像本身不含 Harbor 安装后的 Pi；后续从已有离线策略捕获所用的本地 Pi 缓存读取，已核对关键核心/提供商模块哈希。新增摘要源码未在原始运行审计中逐文件记录，此证据边界保留在[源码审计](../logs/formal-execution-local-001/proposal/native-source-audit.json)。
