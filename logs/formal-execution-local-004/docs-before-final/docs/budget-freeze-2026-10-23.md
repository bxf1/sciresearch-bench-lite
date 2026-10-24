# 第三版冻结：每会话累计输出上限 200,000 token

当前研究已有效关闭 **15/15**，首轮 9 个任务×组别格均已覆盖，其中 9 次保留 first/final；Poisson G3、heat G3 r2/r3、heat G1 r2/r3 与 heat G2 r3 达到预算后无有效提交，均保留结果。19 个 attempt 的关闭与清理已核验，正在统一执行隐藏重放。用户要求未产出任务正常关闭、无需过多重试；此后不新增自动重试。见[最新状态与恢复入口](execution-status-2026-10-23.md)。

用户在同一执行会话中明确要求“预算加大一点，加到上限20w token”。第三版按每个独立研究会话累计输出 200,000 token 执行，正式计划为 [research-run-plan-formal-003.json](../freezes/research-run-plan-formal-003.json)，plan ID 为 `research-6615cd7900ba0750`，SHA256 为 `47356b71b90acb1178dc86f94ec4f58041d933d00a67b4594cc0c697b568a033`。

每请求仍最多输出 4,096 token；每会话仍为 1,800 秒、20 次已接受公开评估、seed=0、无 turn cap、不 resume。原 512 次请求保护上限随输出预算同比调整为 3,125 次，低于已有 4,096 次硬上限。输出预算包括研究请求和原生压缩请求，不是输入与输出 token 的合计，也不改变 Pi 的 128,000 上下文窗口或 16,384 默认单请求元数据。

15 会话的任务、组别、重复次数和顺序不变，使用新的 run/session/workspace 身份。模型及其参数、研究提示、工具、精确原生压缩策略、镜像、90 例数据、数值源码、评分与资源限制全部沿用。第三版 15 会话全部有效关闭后，才执行 11 种作者方法和研究 first/final 的隐藏重放。T3 仍需新的连续宿主观察窗口。

## 验证与证据

- [357 项完整测试](../logs/formal-freeze-local-003/unit-tests-final.txt)通过；只有两条既有 Harbor 弃用提示。边界测试验证 48×4096+3392=200000 后拒绝下一请求，以及第 513 个小请求仍可接受。
- [真实原生压缩 smoke](../logs/formal-freeze-local-003/native-live-summary/result.json)验证新代理限额、初始摘要和摘要更新，均成功且清理完成；仅使用合成对话。
- [冻结校验](../logs/formal-freeze-local-003/cli-validation.json)为 `formal_ready=true`、`blockers=[]`；全部 15 个会话参数均已核对。
- [源码变更范围](../logs/formal-freeze-local-003/revision-impact.json)、[授权](../logs/formal-freeze-local-003/authorization.json)及源码快照均已保留。
- [新冻结归档](../logs/formal-freeze-delivery-local-003/evidence.tar.gz)：249 文件，SHA256 `7f2583a90ec1be58d3890729e54223937268f35596bf84d87f7ebb50691a8af5`；成员哈希与凭据扫描通过。

另外补充了一项诊断：当代理拒绝下降的 usage 计数时，仅保存字段名和已验证为整数的前值、后值。拒绝规则、保守计费和失败分类均未改变，不保存原始请求正文或凭据。旧版两次 `usage_decreased` 未保留这个字段级证据，不能反推出当时下降的是哪项计数。

## 旧版记录与“无正常提交”排查

第二版在预算切换时封存为 5 个 attempt：3 个有效研究关闭、2 个基础设施失败，尚无隐藏成绩。暂停调度器后让当时运行的 ODE 自行结束；它在 15 次成功请求后因第 16 次响应的 `usage_decreased` 失败。所有容器清理完成后，才替换可信源码。详情见 [封存记录](../logs/formal-freeze-local-003/predecessor-closed.json)。

第二版已有 heat 证据显示：G2 产生 8 个有效候选，但一次不存在的 finalize ID 触发冻结协议的粘性无效标记，导致 final 为空；G3 连续重复同一调试命令；G1 的有效重试持续调整参数直到旧 32,768 输出预算耗尽，没有调用公开评估。另两个基础设施失败分别发生在 heat G1 和 ODE G1，均为 usage 单调性校验失败。完整区分见 [提交诊断](submission-diagnosis-2026-10-23.md)。

增大预算只改变预算约束，不能保证提交候选，也不能修复 usage 异常。旧版记录、失败和成本不计入第三版 15 会话分母，单独保留。[第二版执行归档](../logs/formal-execution-delivery-local-003/evidence.tar.gz) SHA256 为 `dc1c1162b82462505e4d1b8538bc83cf54e287735fb8f0d70f325af708f28e42`。第一、二版冻结及其既有归档均未改写。

## 继续执行

第三版顺序控制器为 `logs/formal-execution-local-004/research_sequence.py`，进度入口为 `logs/formal-execution-local-004/status.py`。先检查进程与 [ledger](../research-runs/research-6615cd7900ba0750/manifest.json)，不要重复启动。研究异常会停止调度，须调查后按协议处理；科学失败不能按基础设施失败重试。

全部研究关闭后，使用同目录的 `hidden_sequence.py` 和 `observed_final.py` 执行后续阶段。这些入口只是准备完成；是否执行、是否完整以实际 ledger 和验收结果为准。本地归档未对外发布。


## 执行后续：宿主合盖中断

第三版前三个 heat 会话已正常关闭并有有效 first/final。随后 ODE G1 的 a001 在 2026-10-23 09:33:36 +0800 遇到宿主 Clamshell Sleep，10:03:37 才完全唤醒；墙钟超过研究上限而会话尚未关闭，不能作为正常科学结果。已暂停后续调度、通过现有取消路径保留 a001 为 `research_invalid/cancelled`，确认资源清理与 VM boot ID 不变后，启动一次关联重试 a002。见[调查与重试证据](../logs/formal-execution-local-004/ode-g1-host-sleep-investigation/retry-acceptance.json)。有效研究进度及后续结果仍以第三版 ledger 为准。运行期间须保持电脑开盖及稳定供电；当前 caffeinate 防空闲睡眠未阻止这次合盖睡眠。
