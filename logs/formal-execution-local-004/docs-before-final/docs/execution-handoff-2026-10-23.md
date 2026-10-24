# SciResearch-Bench-Lite v0.3：进度总结与正式执行交接

当前研究已有效关闭 **15/15**，首轮 9 个任务×组别格均已覆盖，其中 9 次保留 first/final；Poisson G3、heat G3 r2/r3、heat G1 r2/r3 与 heat G2 r3 达到预算后无有效提交，均保留结果。19 个 attempt 的关闭与清理已核验，正在统一执行隐藏重放。用户要求未产出任务正常关闭、无需过多重试；此后不新增自动重试。见[最新状态与恢复入口](execution-status-2026-10-23.md)。

当前执行已按用户授权切换至[每会话 200,000 输出 token 的第三版冻结](budget-freeze-2026-10-23.md)，计划为 `research-run-plan-formal-003.json` / `research-6615cd7900ba0750`。先检查第三版 ledger；下文旧版配置与状态保留其历史范围。

当前执行已获用户授权采用[原生压缩修复后的第二版冻结](compaction-freeze-2026-10-23.md)，计划为 `research-run-plan-formal-002.json` / `research-0301cbdf4d96c055`。下文第一版配置与阻塞描述保留历史时点；接手请先检查第二版 ledger，避免重复启动。


更新日期：2026-10-23（Asia/Shanghai）。本文供新的干净会话接手，汇总当前事实、剩余工作和执行入口；不修改已冻结的实验协议。

执行后续：首个 run 已产生两个有关联的基础设施失败 attempt，仍为 0/15 有效会话。已发现 Pi 原生压缩与冻结请求哈希不兼容，后续启动须先处理[执行阻塞记录](execution-blocker-2026-10-23.md)。下文“可以进入正式研究”和 `research-runs/` 尚不存在的描述对应交接时点，不能覆盖这一新事实。

## 1. 当前结论

**实现、资源验收、T3 正式性能校准和正式冻结已完成，可以进入正式研究阶段。正式研究仍为 0/15 会话、0/9 实验格，正式隐藏测试及最终结论尚未完成。**

原先六项待办中，第 1–3 项已经完成，第 4–6 项等待执行。最新冻结校验保存为 `formal_ready=true`、`blockers=[]`；新会话启动前仍须重新检查当时的环境与冻结文件。

本次交接只整理文档，没有启动正式研究或隐藏评分，也没有提交、推送或创建新会话。

## 2. 整体计划：要评估什么

目标是在三类受控合成科学计算任务中，比较同一模型在不同方法指导程度下的求解表现，并记录首次有效候选到最终候选的变化与成本。

| 任务 | 内容 | 正式评价重点 |
|---|---|---|
| T1 / `heat` | 从含噪热方程观测恢复初始场 | 恢复与前向误差、通过数、连续分 |
| T2 / `ode` | 从含噪轨迹辨识二维多项式动力学 | 向量场与轨迹误差、模型复杂度、通过数 |
| T3 / `poisson` | 求解稀疏 SPD 系统并优化完整执行性能 | 数值正确性、完整批次耗时、相对 Jacobi-CG 的加速比 |

所有组使用相同公共任务契约、数据、工具、模型和预算，只改变方法指导：

| 组别 | 条件 |
|---|---|
| G1 | 详细方法指导 |
| G2 | 只给方法方向 |
| G3 | 无额外方法指导，仍提供共同任务契约 |

- 最低覆盖：3 任务 × 3 组，各一次，共 9 格。
- **当前已冻结主计划：15 个独立会话。** T1 每组 3 次，共 9 次；T2、T3 每组各 1 次，各 3 次。
- 原设计中的 27 次是可选扩展，未纳入当前冻结计划。不能自动扩展，也不能无说明地降为 9 次。
- 每会话保存全部尝试、首次有效候选、最终候选、公开反馈、模型用量和可信执行证据。
- 研究结束后，在同一隐藏集上重放 11 种作者方法及研究的 first/final，形成组间、固定参考和迭代变化分析。

结论范围限于上述三类任务。T2/T3 每组 n=1 只支持描述性比较，T1 每组 n=3 仍属探索性结果；first→final 变化不能单独证明反馈的因果收益。S3 不与 S1/S2 直接平均。

原始实施契约：[design/execution-plan-v0.3.md](../../design/execution-plan-v0.3.md)。其中“未完成”描述是 2026-10-22 设计时点的状态；当前进度以本文及最新证据为准。

## 3. 六项正式待办的当前状态

| 项目 | 状态 | 已有结果 / 剩余工作 |
|---|---|---|
| 1. 正式资源验收 | **完成** | 15/15 通过；三种 R 镜像实际 4 vCPU / 4 GiB；R/W 并发压力、真实 4 GiB OOM、分类和恢复均有证据 |
| 2. T3 三组正式校准 | **完成** | 三组 BCCBBC，216/216 数值检查；LU 加速比 2.250× / 2.227× / 2.213×；冻结 `efficiency_gate_1.5` |
| 3. 正式冻结 | **完成** | 三任务与 15 会话计划均为 `frozen`；Flash 版本、参数、源码、镜像、数据、评分、提示、工具、顺序已绑定 |
| 4. 三组真实研究 | **未执行** | 当前 0/15 会话、0/9 格；按冻结顺序启动，保留所有失败 attempt |
| 5. 隐藏测试重放 | **未执行** | 11 作者方法与各研究 first/final；heat/ode 各三次，T3 完整计时；需新独占窗口 |
| 6. 正式分析与交付 | **程序已有，数据未齐** | 待正式结果后生成对比、成本、失败与局限分析，完成归档；本轮资源/冻结改动尚未发布 |

### 3.1 已完成的基础工作，不应重新列为待办

- 三任务数学核查、接口、公开 checker、私有 scorer、Harbor/Pi 与可信登记/W/J 执行链路。
- 90 例生成与 GT QC：每任务 6 public-dev、12 author-calibration、12 final-test；同熵重建验证。
- 11 种作者方法的校准，共 132 个方法×实例记录；保留弱方法的正常失败。
- 评分负例、隔离、限网、快照、预算、进程树与计时探针；当前冻结源码的 **348 项测试通过**，另有 2 条既有 Harbor 弃用提示。
- 多轮真实模型 pilot、原生 Harbor Trial、干净源码与新依赖环境重放。它们是联调与可复现证据，不计入正式研究。
- 三任务三组提示的 9 组逐字差分及哈希归档。
- 历史 GitHub 发布。当前本地 Git HEAD 为 `cbaf82a800f46544faf66e9eed5c885b3ecab677`；之后的资源、计时修复、Flash 切换与正式冻结仍包含未提交修改和新文件。

### 3.2 已有证据的具体边界

1. **资源已验收，不等于后续负载自动合格。** Colima 配置为 6 vCPU / 10 GiB，Docker 实际约 9.69 GiB。R 与 W 分别逐页写入 3.75 GiB 的并发压力通过；另一 W 达到精确 4 GiB 上限并触发 OOM，`oom=1`、`oom_kill=1`、退出 137，可信分类为有效科学失败、score/reward=0。
2. **T3 校准已正式通过，但不是模型成绩。** 校准使用作者 Jacobi-CG/LU 和 author-calibration。005 窗口连续观察已结束，后续隐藏重放不能复用其旧时间窗口；拒绝的 001–004 及修复过程已保留。
3. **Flash 接线已验收，但尚无正式科学结果。** 新 Flash 原生 smoke 的 12/12 次请求成功，一个有效候选通过执行链路；未显式 finalize，按 `deadline_fallback` 选取，first/final 相同，pilot 分数 43.221、reward=0。ODE/Poisson 采用共用模型链路实测加各自 R 镜像离线策略捕获，不代表已跑它们的真实研究。
4. **正式控制器和报告已实现，但完整正式矩阵尚未实跑。** 真实运行中仍需核对登记关闭、退出分类、日志、清理和重试关系，不能只看进程退出码。
5. **干净依赖环境复现已完成，第二台物理主机不是额外硬门槛。** 现有归档未包含全部私有数据数组，数据仍在本机 `authoring/data/`，由 freeze 哈希绑定；仅下载 GitHub 或解压证据包不足以恢复全部本地运行条件。

## 4. 已冻结配置：新会话直接沿用

| 项目 | 固定值 |
|---|---|
| 正式运行计划 | `freezes/research-run-plan-formal-001.json` |
| Plan ID | `research-5db960ec2eb8d256` |
| 模型 | DeepSeek-V4.1-Flash-1017；API 标识 `deepseek-flash` |
| API | Anthropic Messages；`https://api.deepseek.com/anthropic` |
| 采样 | temperature=0、thinking=disabled、top_p=1、stream=true |
| 输出预算 | 每请求最多 4096 token；每会话累计 32768 token |
| 研究预算 | 1800 秒、20 次已接受的公开评估、solver seed=0；不 resume，无 max-turns 扩展 |
| R / W | R 4 vCPU / 4 GiB；W 1 vCPU / 4 GiB、禁 swap、数值线程 1 |
| Pi / Harbor | Pi 0.84.1；Harbor commit `38b9be0164a910015a0be9a37ba6e8e78c562dfe` |
| 数值依赖 | Python 3.12.12、NumPy 2.2.6、SciPy 1.15.3 |
| 工具 | read / bash / edit / write；额外 skills、extensions、MCP 为空 |
| 数据根目录 | `authoring/data/v0.3-local`；沿用既有 90 例，不重新生成 |
| 评分 | heat/ode 为 accuracy；poisson 为 `efficiency_gate_1.5` |
| T3 通过条件 | 12/12 正确且相对固定 Jacobi-CG 的完整批次 speedup ≥ 1.5；其余规则见任务 freeze |

三 R 镜像与数值镜像均按不可变 SHA256 ID 冻结。完整值读取任务 freeze 和[环境核对记录](../logs/formal-freeze-local-001/environment-inspection.json)，不要重新构建或用可变标签替换。49 个可信 Python 文件、任务公共包、提示与实际工具 schema 均有哈希绑定。

模型由 Pro 切换为 Flash，只影响模型接线与相关验证；数值求解、评分、资源和 T3 证据继续适用。旧 Pro pilot 保留原身份，不能与 Flash 合并为正式组间或模型比较。供应商版本是公开别名映射；若发现映射漂移，停止新增正式会话并按新协议版本处理。

## 5. 固定的 15 会话顺序

下表后缀接在 `research-5db960ec2eb8d256-` 后即为完整 run ID；实际 session ID 和工作目录以正式计划 JSON 为准。

| 序号 | run ID 后缀 |
|---:|---|
| 1 | `heat-g2-r1` |
| 2 | `heat-g3-r1` |
| 3 | `heat-g1-r1` |
| 4 | `ode-g1-r1` |
| 5 | `ode-g2-r1` |
| 6 | `ode-g3-r1` |
| 7 | `poisson-g3-r1` |
| 8 | `poisson-g2-r1` |
| 9 | `poisson-g1-r1` |
| 10 | `heat-g3-r2` |
| 11 | `heat-g1-r2` |
| 12 | `heat-g2-r2` |
| 13 | `heat-g3-r3` |
| 14 | `heat-g1-r3` |
| 15 | `heat-g2-r3` |

按此顺序串行执行，每次新工作目录、新 Pi session、新 relay。15 次研究预算合计最多 7.5 小时，另加准备、关闭、允许的基础设施重试和隐藏重放；这不是完成时间承诺。实际成本用日志报告，未知金额写 null。

## 6. 新会话的执行步骤

### A. 接手与启动前检查

**新开干净聊天，继续使用当前目录 `/Users/baixiongfei/Documents/Projects/build_bench/benchmark`。** “干净”指新对话及每次独立研究上下文；当前工作区包含冻结所需的未提交改动和本地证据，不要 reset、clean、切回旧提交或直接用新的 clone 代替。

1. 先读本文、[冻结说明](formal-freeze-2026-10-23.md)、[控制器说明](study.md)、[资源/T3 验收](resource-timing-acceptance-2026-10-23.md)。冻结清单和机器可读日志优先于旧报告中的历史状态。
2. 核对当前 plan、三任务 freeze、源码、镜像、数据、Pi/Harbor 版本。不要重新运行 draft/freeze 生成器或重排顺序。
3. 检查 `research-runs/research-5db960ec2eb8d256/manifest.json` 是否已有记录。本文编写时 `research-runs/` 尚不存在；以后接手必须以实际 ledger 为准，防止重复启动。
4. 核对 Docker/Colima 实际资源和 VM boot ID；保持其他容器停止。用户已授权暂停其他容器，原先运行的 8 个服务此前已停止、数据卷保留。冻结结束时运行容器为 0，这不是对以后状态的保证。
5. 确认专用模型凭据可供可信代理使用，只检查是否可用，不打印、不写入仓库或提示。保持供电和环境稳定；T3 隐藏计时前须另外验收连续独占窗口。
6. 运行冻结校验；只有通过后启动。校验失败先记录并排查原因，不绕过守卫或手改哈希使其通过。

```sh
cd /Users/baixiongfei/Documents/Projects/build_bench/benchmark
.venv/bin/python -m runner.run_plan validate \
  --plan freezes/research-run-plan-formal-001.json
```

此前保存结果为 `{"blockers":[],"formal_ready":true}`，退出码 0。源码未变化时不必为交接重复整套单测、资源压力或三组校准；现场资源/计时资格仍须按入口重新核验。VM 重启等变化使旧资源身份不匹配时，必须处理证据适用性，不能改写原证据。

### B. 顺序执行 15 次正式研究

首个会话命令：

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study start \
  --plan freezes/research-run-plan-formal-001.json \
  --run-id research-5db960ec2eb8d256-heat-g2-r1
```

后续依第 5 节替换 run ID，每次核对 ledger 与该次结果后再继续：

- 研究阶段只使用 public-dev；科学 score/reward 应保持 null，登记核验通过不等于隐藏科学通过。
- 保留全部候选、first/final、请求、用量、退出与清理证据。无显式 finalize 时只按冻结 fallback 规则处理，不替模型挑选更优候选。
- 正常结束或正常超时的会话不能因为没有候选、零分或表现差而重跑。正常无提交按协议记科学失败，不伪造 first/final。
- 纯 API/基础设施失败只算 attempt，不能算完成科学评测。协议支持 `--retry-of <最新失败 attempt ID>` 的显式关联重试，但用户最新要求不再过多重试；本次执行从该指令起不新增自动重试。原失败保留，若因此无法通过完整研究门槛，应如实说明，不绕过门槛或改写分类。
- 若进程中断留下未决 ledger，先调查并按协议恢复；不要删记录后重启，也不要自动把它改成成功或正常失败。

### C. 完成研究后，执行隐藏重放

本次交接采用清晰顺序：**全部 15 会话有效完成研究后，再集中启动 final-test。** 控制器至少要求同任务所有预声明研究结束并关闭 registry（heat 9 次、ode 3 次、poisson 3 次）；首个隐藏重放会关闭该任务继续研究的入口。

| 对象 | 需要执行 |
|---|---|
| heat 作者方法 | `ls`、`rank5`、`tikhonov`、`discrepancy`、`tsvd`；固定参考为 `tikhonov` |
| ode 作者方法 | `raw`、`fixed`、`search`；固定参考为 `fixed` |
| poisson 作者方法 | `cg`、`jacobi`、`lu`；固定参考为 `lu` |
| 各正式研究 | 首次有效与最终候选；相同源码哈希明确复用同一检查点结果 |

heat/ode 每个方法或检查点各三次独立重放。T3 每个方法或检查点执行一个完整 **B,C,C,B,B,C** 组（B 为固定 Jacobi-CG，C 为待测方法）；它已经内含双方各三次，不再外套三组。

已核实的 heat 命令示例，其他任务/方法依相同入口执行：

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study baseline \
  --plan freezes/research-run-plan-formal-001.json \
  --task heat --method tikhonov \
  --data authoring/data/v0.3-local

PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study final \
  --plan freezes/research-run-plan-formal-001.json \
  --run-id research-5db960ec2eb8d256-heat-g2-r1 \
  --data authoring/data/v0.3-local
```

**T3 的新独占窗口尚待建立。** 后续 Poisson 的 baseline/final 命令都必须额外提供 `--timing-contract <新验收合同路径>`。按[计时说明](timing.md)和已验收的 `tests/accepted_t3_calibration.py` / `logs/t3-formal-calibration-local-005/controller.py` 中宿主观察策略，为实际隐藏重放持续收集负载、swap、缓存状态、VM 身份和 Docker 事件证据。现有脚本是校准入口，不能直接当作隐藏重放入口；需要让连续观察覆盖实际 final/baseline 操作并保存新合同及结束验收，不能只编辑旧合同的时间。

计时无效保留 correctness 与 null 性能，不把诊断样本升级为正式结果。只有原协议允许的基线不稳定情形，完成干扰调查后才可进行一次有父记录的完整重测；所有组与失败均保留。隐藏结果不能进入研究容器、修改提示或决定再跑一个会话。

### D. 正式分析、验收和交付

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study_report \
  --project . \
  --plan freezes/research-run-plan-formal-001.json \
  --manifest research-runs/research-5db960ec2eb8d256/manifest.json \
  --output results/formal-study-001
```

输出目录若已存在，应另选新目录，不覆盖证据。报告生成成功只是一步，最终还需核对：

- 15 次研究、9 格覆盖和全部失败 attempt 的分母；11 个作者方法是否都有可追溯最终结果。
- 各任务 G1/G2/G3、相对固定参考、first→final 改善/退化/不变、逐例误差与通过数。
- API/token、墙钟、评估次数、候选与基线 CPU 成本；首次有效之后新增成本；未知成本为 null。
- 正常科学失败、API/基础设施失败、可信评分故障、性能测量无效分别统计；无迭代就明确“未观察到迭代收益”。
- 所有规定重放及新 T3 窗口证据齐全后，再形成正式结论、更新 README/结果/局限，保存源码、候选、清单、逐例表和归档哈希。
- 本轮尚未提交/发布。实际推送与对外发布在获得相应授权后执行；不把本地归档写成已发布。

## 7. 证据与接手文件索引

| 用途 | 文件 |
|---|---|
| 正式计划 | [research-run-plan-formal-001.json](../freezes/research-run-plan-formal-001.json) |
| 三任务 freeze | [heat](../freezes/heat-formal-001.json)、[ode](../freezes/ode-formal-001.json)、[poisson](../freezes/poisson-formal-001.json) |
| 完整冻结交付清单 | [formal-freeze-local-001.json](../freezes/formal-freeze-local-001.json) |
| 资源验收 | [15/15 汇总](../logs/resource-acceptance-local-002/summary.json)、[证据清单](../freezes/resource-acceptance-local-001.json) |
| T3 正式校准 | [005 验收](../logs/t3-formal-calibration-local-005/acceptance.json)、[性能 profile](../freezes/t3-profile-local-001.json) |
| Flash 策略 / smoke | [策略目录](../logs/model-policy-capture-flash-local-001)、[smoke 结果](../logs/harbor-native-flash-pilot-001/result.json) |
| 当前测试 / 校验 | [348 测试日志](../logs/formal-freeze-local-001/model-switch/unit-tests.txt)、[冻结校验](../logs/formal-freeze-local-001/cli-validation.json) |
| 冻结源码快照 | [227 文件清单](../logs/formal-freeze-local-001/source-snapshot-manifest.json) |
| 资源与 T3 原始归档 | [evidence.tar.gz](../logs/resource-t3-delivery-local-001/evidence.tar.gz)、[integrity.json](../logs/resource-t3-delivery-local-001/integrity.json) |
| 正式冻结与 Flash 归档 | [evidence.tar.gz](../logs/formal-freeze-delivery-local-001/evidence.tar.gz)、[integrity.json](../logs/formal-freeze-delivery-local-001/integrity.json) |

旧 `docs/results.md`、`results/stage-status.json`、draft-007 和 Pro pilot 保留各自历史范围。正式冻结以当前工作树字节和已归档哈希为准；新文档不会改写旧归档。

## 8. 可复制到新会话的启动说明

```text
请接手 SciResearch-Bench-Lite v0.3 的正式执行阶段。

工作目录：/Users/baixiongfei/Documents/Projects/build_bench/benchmark
先读：docs/execution-handoff-2026-10-23.md
再读：docs/formal-freeze-2026-10-23.md、docs/study.md、docs/timing.md
正式计划：freezes/research-run-plan-formal-001.json

当前资源验收、T3 三组校准和正式冻结已完成，模型统一为
DeepSeek-V4.1-Flash-1017（deepseek-flash）。交接时正式研究为 0/15，
隐藏成绩未运行。请先检查实际 ledger 与现场环境，避免重复启动。

请完成启动检查后按冻结顺序串行执行 15 个正式会话；全部研究结束后，
完成 11 个作者方法和各研究 first/final 的隐藏重放，再生成正式分析与归档。
T3 隐藏重放必须建立新连续观察独占窗口，不能复用校准 005 的旧时间窗口。

保留当前未提交文件、本地私有数据、所有失败与重试关系，不重新生成计划、
改模型/提示/阈值/数据、覆盖证据或 reset 工作区。每个研究使用新 Pi session。
已授权暂停其他容器；真实阻塞要说明原因，不能降低验收要求。
本次执行不包含 GitHub 发布，发布前另行确认。
```

此段供用户在新会话中发送后作为该会话的任务指令；本次文档整理没有执行上述正式命令。
