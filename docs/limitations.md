# 当前局限与未完成验收

本项目现在有三项任务的可执行实现、90例GT QC、本机11方法校准、W与R的部分隔离攻击证据、真实文件桥和真实模型pilot；同宿主干净源码重放已通过，源码和证据已推送私有GitHub仓库。**正式三组研究、final-test重放、性能冻结和新依赖环境复现仍缺失。** 当前正式研究为0格、0会话，所有final-test求解成绩未查看；缺项也在README首段和验收表显式列出。最新[完整Harbor Trial与模型代理pilot](native-relay-pilot.md)已跑通，实际策略/用量记录、显式finalize、三次独立重放与清理均通过；不据此降低正式门槛。

## 研究与因果解释

模型pilot被明确要求写零解，已完成模型→源码快照→登记→独立W/J三次重放且每次得0分；它证明接线而不能证明模型能解热反问题。first/final为同一candidate，没有研究迭代。首个构建失败是独立保留的attempt；第二次成功不覆盖它。pilot未采用正式30分钟/20次注册评估，也未通过正式R限网和资源验收，不能记作G1、G2或G3。

后续[research-loop-pilot-001](../logs/research-loop-pilot-001/result.json)已由真实模型读取6例公开dev并登记一个合法候选，但没有显式finalize，原选择字段为 `deadline_fallback`，状态保留为 `pilot_returned_without_required_registration`。它实际在12轮上限后结束，未达到600秒墙钟截止，登记成功而显式finalize缺失。600秒/4次评估和12回合均为接线预算，未执行隐藏评分；公开残差不证明逆恢复成功，单个候选也不证明迭代收益。

该候选后续经[真实Harbor verifier与独立W/J](../logs/research-loop-pilot-001-wj-replay-003/result.json)在pilot-smoke三次均3/3通过，score=87.69277970613776、reward=1。first/final同一源码只重放三次并复用，不能据此报告first→final增益；这也不替代final-test。前两次verifier因容器检查及缺失包文件失败，保留为基础设施attempt，不算候选科学失败。

计划的独立统计单位是研究会话。12个测试实例、同源码三次重放、20次候选评估都不是20次独立研究。最低9个格仅足以展示矩阵覆盖；15会话只给T1少量重复，不能对T2/T3稳定优劣作统计结论。即使first→final提高，也不能单凭这对比较证明反馈造成收益；预算匹配的反馈消融不在首版范围。

## 数据与数学范围

三任务都是受控合成问题，校准集很小。参考方法12/12通过不等于对分布所有实例有保证，更不等于跨科学领域自主发现。T1高频信息受扩散严重衰减，带无界高斯噪声不支持逐样本恢复定理。T2真实生成族是私有的窄子族，向量场评分方框不是轨迹边界；紧凑系数接口不接受任意表达式等价模型。T3使用离散制造解，只验证保存的离散线性系统，不测连续PDE离散误差；随机制造解对应源项可能粗糙。

每任务三个综合难度档同时改变多个因素，不用于归因单一噪声或规模效应。T3易档共用常系数A，仅在RHS上泛化；中/难档才提供未见算子。固定网格、初值、全保留mask和逐档metadata可以字节重复，重复审计必须区分公共常量和潜变量复用。

## 环境、隔离与性能

宿主Docker仅2 CPU、约3.81 GiB总内存且有其他长期运行服务。用户已经授权本机继续功能开发；正式R的4 vCPU/4 GiB预算仍未满足。W cgroup限制已实测为1 CPU、4 GiB、禁swap、pids128，但这不创造额外物理内存。为保护共享服务，尚未做真实4 GiB OOM压力；内存配额文字/实际cgroup检查不能替代OOM分类探针。

W已测私有路径、socket、奖励伪造、链接、后台进程、tmpfs配额、PID、超时和日志限制；首轮日志洪泛误分类和timer002的超时误分类均保留。最新[worker005](../logs/runtime-probes-005/summary.json)11项和[timer004](../logs/process-timer-probe-004/summary.json)5项真实回归通过。各轮仍只对应保留的源码哈希；4 GiB OOM未测。

[网络005](../logs/research-network-probe-005/result.json)已验证非root、ALL-drop、无swap配置下模型域名可连接、两个HTTP/TLS对照被阻断、标记/raw socket创建被拒绝，未做全面DNS/TLS绕过审计，也未运行Pi setup或模型请求。[文件桥001](../logs/file-bridge-runtime-001/result.json)已在真实R/W检查9项功能与边界，未调用模型。真实pilot001另记录Harbor可信配置helper所需CHOWN/DAC_OVERRIDE/FOWNER，研究进程有效capabilities仍为0，并实测setup后的限网；它与005配置不同。后续[harbor-native-pilot-001](../logs/harbor-native-pilot-001/result.json)已再次调用真实模型验证完整生命周期；它另外通过relay精确IP/端口限制和Docker DNS阻断，原网络005不追认这些新检查。

新版可信计时已覆盖Python启动至全部后代退出，排除Docker准备，原始日志仍为formal=false。公开dev完整BCCBBC及三组校准已经运行，均通过数值检查，但处于共享本机，不能冻结正式T3加速比或效率profile。当前正式T3 score/reward保持null，数值正确性单独报告；详见[计时说明](timing.md)。

## 复现与发布

同熵重建已经在同固定Linux镜像复现90例、369个公开文件；它仍是同一宿主，不能替代独立干净环境重跑。Harbor/Pi pilot记录请求的 `deepseek-v4-pro`，没有独立的供应商服务端模型修订证明。正式清单因此保留待验证字段：确实不支持temperature或不公开模型版本时可用有原因、证据哈希的明确null，不能编造版本，也不能把普通未决null作为已冻结。系统提示、实际工具清单、输出token总上限与执行机制仍需完整记录。定价未核实，金额为null，不假定免费。

[干净源码重放](../logs/clean-replay-local-001/result.json)使用首提交 `af5a19dcffe1cda8d3fed570e715d97f2b954ccc` 的Git archive展开新目录，并启动新的W/J容器；三任务参考和真实heat候选各3/3通过，T3 score/reward仍为null。工作源码和归档源码的保存日志均为184项通过。但它仍复用本机宿主依赖、同一Docker daemon和固定数值镜像，只支持fresh-source/fresh-container复现结论，不能冒充第二台干净机器、完整依赖重装或新增模型研究。

源码及证据已推送私有GitHub仓库[bxf1/sciresearch-bench-lite](https://github.com/bxf1/sciresearch-bench-lite)，[远端HEAD](../logs/github-remote-head-local-001.txt)核验了上述首提交，[仓库元数据](../logs/github-repository-local-001.json)确认PRIVATE。[本机交付记录](../freezes/local-delivery-001.json)保留提交与测试/重放哈希；私有生成数据和GT数组未提交。宿主依赖须按README固定Harbor commit安装，版本号本身不能代替源码身份。执行计划副本保留原design/参考仓库布局的相对链接，未承诺在独立clone中全部可打开。公开生成器/GT以后，这套机制仅保证运行时访问隔离，不能保证永久保密或不存在训练污染。
