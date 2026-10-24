# 2026-10-23 正式资源与计时窗口验收

资源验收与 T3 三组正式校准均已通过，性能模式单独冻结为 `efficiency_gate_1.5`。本文记录资源验收结束时的状态；同日后续已完成[Flash整体任务冻结](formal-freeze-2026-10-23.md)，正式研究和 final-test 尚未执行。

## 资源实测

Mac 为 10 核、16 GiB，Colima 为 QEMU/aarch64 Linux、6 vCPU、配置 10 GiB；Docker 实际识别 10,401,181,696 字节。原 8 个服务容器按用户要求保持停止，数据卷保留。

[资源验收 002](../logs/resource-acceptance-local-002/summary.json) 的 15 项检查全部通过，[哈希清单](../freezes/resource-acceptance-local-001.json)绑定 71 个原始证据文件。

| 检查 | 实测 |
|---|---|
| 三个 R 镜像 | 分别核验实际 `cpu.max=400000 100000`、`memory.max=4294967296`、禁 swap、pids=128；6 个 CPU 压力子进程触发配额节流，每个 R 实际消耗约 12 CPU 秒 |
| R/W 并发内存 | R 保持逐页写入的 3.75 GiB，同时实际 W 逐页写入 3.75 GiB 并正常生成合法产物；W 峰值 4,065,931,264 字节 |
| W 真实 OOM | 峰值精确为 4,294,967,296 字节；`memory.events` 中 `oom=1`、`oom_kill=1`，退出码 137，禁 swap |
| OOM 分类 | 实际 `replay_single` 返回 `attempt_status=oom`、`evaluation_status=valid`、score=0、reward=0；无合法产物 |
| 恢复与清理 | OOM 后新 W 正常运行，所有探针容器清理完成，剩余运行容器 0 |

R 验收使用固定的三个研究镜像，在无网、非 root、无宿主挂载的独立探针中施加正式资源限额；本次没有调用模型或重新运行完整 Harbor/Pi Trial。此证据验收资源，不替代正式模型会话、网络接线或完整任务 freeze。

首轮 [001](../logs/resource-acceptance-local-001/summary.json) 也实际触发了 4 GiB OOM并正确分类，但新探针把带换行的 `memory.swap.max` 与 `"0"` 直接比较，导致汇总误报。修复字符串处理后独立重跑为 002；001 的输入、源码、日志和失败汇总完整保留，执行器与评分器未修改。

复跑入口（真实内存负载，仅在已有服务已停止时使用新目录）：

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python \
  tests/resource_acceptance_probe.py --output logs/resource-acceptance-new
```

## T3 正式校准结果

[独立轮次 005](../logs/t3-formal-calibration-local-005/acceptance.json)通过连续宿主观察与实际 Docker 事件核验，[性能冻结记录](../freezes/t3-profile-local-001.json)绑定计时合同、输入、源码和全部原始证据。三个完整 Jacobi-CG/LU 比较组均按 `B,C,C,B,B,C` 执行，每次新 W 和空输出目录，每批 12 例，共 18 个 W、18 个 J、216 个方法×实例检查全部通过；没有重试或挑选组内样本。

| 校准组 | Jacobi 中位秒数 | LU 中位秒数 | speedup | 基线 max/min | 正式资格 |
|---|---:|---:|---:|---:|---|
| 1 | 1.110949 | 0.493832 | 2.249650× | 1.015249 | 通过 |
| 2 | 1.102899 | 0.495276 | 2.226840× | 1.011378 | 通过 |
| 3 | 1.106469 | 0.499895 | 2.213403× | 1.011515 | 通过 |

三组均满足预定的基线 max/min≤1.20、speedup≥1.8、正确性与资源资格要求，因此选择 `efficiency_gate_1.5`：未来正式候选须正确 12/12 且 speedup≥1.5 才获得通过 reward。正式计时覆盖 Python 启动、导入、I/O、预处理、计算及全部后代退出；Docker 准备和 J 另计。完整三组的宿主墙钟及全部单次耗时保留在原日志。此次加速比仅说明当前硬件、镜像与作者校准集上的 Jacobi/LU 比较，不能当作模型研究结果或 final-test 成绩。

宿主连续采样 34 次，覆盖含预检查在内的 67.51 秒，未发现超阈值无关进程或新增 swap-out。全局 swap-in 共 383 页如实保留；它包括此前已换出页面的读取，未被写成零换页。所有 W 禁 swap。`pmset` 前后均未记录热或性能警告，但没有 CPU 功率状态记录，不能据此声称频率恒定。缓存采用未清除的宿主/客体页缓存，记录为 warm；新容器不等于冷缓存。

独占范围为停止其他容器、关闭活跃应用后的专用 Colima 计时窗口，OS、GUI 与运行控制开销持续记录。每组实时捕获 142 个容器事件，恰有本组 6 W + 6 J 的 12 个启动事件；没有其他容器启动。结束后运行容器为 0，原 8 个服务继续保持停止。

## 前置窗口与修复记录

已增加独立宿主观察入口，先采样 30 秒，再决定是否进入现有三组 Jacobi/LU、每组 BCCBBC 的完整协议。观察记录只保存进程名、PID、累计 CPU 时间和换页计数，不读取进程参数、环境或凭据。已有 `TimingLease` 继续核验固定镜像、VM boot ID、独占锁、每组 Docker start 事件和清理。

最初采用保守的零换入/零换出筛查：

- [窗口 001](../logs/t3-formal-calibration-local-001/acceptance.json)：VS Code Renderer 短时约 22% 单核 CPU，少量 swap-in，拒绝。
- [窗口 002](../logs/t3-formal-calibration-local-002/acceptance.json)：另一 VS Code Renderer 短时约 27% 单核 CPU，少量 swap-in，拒绝。
- [窗口 003](../logs/t3-formal-calibration-local-003/acceptance.json)：用户退出 VS Code 后无超阈值无关进程，仅因 32 页全局 swap-in 拒绝。

前三个窗口均未运行 T3 样本。原计划没有要求 macOS 全局零换入；修订 2 在首次校准前将 swap-in 改为观察项，保留零新增 swap-out、W 禁 swap、无活跃无关进程和原基线稳定度要求。所有旧策略、源码、原始采样与拒绝结果保留。

[轮次 004](../logs/t3-formal-calibration-local-004/acceptance.json)执行了全部三组，但正式资格被拒绝：Docker 事件查询用 macOS 时间限定，实测 VM 时钟快约 2.1 秒，导致跨组事件混入或末尾事件遗漏。[Docker 官方文档](https://docs.docker.com/reference/cli/docker/system/events/)另说明历史事件最多返回最近 256 条。修复为从组开始前实时订阅事件，以从不启动的标记容器 create 事件确认订阅和结束边界，避免跨宿主时间比较与历史缓冲截断；仍拒绝未知、缺失或重复 W 启动事件。新事件原文进入正式资格记录，原始 worker/timer 保持 `formal_timing=false`。

修订 3 同时把 Colima 的 `limactl` 正确归为 VM 控制开销，并保证 CPU 差分采样至少间隔 2 秒，避免同步采样的极短区间放大百分比。004 中相关拒绝及 Tailscale/控制服务短时观测完整保留，未追认任何样本。修复仅涉及资格事件采集及宿主观察，不改计时区间、求解器、输入、评分或门槛；修复后的 005 全部重新执行。事件采集和 T3 协议定向回归 [25/25](../logs/t3-formal-calibration-local-004/event-capture-regression.txt)通过。

复跑（使用新目录，每次重新验收窗口）：

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python \
  tests/accepted_t3_calibration.py \
  --resources logs/resource-acceptance-local-002/summary.json \
  --output logs/t3-formal-calibration-new
```

## 交付边界

资源验收结束时，模型/任务 freeze 和15会话计划仍为 `draft`。随后已完成[正式冻结](formal-freeze-2026-10-23.md)，纳入本次事件采集修复以及Flash模型切换的新源码哈希；旧 `draft-007` 保留。正式研究仍为0，final-test求解成绩未读取。005 计时窗口有明确有效期且连续观察已经结束，后续正式重放须按相同策略建立新窗口。

历史报告 `docs/results.md` 和 `results/stage-status.json` 保留其生成日期与当时状态；当前资源与 T3 状态以本文及两份验收/冻结记录为准。本次结果在本机归档，未发布到 GitHub。

修复后[完整单测](../logs/t3-formal-calibration-local-005/unit-tests.txt)为348项通过、2条既有Harbor弃用提示；旧草稿校验仍以退出码2拒绝正式启动。[本机归档](../logs/resource-t3-delivery-local-001/evidence.tar.gz)包含资源调整、两轮资源验收、五个窗口/校准轮次、源码快照、冻结记录与本文；[归档核对](../logs/resource-t3-delivery-local-001/integrity.json)记录逐文件核验和压缩包哈希。输入/私有GT原数组仍在本机 `authoring/data/`，其73个文件哈希由校准证据绑定；压缩包不替代完整数据复现包。
