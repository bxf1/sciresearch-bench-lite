# v0.3 执行协议与当前实现边界

执行契约来自原 `design/execution-plan-v0.3.md`，仓库中保留[逐字副本](execution-plan-v0.3.md)；副本内相对证据链接依赖原目录布局。本文件描述 `benchmark/` 的实际接口，并区分实现与验收。文档、单元测试、Docker配置和作者参考算法不能代替真实模型研究、隔离攻击探针或正式性能测量。

## 数据与角色

每任务应分别生成 public-dev 6、author-calibration 12、final-test 12 例，各难度占三分之一。生成器使用独立命名空间随机流，保留中间真值、每例 QC、拒绝记录、文件哈希和潜变量指纹。不得根据参考算法的恢复成绩换种子或删除失败实例。作者生成器和私有真值位于作者区；R 只获得公共开发输入与本组提示；W 只获得该快照和该批公共输入；J 获得可信评分代码、私有真值和已检查的数值产物。

所有候选和基线入口均为：

```sh
python solve.py --input /input --output /output --seed 0
```

输入 `manifest.json` 的 `cases` 列表含每例 `id`、相对 `path`、`level`。输出只允许 `cases/<id>/u0.npy`、`cases/<id>/model.json` 或 `cases/<id>/solution.npy`，分别对应 heat、ode、poisson。数值形状、有限性、little-endian float64、JSON 无重复键与类型限制由 `runner/artifact_gate.py` 执行。对象 dtype、复数、链接、特殊文件、路径逃逸和超限体积不可作为合法产物转交 J。可信输入/GT 损坏须归为评测无效。

## 候选登记和选择

宿主 `runner/registry.py` 将状态和事件存于 R 工作目录之外。研究预算默认为 1,800 秒、20 次已接受公开评估。每个已接受请求消耗额度，包括后来发现源码或数值产物非法的请求。全部请求、开始/结束时间、快照文件清单、源码哈希和执行结果必须保留；事件按前一事件哈希串联。宿主文件访问边界是可信性的基础，哈希链本身不抵御获得宿主写权限的攻击者。

桥的公共协议为 `bench evaluate <relative-source-dir>` 和 `bench finalize <candidate-id>`。当前R客户端通过 `/workspace/.bench` 内有界请求/响应文件工作；宿主FileBridge轮询并通过可信导出helper形成源码快照，再启动W。R不需要宿主HTTP接口、bridge凭据或Docker socket。登记接口不接受任意宿主命令、Docker参数或外部URL；登记后的R源码修改不影响候选快照。文件桥有限功能已在真实R/W通过9项探针，实际Pi研究生命周期仍需独立验收。

首次有效候选要求全部开发实例成功执行且数值产物合法，不要求科学通过。零解，以及 T2 合法系数导致的积分失败，仍可成为首次有效候选。显式 `finalize` 只能选择当前会话已经评估的快照；非法 ID 记录提交失败。没有 finalize 时选择最近有效候选并标注 `deadline_fallback`；无有效候选记提交失败。不得借隐藏成绩替用户选一个更好候选。

## W、产物检查与 J

`runner/worker.py` 建立全新 W：非 root、只读根、独立 IPC、无网络、丢弃全部 capabilities、no-new-privileges、默认 seccomp、1 CPU、4 GiB 内存、禁 swap、最多 128 PID。源码与输入只读挂载；输出为 256 MiB tmpfs，临时目录为 64 MiB tmpfs。数值库线程固定为 1。heat/ode 每批最多 120 秒，poisson 最多 60 秒。宿主保存 Docker 配置和 cgroup 实际值；参数存在不等于资源探针已经验收。

新版worker的可信PID1使用UID65533，候选使用UID65534。PID1等待候选主进程及所有被接管的后代退出；超过原执行预算则停止整个W并保留候选超时失败。宿主再核对进程树已清理。随后由可信 tar 读取 tmpfs 输出并流入宿主暂存目录，移除容器后才检查并复制到只读评分输入。这样避免当前引擎 `docker cp` 未复制 tmpfs 内容的问题。J 不会执行或 import 提交代码；它只导入 `judge/`、`public/` 和少量可信序列化/格式工具。`runner/replay.py` 为 J 准备有哈希的可信代码快照，使用另一无网、非 root、只读根容器调用 `python -m judge.batch`，可信 J 总时限 20 分钟。只有被许可的数值产物挂载到 J；R 自写 reward 或源码没有官方评分效力。

新版worker通过独立UID的可信PID1，记录固定Python exec前至全部后代退出的完整区间，涵盖启动、导入、I/O、计算与文件关闭；宿主Docker exec墙钟另存。原始记录始终为 `formal_timing=false`，仅有可信宿主资格合同、独占窗口与实际容器启动事件均通过后才能生成另存的正式资格记录。旧计时不追认。详见[计时实现及探针](timing.md)。

## 评分、错误状态与重放

| 任务 | 私有数值指标与通过条件 | 公开反馈 |
|---|---|---|
| heat | 初场相对误差 <=0.15，256 模态传播后的未来场相对误差 <=0.03 | 观测残差比 R 和含零边界二阶差分粗糙度 |
| ode | 四条 hidden rollout 的最大相对误差 <=0.05，field 相对误差 <=0.05，K<=10，完整积分成功 | 两条 noisy validation 误差、平均误差、K、积分状态 |
| poisson | 每 RHS 残差 <=1e-8、解误差 <=1e-5、资源合格；正式效率要求由冻结 profile 决定 | 重算残差、完整计时、资源和公开 Jacobi 比较 |

T2 先将绝对值严格小于 1e-6 的系数置零。候选积分固定 DOP853、rtol=1e-9、atol=1e-11，每条用有真实五秒截止时间的子进程；隐藏采样为 [0,8] 上 401 点，公开验证为 [0,6] 上 301 点。21×21 向量场评分网格不是轨迹边界。有限候选导致溢出、未完成、非有限状态或超时属于合法产物的科学失败，整例零分；失败 rollout 误差为 null，其他诊断可保留。

`attempt_status`、`artifact_valid`、`scientific_pass`、`evaluation_status`、`performance_status` 各自保存。候选错误、超时、OOM 或畸形产物计正常失败；可信 GT/评分代码错误写 `score=null,reward=null` 并停查。J 的官方 reward 仅在有数值结果时写出；不可将 null 填入 Harbor 默认数值奖励解析器。API/可信基础设施失败保留 attempt，不能冒充一个有效三组实验格。

`judge.batch` 按完整 manifest 计分，缺失或非法实例仍保留在分母中。heat/ode 要求 12/12 通过且每档 4/4。正式 first/final 各三次清洁重放，同源码哈希可复用并注明。Harbor `ResearchReplayVerifier` 提供已关闭 registry 的重放接入点，并要求 separate verifier，拒绝自动传入任意研究产物；实际 Harbor 生命周期联调尚需集成证据。基础重放函数的单次结果并不代表已经完成三次正式复现。

poisson 的重放次序为 B,C,C,B,B,C，各三次，不再外套三次。只有两者全部正确且资源合格，基线耗时才可作为速度分母。未通过正式宿主资格门禁时，本机性能标为 `invalid_environment`，只给 diagnostic_speedup；不能把该诊断值替代正式冻结的效率分。效率 profile 必须先由 calibration 的三组完整比较决定，不能看最终成绩后改 profile。

所有组共用的 `public/poisson_compare.py` 已打包到T3研究环境。它固定Jacobi-CG `rtol=1e-10,atol=0,maxiter=10000`，复用Jacobi预条件器、逐列求解四个RHS，只写标准solution.npy并输出公开残差。程序内部耗时明确为 `diagnostic_in_process_only`，排除了Python启动与模块导入，不能充当正式完整任务计时或科学reward。

## 冻结与本机先决条件

正式研究开始前须冻结数据、镜像摘要、Python/NumPy/SciPy、代码、指标、提示、模型精确 ID、Pi/Harbor 配置、工具和运行顺序。G1 为详细方法，G2 为方向，G3 不追加指导；三组公共输入、反馈、工具和预算相同。不得在研究循环中暴露 hidden 成绩或用其改提示、选候选。真实会话日志和可信评估记录分别保存，模型自述不是执行证明。

`runner/run_plan.py` 生成15次独立session/run/workdir的draft：先三任务×三组九格，再补T1两轮；每个task×重复轮次块内预随机G1/G2/G3，保留与数据根熵独立的排序熵。共同模型固定为deepseek-v4-pro、Pi0.84.1和指定Harbor commit，每会话1800秒/20次评估、solver seed0。启动守卫重验提示、任务包、工具代码、系统提示、R镜像及三任务freeze与证据文件哈希。普通未决null会阻断；温度确实不支持或服务未公开版本号时，只接受明确状态、原因与哈希证据。draft、未验收资源或文件漂移均不能自动转为正式运行。

只读先决条件检查命令：

```sh
PYTHONPATH=benchmark benchmark/.venv/bin/python -m runner.preflight \
  --image sciresearch-numeric:0.3.0 --output benchmark/logs/preflight-new.json
```

它不启动/停止容器，不读取凭据值，不下载镜像；仅查看 Docker 能力、已有服务、镜像标识、Pi 版本、模型密钥环境变量是否存在以及 GitHub 登录是否可用。镜像已安装依赖的实际版本、真实模型请求和隔离能力需要另做运行验证。

当前只读记录显示 Docker daemon 只有 2 CPU、4,091,772,928 bytes 可用总内存，存在 8 个既有服务容器。用户已明确允许继续本机功能工作；它仍不足以满足 R 的4 vCPU/4 GiB正式条件，也未提供T3独占窗口，因此相关记录显式为 `formal=false`。已有服务不为本任务被停止或修改。预检未发现标准API key环境变量，但真实Pi pilot已通过专用运行配置调用模型；密钥值不写入证据。GitHub登录可用不等于已经发布。

## 已执行的 W 运行时探针

`tests/runtime_probe.py` 已在本机顺序执行 11 项 Docker 探针，使用独立新建 worker、现有三个 pilot heat 输入和新的测试目录。首轮证据在 `logs/runtime-probes-001/`：每项保留候选源码、worker/格式闸门/输入哈希、实际镜像和容器配置、资源日志及 `probe.json`，汇总为 `summary.json`。这是 W 的本机功能证据，不是 R/J 全链路或真实 Agent 实验。

首轮 10 项通过：正常零解合法；继承输出管道的后台子进程被一秒截止时间终止；关闭管道的后台子进程被 reaper 终止且已接收数组保持为零；真实存在但未挂载的宿主 sentinel、`/truth`、`/privateGT`、宿主路径和 Docker socket 均不可读；伪造 `reward.json` 及符号链接输出被拒绝；output/tmp 分别在 256/64 MiB 报 ENOSPC；正常超时保留候选失败；PID 压力在 126 个子进程后报 EAGAIN，未被误归可信基础设施错误。实际 cgroup 的 CPU quota/period=1、memory.max=4 GiB、swap.max=0、pids.max=128 已核对。未在真实 HOME 创建 sentinel，只在本任务新的私有 fixture 目录创建并尝试其宿主绝对路径；挂载清单也确认只绑定源码和输入。

首轮日志洪泛探针失败：宿主日志确实被限制在 4 MiB，但停止读取管道后 Docker exec 客户端等待超时，被误归 `infrastructure_failed`。该原始失败完整保留。随后修复在资源限制路径结束 Docker exec 客户端，避免等待已停止读取的管道；`logs/runtime-probes-002/` 用新 worker 重跑正常零解、日志洪泛、普通超时和继承输出管道的后台进程，四项全部通过。日志洪泛现在正确记录 `log_limit`，仍保留为候选失败，宿主日志总量不超过 4 MiB。两轮各项 `provenance.json` 保存实际 worker 源码哈希，可区分修复前后版本。

两轮的 `cleanup.json` 确认11+4个探针容器均已移除，先前8个服务仍在运行。为保护共享宿主，没有实施实际4 GiB OOM压力；只有内存与swap的cgroup配置检查。两轮证据只对应各自worker源码哈希，后续截止时间/资源逻辑修订需另留回归，不能将旧日志重新标成新版本通过。

加入研究总截止时间处理后的worker已在[回归004](../logs/runtime-probes-004/summary.json)重跑正常零解、日志洪泛、普通超时、继承管道的后台进程，4/4通过；截止时记录 `research deadline expired`。该轮provenance与旧两轮分别保留，不把未重跑的旧攻击项目标为新worker全部通过。动态[stage-status](../results/stage-status.json)逐轮列出源码哈希以及是否匹配报告生成时的当前worker。

## R与文件桥的已执行探针

[网络005](../logs/research-network-probe-005/result.json)实测UID1000、全部capabilities丢弃、no-new-privileges、无宿主挂载/socket、1 CPU/1 GiB/禁swap/pids128。安装策略后模型域名仍返回HTTP401，example.com与直接IP对照连接被拒绝；`SO_MARK`与raw socket创建均EPERM。网络001–003的构建/插件失败和root配置004完整保留于[集成说明](harbor-integration.md)。005未运行Pi setup，也未作模型调用，不能外推为其他权限配置或全面DNS/TLS攻击审计通过。

[文件桥001](../logs/file-bridge-runtime-001/result.json)的9项真实探针均通过：6例公开输入匹配、helper/反馈不可被研究用户替换、越界请求被拒并计额、独立W执行、反馈无隐藏指标、登记快照不受R改写影响、finalize以及first/final保留。模型调用数为0；研究容器已移除、桥线程已结束。它与旧localhost HTTP桥7项探针分别保留，不能与模型pilot拼接成已完成的正式研究会话。

更新宿主评估代码后，[文件桥002](../logs/file-bridge-runtime-002/result.json)再次9/9通过，仍未调用模型。随后[真实研究pilot001](../logs/research-loop-pilot-001/result.json)登记一个有效candidate-001，但没有显式finalize，会话结束后回退选择同一候选，记录状态仍为 `pilot_returned_without_required_registration`。实际在12轮上限后结束，未达到600秒墙钟截止；原日志的 `deadline_fallback` 字段照录。其缩短预算600秒/4次只用于接线；正式会话的1800秒/20次保持不变。

该候选随后通过[真实Harbor verifier hook及独立W/J](../logs/research-loop-pilot-001-wj-replay-003/result.json)，pilot-smoke三次均3/3通过，每次score=87.69277970613776、reward=1。first/final源码相同并复用重放，没有迭代增益；此前两次verifier基础设施失败的null成绩完整保留于[结果报告](results.md)。这些均不是final-test成绩。pilot请求reasoning off却记录12个thinking块，说明参数配置尚未证明落实；官方API行为与这一差异的推断见[集成说明](harbor-integration.md)，不能据此冻结模型参数。

最新worker的[回归005](../logs/runtime-probes-005/summary.json)已重跑全部11项并通过；[timer004](../logs/process-timer-probe-004/summary.json)的5项真实进程树与权限探针通过。公开dev的6批BCCBBC及三组校准的18批均已数值通过，仍为诊断、profile=null；这些不会解锁final-test。全部11个基线已在新版worker统一重放，132个逐例科学指标与原校准完全一致：[比较证据](../logs/calibration-worker-replay-local-002.json)。
