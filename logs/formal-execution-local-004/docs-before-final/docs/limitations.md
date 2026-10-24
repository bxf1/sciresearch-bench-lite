# 当前局限与未完成验收

本项目现在有三项任务的可执行实现、90例GT QC、本机11方法校准、W与R的部分隔离攻击证据、真实文件桥和真实模型pilot；同宿主干净源码及新依赖环境重放已通过，经用户明确批准，[远端已核验至536c0d9](../logs/github-remote-head-local-003.txt)，包含0a84f0c证据与后续基线代码。**正式三组研究和final-test重放仍缺失。** 2026-10-23已完成[正式资源与T3验收](resource-timing-acceptance-2026-10-23.md)，随后完成[Flash正式冻结](formal-freeze-2026-10-23.md)。新Flash smoke为接线验收，不能与历史Pro pilot作模型优劣比较。 当前正式研究为0格、0会话，所有final-test求解成绩未查看；缺项也在README首段和验收表显式列出。最新[完整Harbor Trial与模型代理pilot](native-relay-pilot.md)已跑通，实际策略/用量记录、显式finalize、三次独立重放与清理均通过；不据此降低正式门槛。

## 研究与因果解释

模型pilot被明确要求写零解，已完成模型→源码快照→登记→独立W/J三次重放且每次得0分；它证明接线而不能证明模型能解热反问题。first/final为同一candidate，没有研究迭代。首个构建失败是独立保留的attempt；第二次成功不覆盖它。pilot未采用正式30分钟/20次注册评估，也未通过正式R限网和资源验收，不能记作G1、G2或G3。

后续[research-loop-pilot-001](../logs/research-loop-pilot-001/result.json)已由真实模型读取6例公开dev并登记一个合法候选，但没有显式finalize，原选择字段为 `deadline_fallback`，状态保留为 `pilot_returned_without_required_registration`。它实际在12轮上限后结束，未达到600秒墙钟截止，登记成功而显式finalize缺失。600秒/4次评估和12回合均为接线预算，未执行隐藏评分；公开残差不证明逆恢复成功，单个候选也不证明迭代收益。

该候选后续经[真实Harbor verifier与独立W/J](../logs/research-loop-pilot-001-wj-replay-003/result.json)在pilot-smoke三次均3/3通过，score=87.69277970613776、reward=1。first/final同一源码只重放三次并复用，不能据此报告first→final增益；这也不替代final-test。前两次verifier因容器检查及缺失包文件失败，保留为基础设施attempt，不算候选科学失败。

计划的独立统计单位是研究会话。12个测试实例、同源码三次重放、20次候选评估都不是20次独立研究。最低9个格仅足以展示矩阵覆盖；15会话只给T1少量重复，不能对T2/T3稳定优劣作统计结论。即使first→final提高，也不能单凭这对比较证明反馈造成收益；预算匹配的反馈消融不在首版范围。

## 数据与数学范围

三任务都是受控合成问题，校准集很小。参考方法12/12通过不等于对分布所有实例有保证，更不等于跨科学领域自主发现。T1高频信息受扩散严重衰减，带无界高斯噪声不支持逐样本恢复定理。T2真实生成族是私有的窄子族，向量场评分方框不是轨迹边界；紧凑系数接口不接受任意表达式等价模型。T3使用离散制造解，只验证保存的离散线性系统，不测连续PDE离散误差；随机制造解对应源项可能粗糙。

每任务三个综合难度档同时改变多个因素，不用于归因单一噪声或规模效应。T3易档共用常系数A，仅在RHS上泛化；中/难档才提供未见算子。固定网格、初值、全保留mask和逐档metadata可以字节重复，重复审计必须区分公共常量和潜变量复用。

## 环境、隔离与性能

2026-10-23 按用户授权将Colima调整为6 vCPU/10 GiB，Docker实际可用约9.69 GiB，其他8个容器保持停止。三个R镜像的4 vCPU/4 GiB配额、R/W并发3.75 GiB逐页写入、W真实4 GiB OOM及零分分类均已通过，资源15/15。该验收使用离线R镜像和真实W执行器，没有重新运行正式模型会话；原2 CPU/3.81 GiB状态仅对应历史功能轮次。

W已测私有路径、socket、奖励伪造、链接、后台进程、tmpfs配额、PID、超时和日志限制；首轮日志洪泛误分类和timer002的超时误分类均保留。最新[worker005](../logs/runtime-probes-005/summary.json)11项和[timer004](../logs/process-timer-probe-004/summary.json)5项真实回归通过。各轮仍只对应保留的源码哈希；真实4 GiB OOM另由[资源验收002](../logs/resource-acceptance-local-002/summary.json)补齐。

[网络005](../logs/research-network-probe-005/result.json)已验证非root、ALL-drop、无swap配置下模型域名可连接、两个HTTP/TLS对照被阻断、标记/raw socket创建被拒绝，未做全面DNS/TLS绕过审计，也未运行Pi setup或模型请求。[文件桥001](../logs/file-bridge-runtime-001/result.json)已在真实R/W检查9项功能与边界，未调用模型。真实pilot001另记录Harbor可信配置helper所需CHOWN/DAC_OVERRIDE/FOWNER，研究进程有效capabilities仍为0，并实测setup后的限网；它与005配置不同。后续[harbor-native-pilot-001](../logs/harbor-native-pilot-001/result.json)已再次调用真实模型验证完整生命周期；它另外通过relay精确IP/端口限制和Docker DNS阻断，原网络005不追认这些新检查。

新版可信计时覆盖Python启动至全部后代退出，排除Docker准备，原始日志保持formal=false。历史公开dev与三组诊断没有正式资格；新增[正式校准005](resource-timing-acceptance-2026-10-23.md)在独立观察窗口通过三组完整BCCBBC，LU speedup为2.250×、2.227×、2.213×，冻结efficiency_gate_1.5。该结果限于M4/Colima和当前作者校准集，不能外推模型研究或final-test。macOS/VM缓存未清除，OS/GUI/控制开销与383页全局swap-in保留记录，swap-out为0；后续测量需要新独占窗口。

## 复现与发布

同熵重建已经在同固定Linux镜像复现90例、369个公开文件；它仍是同一宿主，不能替代独立干净环境重跑。Harbor/Pi pilot记录请求的 `deepseek-v4-pro`，没有独立的供应商服务端模型修订证明。历史[Pro文档取证](../logs/model-policy-documentation-local-001/result.json)保留原观察日期；最新[Flash冻结前复核](../logs/model-policy-documentation-local-003/result.json)确认 `deepseek-flash` 对应 `DeepSeek-V4.1-Flash-1017`，已纳入正式冻结。这是供应商公开映射，不能追认早期pilot版本或证明不可变内部二进制身份。系统提示/实际工具定义已在三个R镜像中离线捕获，可信代理已实测每请求4096、会话32768的输出额度和请求哈希门禁；这些不证明供应商未公开的内部模型修订。历史实际计费未核实，金额为null；不将当前公开价格代入过去调用，也不假定免费。

[干净源码重放](../logs/clean-replay-local-001/result.json)使用首提交 `af5a19dcffe1cda8d3fed570e715d97f2b954ccc` 的Git archive展开新目录，并启动新的W/J容器；三任务参考和真实heat候选各3/3通过，T3 score/reward仍为null。工作源码和归档源码的保存日志均为184项通过。但它仍复用本机宿主依赖、同一Docker daemon和固定数值镜像，只支持fresh-source/fresh-container复现结论，不能冒充第二台干净机器、完整依赖重装或新增模型研究。

源码及证据已推送GitHub仓库[bxf1/sciresearch-bench-lite](https://github.com/bxf1/sciresearch-bench-lite)，[远端HEAD](../logs/github-remote-head-local-001.txt)核验了上述首提交，[仓库元数据](../logs/github-repository-local-001.json)确认PRIVATE。[本机交付记录](../freezes/local-delivery-001.json)保留提交与测试/重放哈希；私有生成数据和GT数组未提交。宿主依赖须按README固定Harbor commit安装，版本号本身不能代替源码身份。执行计划副本保留原design/参考仓库布局的相对链接，未承诺在独立clone中全部可打开。公开生成器/GT以后，这套机制仅保证运行时访问隔离，不能保证永久保密或不存在训练污染。

后续[清洁重放002](../logs/clean-replay-local-002/result.json)已使用源码提交 `28da96e1c1a8a50911c6a08dbb99bb6b72f145c9`、重新安装的95个锁定依赖加固定Harbor源码，以及全新W/J。三任务参考和最新真实模型候选各3/3通过；[归档源码328项测试](../logs/clean-replay-local-002/archived-unit-tests.txt)通过。它没有复用旧site-packages，但仍复用同一物理宿主、Python二进制、Docker daemon与数值镜像，不能写成第二台机器或正式性能验收。依赖安装的早期TLS失败、修正后成功记录及原安装阶段状态均保留。

[正式研究控制器](study.md)已实现逐会话固定预算、研究与final分离、全部attempt留档、显式关联重试和T3至多一次经调查的重测；这些分支目前是合成测试证据。完整真实native pilot仅覆盖本机heat功能链路，正式三个任务的15会话没有执行。

仓库可见性以[最新核验003](../logs/github-repository-local-003.json)为准：当前为PUBLIC。初次001的PRIVATE记录仅代表当时状态；本轮没有改变仓库可见性。随后报告仅修复了读取最新元数据的逻辑，独立回归通过，不涉及求解/执行/计时/科学指标。

公开推送0a84f0c与536c0d9曾被自动审批拒绝，因为具体内容须获公开授权。用户随后分别明确批准这两个提交，推送及远端核验均已完成，见[发布记录](../logs/publication-local-003/result.json)。该记录仅证明所列提交，不追认任何未来提交的授权；正式研究和资源门槛不因发布完成而改变。
