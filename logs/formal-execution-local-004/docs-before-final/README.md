# SciResearch-Bench-Lite v0.3

当前正式执行已切换至[每会话 200,000 输出 token 的第三版冻结](docs/budget-freeze-2026-10-23.md)。第三版研究已有效关闭 15/15，其中 9 次保留 first/final；6 次达到预算后无有效提交，保留正常失败。全部研究与资源清理已核验，正在执行统一隐藏重放，后续不新增自动重试；见[当前状态与恢复入口](docs/execution-status-2026-10-23.md)。隐藏重放和最终结论尚未完成。

正式执行已采用[第二版冻结与原生压缩修复](docs/compaction-freeze-2026-10-23.md)，15 会话矩阵正在执行。第一版两个失败 attempt 完整保留。

2026-10-23 正式执行进展：启动核验通过，首个 run 的两次关联 attempt 均因 Pi 原生上下文压缩请求与冻结策略冲突而失败。当前 **0/15 有效研究会话，隐藏重放未启动**；原始证据已保存，最小修复原型通过 12 项离线检查，待批准新冻结版本。见[执行阻塞与修订方案](docs/execution-blocker-2026-10-23.md)。下文冻结前与 pilot 的描述保留其历史范围。

三条合成科学计算任务：热方程逆恢复、二维多项式动力学辨识、稀疏 SPD 系统求解优化。实现依据 [执行契约的只读副本](docs/execution-plan-v0.3.md)，原设计和三个参考仓库未被本实现改写。副本中的相对证据链接沿用原 `design/` 树与本地参考仓库布局，保留其来源，不保证在独立GitHub仓库中可打开。

**本机实现、校准、隔离功能探针、真实模型到独立评分的pilot链路及干净源码和新依赖环境重放已完成；正式 Benchmark 验收尚未完成。** 已生成90例并通过GT QC，11个作者方法通过统一W/J执行；固定T1、T2、T3参考各12/12通过校准。刻意零解pilot经三次W/J得0分；后续真实研究候选在pilot-smoke三次均3/3通过、得87.693分，但未显式finalize，first/final同一源码，没有迭代收益证据。各次基础设施失败均保留。正式三组研究仍为0格、0会话，final-test求解成绩均未查看，正式研究的T3加速比尚不可报告；作者校准的正式性能结果见下方2026-10-23更新。远端已核验至 `536c0d9`；`0a84f0c` 的证据与后续基线代码均在用户明确批准后公开推送。[发布记录](logs/publication-local-003/result.json)保留这次核验的具体提交。完整结果见 [结果报告](docs/results.md)和[本机交付记录](freezes/local-delivery-004.json)。

[完整 Harbor Trial 与模型代理 pilot](docs/native-relay-pilot.md)已连续两次成功：最新002的8次模型请求全部成功，显式evaluate/finalize，三次pilot重放均3/3通过、89.302分；first/final仍同一源码。已验证实际请求哈希门禁、用量额度和DNS出口限制，不能记作正式实验格。正式入口与结果汇总见[研究控制器](docs/study.md)，包括11方法正式基线入口和相对固定参考的逐会话/逐组/逐例对照；这些新增路径已用合成测试验证，尚未运行正式隐藏重放。可信进程计时与三组诊断见[计时说明](docs/timing.md)。

2026-10-23 更新：[正式资源验收](docs/resource-timing-acceptance-2026-10-23.md)已通过 15/15，含真实 4 GiB OOM；T3 三组独占校准通过，LU 加速比 2.250×／2.227×／2.213×，冻结 `efficiency_gate_1.5`。下方历史校准、pilot 和单测记录保留原范围。

同日后续：[三任务正式冻结已完成](docs/formal-freeze-2026-10-23.md)，全部15会话统一使用 **DeepSeek-V4.1-Flash-1017**（API：`deepseek-flash`）。新Flash原生smoke完成12次成功请求；正式计划校验 `formal_ready=true`，正式研究仍为0会话。

## 当前验收状态

| 项目 | 实际状态 | 证据 |
|---|---|---|
| 三任务生成与独立QC | 90/90；各任务6 dev、12 calibration、12 final | `authoring/data/v0.3-local/private/`、[动态汇总](results/stage-status.json) |
| 同熵数据重建 | 同Linux镜像，369个公开输入文件逐字节一致 | [重建记录](freezes/data-reproduction-local.json) |
| 作者基线 | 11方法、132个方法×实例记录；保留弱基线失败 | [新版worker校准](results/calibration-local-002/summary.json)、[132例与旧版完全一致](logs/calibration-worker-replay-local-002.json)、[CSV](results/cases/calibration.csv) |
| 干净源码与新依赖环境 | 提交28da96e的Git archive、新site-packages、新W/J；三任务参考和最新真实候选各3/3通过，T3分数null；同宿主/Python二进制/数值镜像 | [重放002](logs/clean-replay-local-002/result.json)、[依赖记录](logs/dependency-rebuild-local-001/result.json) |
| 保存的单测结果 | 当前工作源码348通过；此前新依赖环境归档源码328通过，各有2条Harbor弃用提示 | [当前Flash源码](logs/formal-freeze-local-001/model-switch/unit-tests.txt)、[新环境归档](logs/clean-replay-local-002/archived-unit-tests.txt) |
| W隔离与资源 | 完整回归11/11、计时探针5/5；新增真实4GiB OOM及资源验收15/15通过 | [边界](docs/protocol.md)、[worker005](logs/runtime-probes-005/summary.json)、[timer004](logs/process-timer-probe-004/summary.json) |
| 真实模型与独立评分 | 零解pilot为0分；研究pilot001按fallback选出的候选，经真实Harbor hook/W/J三次各3/3、87.693分，无迭代 | [零解W/J](logs/pilot-model-registry-wj-001/result.json)、[研究pilot](logs/research-loop-pilot-001/result.json)、[独立评分003](logs/research-loop-pilot-001-wj-replay-003/result.json) |
| R限网 | 非root/ALL-drop配置005通过所测URL、socket与宿主边界检查；未运行Pi | [网络005](logs/research-network-probe-005/result.json)、[全部attempt](docs/harbor-integration.md) |
| 三个R镜像 | 实际构建与8/8启动检查；另完成三个镜像的正式4 vCPU/4 GiB配额、CPU节流实测 | [镜像检查](logs/research-images-local-001/result.json) |
| 受控桥 | localhost7项、R文件桥两轮各9项通过；文件桥包含真实W、6例公开反馈与不可改写快照，未调用模型 | [localhost](logs/bridge-runtime-001/result.json)、[文件桥001](logs/file-bridge-runtime-001/result.json)、[回归002](logs/file-bridge-runtime-002/result.json) |
| 完整原生Harbor Trial | **两次本机pilot通过**；最新8次可信模型请求、显式finalize、三次W/J、资源清理已核对 | [最新pilot002](logs/harbor-native-pilot-002/result.json)、[完整说明](docs/native-relay-pilot.md) |
| 正式资源 | **资源探针已通过**；Docker 6 vCPU／约9.69 GiB，R/W并发压力与真实4GiB OOM通过；T3独占计时窗口也已通过 | [验收002](logs/resource-acceptance-local-002/summary.json)、[范围与证据](docs/resource-timing-acceptance-2026-10-23.md) |
| T3正式校准 | **三组通过**；216/216数值检查，冻结 `efficiency_gate_1.5`；非模型研究成绩 | [结果与范围](docs/resource-timing-acceptance-2026-10-23.md)、[冻结](freezes/t3-profile-local-001.json) |
| 正式任务冻结 | **完成**；三任务及15会话计划为frozen，Flash版本/参数、镜像、数据、评分、提示、工具、顺序均绑定 | [冻结说明](docs/formal-freeze-2026-10-23.md)、[正式计划](freezes/research-run-plan-formal-001.json) |
| 三任务×三组研究 | **0个正式格**；最低9格，主计划15会话 | [未完成事项](#仍需完成) |
| 隐藏重放与正式性能 | **未完成**；不把校准或pilot记成final | [局限](docs/limitations.md) |
| 个人GitHub发布 | 用户明确批准后，已核验远端提交 `536c0d9`，包含 `0a84f0c` 的证据与正式基线入口/报告；可见性为PUBLIC | [仓库](https://github.com/bxf1/sciresearch-bench-lite)、[远端HEAD](logs/github-remote-head-local-003.txt)、[最新仓库元数据](logs/github-repository-local-003.json) |

## 文件与执行边界

`authoring/` 为作者生成器和私有GT，`baselines/` 为11个只读公共输入的方法，`public/` 为公开诊断与所有组共享的T3 Jacobi-CG比较器，`judge/` 为独立数值评分，`runner/` 为登记/源码快照/W/J/Harbor桥，`prompts/<task>/` 保存共同契约和三组指导。`tasks/` 是三个可由真实Harbor TaskConfig解析的准备包，各仅含6例公开dev、公共helper/checker及格式工具；默认 `tests/test.sh` 故意失败，防止未经可信verifier生成reward。私有材料不能作为R或W镜像上下文。

仓库包含源码、公共任务包、日志与结果；`authoring/data/` 的私有生成数据和GT数组未提交。新clone可按下方生成命令准备数据，原90例的根熵与GT仍留在作者本机。公开生成器/GT后不能声称永久保密或无训练污染。

候选入口为 `python solve.py --input /input --output /output --seed 0`。输出必须是规定的数值文件。可信评估在独立W执行已登记快照；R可自行做公开实验，J不执行或import提交代码。任务和格式见 [任务卡](docs/task_cards.md)，具体安全边界见 [协议](docs/protocol.md)。

## 运行已有实现

以下命令在仓库根目录（当前本地 `benchmark/`）执行，使用独立 `.venv`；现有目录不会被生成/校准命令覆盖。重新运行时选择新的输出目录。

```sh
export PYTHONPATH=.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1

.venv/bin/python -m pytest -q tests
.venv/bin/python -m runner.preflight --output logs/preflight-new.json
.venv/bin/python -m runner.report
```

测试不要求正式模型调用；具体测试数量和结果以该次输出/保存日志为准。`runner.report` 只读取作者校准、生成QC及明确标记的pilot状态/分数，重建CSV/派生报告，不修改原日志或读取隐藏求解成绩。

准备15次研究顺序可用 `.venv/bin/python -m runner.run_plan draft --output freezes/research-run-plan-new.json`；它只写 `status=draft`，不创建研究会话。`validate --plan <文件>` 在缺少完整freeze、参数实测、固定R镜像或文件哈希已变时返回非零。温度不受支持或服务未公开模型修订可明确记null，但必须给出原因和有哈希的验证证据；普通未决null不能启动。所有会话仍固定30分钟、20次公开评估和solver seed0。

重新生成一套**新数据**或重建已有根熵（私有根熵不能挂载到R/W）：

```sh
.venv/bin/python -m authoring.generate --output authoring/data/new-local
.venv/bin/python -m authoring.generate \
  --entropy-file authoring/data/v0.3-local/private/generation.json \
  --output authoring/data/same-entropy-new
```

生成仅执行预声明GT检查，不调用逆求解器选择实例。`--smoke` 生成每任务每档一个pilot实例；这些不能代替正式split。严格复现数值版本时应在同一固定Linux镜像内生成；本机Python生成可用于功能检查。

构建数值镜像并运行全部作者校准（Docker必须可访问；不会停止已有服务）：

```sh
docker build -t sciresearch-numeric:0.3.0 environment
.venv/bin/python -m runner.calibrate \
  --data authoring/data/v0.3-local \
  --output results/calibration-local-new \
  --image sciresearch-numeric:0.3.0
.venv/bin/python -m runner.report \
  --calibration results/calibration-local-new/summary.json
```

校准按heat 5种、ode 3种、poisson 3种依次执行。每个方法的W/J容器配置、输入/代码/镜像标识、全部case指标和资源日志保留在输出目录。它不会自动冻结正式性能profile。

重放单个作者方法到新输出目录：

```sh
.venv/bin/python -m runner.replay --task heat --source baselines/heat \
  --input authoring/data/v0.3-local/inputs/heat/author-calibration \
  --truth authoring/data/v0.3-local/private/heat/author-calibration \
  --output results/heat-reference-new --method tikhonov
```

运行W探针时使用新目录；包含约256 MiB/64 MiB的tmpfs配额测试，但不实施真实4 GiB OOM压力：

```sh
.venv/bin/python tests/runtime_probe.py --output logs/runtime-probes-new
```

`reproduce.sh` 默认执行测试，支持以下四个本机入口；它不代表已在第二台干净机器完成复现：

```sh
./reproduce.sh test
./reproduce.sh preflight logs/preflight-another.json
./reproduce.sh generate authoring/data/another-new
./reproduce.sh calibrate authoring/data/v0.3-local results/calibration-another-new
```

已保存正式[15会话运行计划](freezes/research-run-plan-formal-001.json)及 [T1](freezes/heat-formal-001.json)、[T2](freezes/ode-formal-001.json)、[T3](freezes/poisson-formal-001.json) freeze。全部采用DeepSeek-V4.1-Flash-1017，沿用007草稿的独立顺序熵和session ID，先覆盖九格，再补T1两轮，每次1800秒/20次/seed0。资源、T3、模型参数、三个R镜像、实际系统提示/工具JSON与49个可信源码文件均已绑定；[校验记录](logs/formal-freeze-local-001/validation.json)确认15个会话配置可构造，但未启动正式会话。

```sh
.venv/bin/python -m runner.run_plan validate --plan freezes/research-run-plan-formal-001.json
```

本次返回退出码0。旧[007草稿](freezes/research-run-plan-local-draft-007.json)及Pro pilot保留为历史证据；新模型smoke和模型切换影响见[正式冻结说明](docs/formal-freeze-2026-10-23.md)。

## 环境

数值依赖为 Python 3.12.12、NumPy 2.2.6、SciPy 1.15.3。镜像基底钉住digest，实际运行image ID写入每个结果。本地Harbor为0.24.0、commit `38b9be0164a910015a0be9a37ba6e8e78c562dfe`，Pi pilot记录0.84.1。不要用可变latest标记正式复现。

从Python3.12环境重建宿主依赖，且相邻 `../harbor` 已检出上述commit时：

```sh
python3.12 -m venv .venv
sed '/^harbor[ @=]/d' freezes/host-requirements.lock | .venv/bin/python -m pip install -r /dev/stdin
.venv/bin/python -m pip install --no-deps ../harbor
```

以上命令过滤锁文件中单独的Harbor条目，并安装相邻固定源码；不要用同版本号的未知构建替代该commit。没有相邻checkout时，最后一步可改为 `.venv/bin/python -m pip install --no-deps 'git+https://github.com/harbor-framework/harbor.git@38b9be0164a910015a0be9a37ba6e8e78c562dfe'`。新site-packages重建和重放已实际通过，见[新依赖环境记录](logs/dependency-rebuild-local-001/result.json)；复用了同一宿主、Python二进制和数值镜像。模型凭据由授权的专用运行环境提供；不要写进配置、镜像、提示、日志或版本控制。模型端点和实际请求证据见 [集成说明](docs/harbor-integration.md)。

## 仍需完成

资源验收和T3三组正式校准已完成，见[验收报告](docs/resource-timing-acceptance-2026-10-23.md)及[性能冻结记录](freezes/t3-profile-local-001.json)。Colima为6 vCPU／10 GiB，原8个容器按授权保持停止。

模型与整体任务冻结也已完成，见[正式冻结说明](docs/formal-freeze-2026-10-23.md)。

1. 在正式环境完成至少3任务×3组各一次，主目标15个独立会话；失败attempt全部保留，当前正式会话仍为0。
2. 对11个作者基线和每次研究的first/final运行final-test；heat/ode各三次，T3使用新的独占窗口及完整BCCBBC协议。隐藏成绩不得回流研究。
3. 用正式数据生成三组与固定基线对照、首次→最终变化、成本和失败分析，归档正式结论；S3不与S1/S2直接平均。

新依赖环境复现已完成：[清洁重放002](logs/clean-replay-local-002/result.json)。第二台物理主机不是计划的额外硬门槛；正式研究与隐藏性能重放仍须补齐。已按[官方模型表](https://api-docs.deepseek.com/quick_start/pricing/)复核 `deepseek-flash` 对应 `DeepSeek-V4.1-Flash-1017`，见[冻结前取证](logs/model-policy-documentation-local-003/result.json)。旧Pro pilot保留原身份；公开别名映射不能证明不可变服务端二进制。

[调研对应关系](docs/survey.md) · [任务卡](docs/task_cards.md) · [协议](docs/protocol.md) · [结果](docs/results.md) · [局限](docs/limitations.md)

最新远端核验时仓库为公开状态；初次创建/检查的私有记录仍保留。源码28da96e完成了328项工作/新依赖归档测试，随后修正报告读取最新仓库可见性的逻辑，对应回归：[27项通过](logs/publication-report-unit-local-001.txt)。本轮另补正式基线编排与对照报告；执行器、I/O、计时、算法与科学指标未变化。

三组提示的[逐字差分归档](logs/prompt-diffs-local-001/manifest.json)保留三任务各G1/G2/G3两两对照，共9组；同时提供行差分、Unicode字符编辑及原文哈希，9组均验证可逐字节重建目标提示。提示原文未改动，未估算token数冒充真实模型用量。
