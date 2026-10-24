# 原生压缩修复与第二版正式冻结

当前执行已按用户授权切换至[每会话 200,000 输出 token 的第三版冻结](budget-freeze-2026-10-23.md)，计划为 `research-run-plan-formal-003.json` / `research-6615cd7900ba0750`。先检查第三版 ledger；下文旧版配置与状态保留其历史范围。

用户明确授权“授权新版本修复并继续（推荐）”后，建立第二版正式冻结。当前执行计划为 [research-run-plan-formal-002.json](../freezes/research-run-plan-formal-002.json)，plan ID 为 `research-0301cbdf4d96c055`；冻结校验 `formal_ready=true`、`blockers=[]`。原版冻结、两个基础设施失败 attempt 和对应成本报告继续保留，不计入新计划的科学分母。

## 修复范围

原研究请求仍严格匹配既有 system/tools 哈希；新增的 Pi 原生压缩规则严格匹配实际捕获的摘要 system 哈希，并要求请求中完全不存在 tools 字段。空数组、null、研究工具混配和未知提示均不能通过。两类请求共用模型、采样、每请求 4096 token、会话累计 32768 token、请求数和时间守卫。事件新增请求类别；原生压缩源码哈希在会话模型调用前核对。

模型仍为 DeepSeek-V4.1-Flash-1017，Pi 0.84.1 与 Harbor 修订不变。研究提示、公共任务包、既有 90 例数据、全部数值镜像、数值源码、评分、资源、预算及任务/组/重复次序均未变化。Pi 原默认模型元数据 contextWindow=128000、maxTokens=16384 保留。新的 plan/run/session/workspace 身份与原版完全分离，不恢复原对话。

完整变更和证据：[修订补丁](../logs/formal-freeze-local-002/revision.patch)、[影响核对](../logs/formal-freeze-local-002/revision-impact.json)、[授权记录](../logs/formal-freeze-local-002/authorization.json)、[冻结校验](../logs/formal-freeze-local-002/validation.json)。

## 验收

- [354 项测试通过](../logs/formal-freeze-local-002/unit-tests-final.txt)，覆盖共享预算、精确拒绝、运行前源码校验、容器 CLI 接线和新版本身份/顺序规则。
- [三镜像离线策略捕获](../logs/model-policy-capture-compaction-local-003/result.json)一致；首次与更新摘要均在 HTTP 前捕获，真实模型请求为 0。前两次捕获脚本诊断失败日志保留。
- [真实原生摘要检查](../logs/formal-freeze-local-002/native-live-summary/result.json)两次成功，共 283 输出 token。其 SDK 零成本字段来自合成元数据，不代表实际免费；实际金额未知。
- [完整 Harbor 验收](../logs/harbor-native-compaction-pilot-001/result.json)67 次请求全部成功，18096 输出 token，包含自然触发的原生压缩。一个候选完成既有 pilot-smoke 路径；pilot 分数不进入正式结果。桥接及清理错误为空，相关容器与网络均已清理。
- 数值/评分源码未变，保留既有资源及 T3 profile 验收适用性。VM boot ID 未变，启动前核对 Docker 6 CPU、10401181696 字节内存及四份不可变镜像。

## 执行入口

```sh
.venv/bin/python -m runner.run_plan validate --plan freezes/research-run-plan-formal-002.json
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study start \
  --plan freezes/research-run-plan-formal-002.json \
  --run-id research-0301cbdf4d96c055-heat-g2-r1
```

实际执行由 [串行控制脚本](../logs/formal-execution-local-003/research_sequence.py)负责；接手前先检查 [ledger](../research-runs/research-0301cbdf4d96c055/manifest.json) 和运行进程，不能重复启动。全部 15 次研究有效关闭后再开始隐藏重放。T3 仍需新的连续观察独占窗口；旧校准窗口不能复用。

最终报告使用第二版计划和 ledger，并单独保留原版两个失败 attempt 的成本与原因。科学零分或无候选不重跑；基础设施失败必须调查后创建关联重试。当前授权不包含 GitHub 发布。
