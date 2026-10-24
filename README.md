# SciResearch-Bench-Lite

科学计算 Auto Research Benchmark：热逆问题、动力学辨识与稀疏求解优化。

**[提交报告](docs/submission-report-2026-10-24.md)** · **[Benchmark 调研与逻辑图](docs/survey.md)** · **[复现指南](docs/reproduction.md)** · **[50 万 token 补充实验](docs/supplemental-results-2026-10-24.md)**

2026-10-24 当前状态：三任务共 90 例数据完成生成与 QC；11 种作者基线、15 次原正式研究及全部隐藏评分操作已执行。原批次 9 次有提交、6 次正常无提交，有效评分 14/15（包括零分）；Poisson G2 计时无效留空。各任务均有端到端 Agent 评测，原结果满足三任务基线与至少一条端到端验证的交付要求。

用户授权的补充批次在 2026-10-24 12:10 因供应商 HTTP 402 中止：仅补跑原 6 个无提交会话，每会话 500,000 输出 token、无研究总墙钟上限；Poisson G2 仅重放原候选。首个恢复会话已知输出 60,285 token、无提交；余下五个会话未启动，详情见补充报告。原结果保持不变。补跑是选择性新批次，不能合并为等预算指导比较。

[原正式结果与成本](docs/formal-results-2026-10-23.md) · [机器可读结果](results/formal-study-003/summary.json) · [失败诊断](docs/submission-diagnosis-2026-10-23.md) · [数据卡](docs/task_cards.md)

## 快速验证

```bash
# Python 3.12 + Docker；完整依赖安装步骤见复现指南
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m authoring.generate --output authoring/data/new-local
# 生成完整三任务数据和 QC；不会调用模型
```

作者基线、可信评分、固定依赖、模型入口、历史证据和完整数据的使用方法见[复现指南](docs/reproduction.md)。不要直接用默认 Harbor test.sh 作为正式评分：它有意拒绝缺少可信登记的运行。

## 历史验收记录（2026-10-23 及此前）

以下记录保留原时间范围；其中“未发布”“尚未运行”等文字不能覆盖上面的当前状态。

## 正式执行前的实现与 pilot 证据

下表中的生成、校准、隔离、pilot 与干净环境记录保留各自历史范围。90 例 GT QC、11 方法校准、真实模型接线和同宿主新依赖环境重放均已完成；它们不替代上方的正式 final-test 结果。历史发布以[既有发布记录](logs/publication-local-003/result.json)为限，不代表本轮内容已发布。

## 当前验收状态

| 项目 | 实际状态 | 证据 |
|---|---|---|
| 三任务生成与独立QC | 90/90；各任务6 dev、12 calibration、12 final | `authoring/data/v0.3-local/private/`、[动态汇总](results/stage-status.json) |
| 同熵数据重建 | 同Linux镜像，369个公开输入文件逐字节一致 | [重建记录](freezes/data-reproduction-local.json) |
| 作者校准（历史） | 11方法、132个方法×实例记录；保留弱基线失败 | [新版worker校准](results/calibration-local-002/summary.json)、[132例与旧版完全一致](logs/calibration-worker-replay-local-002.json)、[CSV](results/cases/calibration.csv) |
| 干净源码与新依赖环境 | 提交28da96e的Git archive、新site-packages、新W/J；三任务参考和最新真实候选各3/3通过，T3分数null；同宿主/Python二进制/数值镜像 | [重放002](logs/clean-replay-local-002/result.json)、[依赖记录](logs/dependency-rebuild-local-001/result.json) |
| 保存的单测结果 | 第三版冻结源码357通过；历史新依赖环境归档源码328通过，各有2条Harbor弃用提示 | [第三版冻结源码](logs/formal-freeze-local-003/unit-tests-final.txt)、[新环境归档](logs/clean-replay-local-002/archived-unit-tests.txt) |
| W隔离与资源 | 完整回归11/11、计时探针5/5；新增真实4GiB OOM及资源验收15/15通过 | [边界](docs/protocol.md)、[worker005](logs/runtime-probes-005/summary.json)、[timer004](logs/process-timer-probe-004/summary.json) |
| 真实模型与独立评分 | 零解pilot为0分；研究pilot001按fallback选出的候选，经真实Harbor hook/W/J三次各3/3、87.693分，无迭代 | [零解W/J](logs/pilot-model-registry-wj-001/result.json)、[研究pilot](logs/research-loop-pilot-001/result.json)、[独立评分003](logs/research-loop-pilot-001-wj-replay-003/result.json) |
| R限网 | 非root/ALL-drop配置005通过所测URL、socket与宿主边界检查；未运行Pi | [网络005](logs/research-network-probe-005/result.json)、[全部attempt](docs/harbor-integration.md) |
| 三个R镜像 | 实际构建与8/8启动检查；另完成三个镜像的正式4 vCPU/4 GiB配额、CPU节流实测 | [镜像检查](logs/research-images-local-001/result.json) |
| 受控桥 | localhost7项、R文件桥两轮各9项通过；文件桥包含真实W、6例公开反馈与不可改写快照，未调用模型 | [localhost](logs/bridge-runtime-001/result.json)、[文件桥001](logs/file-bridge-runtime-001/result.json)、[回归002](logs/file-bridge-runtime-002/result.json) |
| 完整原生Harbor Trial | **两次本机pilot通过**；最新8次可信模型请求、显式finalize、三次W/J、资源清理已核对 | [最新pilot002](logs/harbor-native-pilot-002/result.json)、[完整说明](docs/native-relay-pilot.md) |
| 正式资源 | **资源探针已通过**；Docker 6 vCPU／约9.69 GiB，R/W并发压力与真实4GiB OOM通过；T3独占计时窗口也已通过 | [验收002](logs/resource-acceptance-local-002/summary.json)、[范围与证据](docs/resource-timing-acceptance-2026-10-23.md) |
| T3正式校准 | **三组通过**；216/216数值检查，冻结 `efficiency_gate_1.5`；非模型研究成绩 | [结果与范围](docs/resource-timing-acceptance-2026-10-23.md)、[冻结](freezes/t3-profile-local-001.json) |
| 正式任务冻结 | **完成**；三任务及15会话计划为frozen，Flash版本/参数、镜像、数据、评分、提示、工具、顺序均绑定 | [冻结说明](docs/formal-freeze-2026-10-23.md)、[当前正式计划](freezes/research-run-plan-formal-003.json) |
| 三任务×三组研究 | **15/15研究关闭、9/9研究格**；9有候选、6无提交，另4无效attempt | [最终结果](docs/formal-results-2026-10-23.md) |
| 隐藏重放与正式性能 | 全部操作已执行；**14/15有效评分、8/9有效科学格**，Poisson G2计时无效 | [最终报告](results/formal-study-003/summary.json) |
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

本轮执行采用 [formal-003 计划](freezes/research-run-plan-formal-003.json)及三任务同号 freeze，已完成全部规定操作。原数据、镜像和可信源码不能重建或替换后冒充本次证据；运行/报告恢复入口见[收束交接](docs/execution-handoff-2026-10-23.md)。上述 draft、生成和校准命令仅供独立新工作使用，不是当前待办。

## 环境

数值依赖为 Python 3.12.12、NumPy 2.2.6、SciPy 1.15.3。镜像基底钉住digest，实际运行image ID写入每个结果。本地Harbor为0.24.0、commit `38b9be0164a910015a0be9a37ba6e8e78c562dfe`，Pi pilot记录0.84.1。不要用可变latest标记正式复现。

从Python3.12环境重建宿主依赖，且相邻 `../harbor` 已检出上述commit时：

```sh
python3.12 -m venv .venv
sed '/^harbor[ @=]/d' freezes/host-requirements.lock | .venv/bin/python -m pip install -r /dev/stdin
.venv/bin/python -m pip install --no-deps ../harbor
```

以上命令过滤锁文件中单独的Harbor条目，并安装相邻固定源码；不要用同版本号的未知构建替代该commit。没有相邻checkout时，最后一步可改为 `.venv/bin/python -m pip install --no-deps 'git+https://github.com/harbor-framework/harbor.git@38b9be0164a910015a0be9a37ba6e8e78c562dfe'`。新site-packages重建和重放已实际通过，见[新依赖环境记录](logs/dependency-rebuild-local-001/result.json)；复用了同一宿主、Python二进制和数值镜像。模型凭据由授权的专用运行环境提供；不要写进配置、镜像、提示、日志或版本控制。模型端点和实际请求证据见 [集成说明](docs/harbor-integration.md)。

## 执行范围与未达成项

本轮规定操作已全部尝试并本地归档；Poisson G2 的性能测量无效，因此完整 15/15 有效科学验收未达成。按用户减少重试的要求，此项保留 null，不再自动测量。其他正常无提交与零分结果也不补跑。若以后继续实验或发布，需要明确新工作范围，不能覆盖本轮失败证据。

三类受控合成任务、heat 每组 n=3、ODE/Poisson 每组 n=1、同一物理宿主与供应商模型别名均限制外推。首次→最终变化不证明反馈的因果效果，T3不与T1/T2平均。私有数值数组、运行镜像和宿主依赖仍需本机保留；证据包不是独立的完整运行环境。

[调研对应关系](docs/survey.md) · [任务卡](docs/task_cards.md) · [协议](docs/protocol.md) · [正式结果](docs/formal-results-2026-10-23.md) · [历史结果](docs/results.md) · [局限](docs/limitations.md)

最新远端核验时仓库为公开状态；初次创建/检查的私有记录仍保留。源码28da96e完成了328项工作/新依赖归档测试，随后修正报告读取最新仓库可见性的逻辑，对应回归：[27项通过](logs/publication-report-unit-local-001.txt)。本轮另补正式基线编排与对照报告；执行器、I/O、计时、算法与科学指标未变化。

三组提示的[逐字差分归档](logs/prompt-diffs-local-001/manifest.json)保留三任务各G1/G2/G3两两对照，共9组；同时提供行差分、Unicode字符编辑及原文哈希，9组均验证可逐字节重建目标提示。提示原文未改动，未估算token数冒充真实模型用量。
