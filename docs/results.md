# 本机实施与校准结果

报告生成时间：2026-10-22T12:07:24.791522+08:00。状态以该次读取的原始证据为准。

当前证据支持三任务生成/QC、作者基线和 W/J 本机功能；正式三组研究及 final-test 成绩尚未完成。所有表格保留失败，不把实例数量当作研究会话数量。

## 作者校准

来源：[原始完整结果](../results/calibration-local-002/summary.json)。每种方法只跑一次 author-calibration 批次，每批12例、每档4例；下表给出全部方法和分母。校准数值可解性不能替代未见测试或正式资源验收。

| 任务 | 方法 | 通过数 | 连续分 |
|---|---|---:|---:|
| heat | 32模态未正则化 LS | 1/12 | 24.812 |
| heat | 前5模态 LS | 12/12 | 87.015 |
| heat | 固定 Tikhonov α=1e-5 | 12/12 | 93.572 |
| heat | discrepancy Tikhonov | 12/12 | 91.780 |
| heat | TSVD | 12/12 | 92.505 |
| ode | 原始差分+稠密 LS | 0/12 | 0.000 |
| ode | 固定 SG31/STLSQ.02 | 12/12 | 95.791 |
| ode | SG/STLSQ 公开验证选参 | 12/12 | 97.166 |
| poisson | 无预条件 CG | 12/12 | null（性能未验收） |
| poisson | Jacobi-CG | 12/12 | null（性能未验收） |
| poisson | LU复用4 RHS | 12/12 | null（性能未验收） |

前向扩散会掩盖不稳定高频，因此不能把低观测/前向残差当作逆恢复成功。T2 合法但超出 K<=10 紧凑性限制的模型保留为0分。失败实例和原始误差均未删除。

固定 Tikhonov 的最大初场/前向误差为 0.055578/0.0039155。固定 SG/STLSQ 的最大 rollout/field 误差为 0.015645/0.020877。LU 的最大残差/解误差为 3.2114e-16/1.0913e-12。完整逐例误差、K、状态及失败ID见导出表和原始JSON。

T3 三种方法数值均通过；正式性能 profile 尚未冻结。本机新版可信计时、公开dev完整BCCBBC和三组校准诊断详见[计时说明](timing.md)，共享宿主诊断不满足独占验收。各批次计时范围以对应源码和原始日志为准；正式S3、speedup门槛和任务reward保持null。

可机读表：[132个方法×实例记录](../results/cases/calibration.csv)、[11个批次记录](../results/runs/calibration.csv)、[方法汇总及失败ID](../results/comparisons/calibration-summary.json)。CSV 中未知值为字面量 `null`；成本未估算。

## 数据与复现证据

当前生成 90 例，90 例通过预声明 GT QC。每任务为6 dev、12 calibration、12 final；36个 final 实例仅做生成与GT检查，未读取求解成绩。

[同熵重建证据](../freezes/data-reproduction-local.json)记录同一固定Linux镜像重建90例，369个公开输入文件逐字节一致。生成器期间补充了来源快照和重复审计，但没有改变数据公式或随机流；重建来源保存在 `authoring/data/v0.3-local-reproduced/private/generator-code/`。

T3 共有21个独立算子：10个易档实例共用固定 A、RHS 独立，20个中/难档 A 不同。T1易档全保留mask、固定网格、T2固定时间/初值以及T3逐档metadata是设计常量，不能冒充独立随机矩阵。

## 运行时与模型 smoke

W运行时第一轮11项通过10项，发现日志洪泛误分类；原失败保留。修复后对正常路径、洪泛、超时和后台管道四项重跑，4/4通过。两轮共15个专用探针容器已移除，原8个服务仍运行；参见 [第一轮](../logs/runtime-probes-001/summary.json)、[回归](../logs/runtime-probes-002/summary.json)及[协议边界](protocol.md)。

真实模型 pilot 保留两个 attempt：第一次在镜像构建阶段失败，未调用模型；第二次通过 Harbor 内置 Pi 调用配置的 DeepSeek 兼容端点，读取公共形状并写出刻意要求的零解程序。它用于链路测试，不是自主求解成功，也不属于 G1/G2/G3 正式格。输入8924 token（含缓存6528）、输出625 token，模型阶段约11.84秒，金额未知为null。R使用2 CPU/2 GiB且网络未限定，仅属于诊断配置。参见 [原始失败](../logs/model-smoke-20261022-01/result.json)、[模型生成源码](../logs/model-smoke-20261022-02/result.json)和[集成说明](harbor-integration.md)。

模型源码的 registry→W→J 原始结果已保存于 [pilot-model-registry-wj-001](../logs/pilot-model-registry-wj-001/result.json)。状态为 `pilot_model_to_independent_scoring_completed`，first/final为 `candidate-001` / `candidate-001`，共 3 次清洁重放，reward=0、score=0.0。合法零解得到0分证明独立评分链路；没有研究迭代，也不能计入正式三组矩阵。

[localhost受控桥探针](../logs/bridge-runtime-001/result.json)有 7/7 项通过，包含真实W公开反馈、认证拒绝、路径逃逸、快照后改写与finalize。它是宿主本地接口验证，不是R网络allowlist或完整研究闭环。

## 研究容器与文件桥

用户已授权继续本机功能开发；该授权不改变正式4 vCPU/4 GiB和30分钟/20次评估预算。新增探针继续标记 `formal=false`，不调用模型，也不读取隐藏成绩。

| 保留的运行 | 记录状态 | 通过项 |
|---|---|---:|
| [research-network-probe-001](../logs/research-network-probe-001/result.json) | `probe_failed` | — |
| [research-network-probe-002](../logs/research-network-probe-002/result.json) | `probe_failed` | — |
| [research-network-probe-003](../logs/research-network-probe-003/result.json) | `probe_failed` | — |
| [research-network-probe-004](../logs/research-network-probe-004/result.json) | `functional_probe_passed` | — |
| [research-network-probe-005](../logs/research-network-probe-005/result.json) | `functional_probe_passed` | — |
| [file-bridge-runtime-001](../logs/file-bridge-runtime-001/result.json) | `functional_probe_passed` | 9/9 |
| [file-bridge-runtime-002](../logs/file-bridge-runtime-002/result.json) | `functional_probe_passed` | 9/9 |

网络005实测研究进程为UID1000、无capabilities、no-new-privileges；模型域名仍可连接，example.com与直接IP两个对照被阻断，标记socket与raw socket创建均EPERM。该探针使用1 CPU/1 GiB、无模型调用，且未执行Pi安装；它没有覆盖所有DNS/TLS绕过或未来CHOWN-only启动配置。此前构建/插件失败及root配置004均保留，详见[集成说明](harbor-integration.md)。

文件桥001的9项检查包含：6例公开输入逐文件匹配，研究用户不能改写helper/反馈，路径逃逸被拒绝且消耗额度，已登记快照在独立W执行，反馈无隐藏指标，R事后改写不影响快照，finalize与first/final保留。这里没有模型调用；真实Pi研究循环须由其自己的完整结果验收。

与本报告生成时worker源码哈希一致的回归：[runtime-probes-005](../logs/runtime-probes-005/summary.json) 11/11。这些回归只覆盖各自列出的探针，旧轮的覆盖范围仍按旧源码版本报告。

模型研究循环pilot的当前记录如下；未结束或失败均不计成功，所有运行都不是正式研究格：

| 运行 | 当前记录状态 | 已登记评估 / 最终选择 | 预算秒/评估上限 |
|---|---|---|---:|
| [research-loop-pilot-001](../logs/research-loop-pilot-001/result.json) | `pilot_returned_without_required_registration` | 1 / `deadline_fallback` | 600/4 |

pilot001在12轮上限后结束，未达到600秒墙钟截止；原日志的 `deadline_fallback` 选择字段照录，[补充观察](../logs/research-loop-pilot-001/model-observation.json)区分了成功登记与缺失的显式finalize。pilot的缩短预算用于接线检验，不更改正式会话的1800秒/20次预算。当前状态和证据hash同时写入[研究pilot表](../results/runs/research-pilots.csv)。

该研究候选的后续Harbor verifier与独立W/J链路单独记录，不能与此前刻意零解pilot混为一项：

| verifier attempt | 状态 | reward / score |
|---|---|---:|
| [research-loop-pilot-001-wj-replay](../logs/research-loop-pilot-001-wj-replay/result.json) | `pilot_verifier_failed` | null / null |
| [research-loop-pilot-001-wj-replay-002](../logs/research-loop-pilot-001-wj-replay-002/result.json) | `pilot_verifier_failed` | null / null |
| [research-loop-pilot-001-wj-replay-003](../logs/research-loop-pilot-001-wj-replay-003/result.json) | `pilot_verifier_completed` | 1 / 87.693 |

成功记录通过真实Harbor verifier hook调度独立W/J，数据仅为pilot-smoke。research-loop-pilot-001的同一candidate-001三次各3/3通过，每次score=87.69277970613776、reward=1；first与final源码相同，final复用first的三次记录，没有迭代增益。先前两次因容器检查/缺失包文件而失败，reward与score为null，属于基础设施attempt，不算候选科学失败。

全部attempt及parent链见[重放批次表](../results/runs/research-pilot-replays.csv)，真正执行的三个批次共9个case记录见[逐例表](../results/cases/research-pilot-replays.csv)；不重复计入复用的final。所有这些结果均非final-test，正式0格/0会话保持不变。

旧W探针只证明各自 `provenance.json` 所记源码。stage-status同时保存当前worker哈希和是否与各轮探针匹配；不能把旧版本通过记录直接算作后续截止时间/资源修订的回归。公开T3 Jacobi-CG比较程序已加入共同任务环境，仅用A/RHS，内部时间为诊断；正式比较仍需可信W完整计时。

## 干净源码重放与交付

从已提交Git archive展开到新目录，在同一宿主使用新的W/J容器完成以下pilot-smoke重放；依赖环境是否重装按各次证据和新依赖环境记录分别报告。没有新增模型调用。

| 方法/候选 | 通过数 | score | reward |
|---|---:|---:|---:|
| heat / tikhonov | 3/3 | 87.69277970613761 | 1 |
| ode / fixed | 3/3 | 97.14755312766924 | 1 |
| poisson / lu | 3/3 | null | null |
| heat / model | 3/3 | 87.69277970613776 | 1 |

[clean-replay-local-001](../logs/clean-replay-local-001/result.json)状态为 `completed`，源码commit为 `af5a19dcffe1cda8d3fed570e715d97f2b954ccc`；archive、数值image、模型registry/源码及输入哈希保留在原始证据。各方法只重放一个三例批次，T3正式性能仍未测，因此其score/reward为null。

导出[重放批次表](../results/runs/clean-replays.csv)和[12个逐例记录](../results/cases/clean-replays.csv)。原始运行证据保留，GT数组没有复制进交付日志。

首版源码和证据已实际推送到私有仓库[bxf1/sciresearch-bench-lite](https://github.com/bxf1/sciresearch-bench-lite)；远端核验提交为 `2af15fa2d233e62aa952d25f3799cfb02f617c54`。核验记录：[github-repository-local-001.json](../logs/github-repository-local-001.json)、[github-remote-head-local-002.txt](../logs/github-remote-head-local-002.txt)。此处记录已核验的提交，不将后续文档修改冒充该提交的内容。

最新保存的[完整单测日志](../logs/unit-tests-final-local-004.txt)为328 passed，用时780.68秒；测试数量随代码变化，以对应日志和源码版本为准。

[归档源码单测](../logs/clean-replay-local-001/archived-unit-tests.txt)同样为184 passed，用时10.39秒；其依赖来源以对应重放记录为准，不代表第二台物理机器验收。

[本机交付记录](../freezes/local-delivery-001.json)绑定其对应提交、重放结果与测试哈希，并明确formal pending、正式0会话及私有数据未发布。

真实模型的显式finalize和完整Harbor SingleStepTrial生命周期已由本机native pilot验证：[harbor-native-pilot-001](../logs/harbor-native-pilot-001/result.json)、[harbor-native-pilot-002](../logs/harbor-native-pilot-002/result.json)。这些记录仅使用public-dev研究与pilot-smoke重放，formal=false，不计入正式三组实验。

[新依赖环境记录](../logs/dependency-rebuild-local-001/result.json)的安装阶段状态为 `fresh_dependency_environment_installed`，新环境重放状态为 `pending`。旧site-packages复用标记为 `false`；安装完成不等于重放已完成。

自动汇总见 [stage-status.json](../results/stage-status.json)，模型attempt表见 [model-pilots.csv](../results/runs/model-pilots.csv)。

## 未完成的验收

正式资源、固定模型参数/系统提示/有效工具配置及三任务freeze、至少9格（主目标15会话）的正式三组实验、first/final隐藏重放、T3性能profile与独占计时仍未完成。新依赖环境复现以其单独记录的重放状态为准。正式研究当前为0格、0会话；final-test仅做GT QC，未查看任何求解成绩。15次分块运行清单只生成draft，遇到未证参数、缺freeze或哈希漂移会拒绝启动。详见 [README](../README.md)和[局限](limitations.md)。
