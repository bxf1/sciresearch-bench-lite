# T3计时实现与本机验证

新W将Linux PID1设为非root UID65533，候选仍是UID65534；cap-drop ALL、no-new-privileges、只读根目录、1 CPU、4 GiB、禁swap和pids128保持不变。可信计时器替换原有sleep PID1，不增加容器配额。其CPU和内存仍计入W的整体资源使用。

只读launcher在执行任何候选代码前，通过SO_PEERCRED核验的一次性UNIX连接记录起点，随后立即exec固定Python。连接CLOEXEC，监听器在放行前关闭。PID1持有主进程pidfd，等待其退出后通过waitpid收完全部被接管的后代；双fork、setsid、关闭stdout或自设subreaper不会提前结束计时。区间包含Python启动、导入、I/O、计算和全部后代退出/文件关闭；不包含容器准备和J。宿主总墙钟另外保存。

计时器与候选UID不同。候选不能signal、ptrace、prlimit或写入其私有证据/标准输出。计时记录在候选启动前实际预分配于原有64 MiB tmpfs中；结束时原位写入，不因候选耗尽剩余tmp空间而创建文件失败。宿主通过PID1专用Docker日志收取有长度上限的JSON，不需要在满PID配额的W中再启动读取进程。超时结束整W，保留失败状态，不伪造完整计时区间。

## 原始区间与正式资格

`process-timing.json`与原始`worker.json`始终保存`formal_timing=false`；旧日志不改写。原始区间不足以证明正式硬件或独占条件。

可信宿主可通过`runner.timing_host.TimingLease`接入已验收环境。其合同JSON必须有`status=frozen`、与`runner.phase.RESOURCES`完全相同的`resources`、不可变`image_id`，以及`resource_evidence`和`exclusivity_evidence`两个精确的`{path, sha256}`引用。相对路径按合同目录解析：

- 资源证据须包含`status=passed`、`formal_resources_accepted=true`、完整`resources`与Linux VM的`machine_id`（boot ID）。
- 独占证据须包含`status=passed`、`machine_exclusive_verified=true`、同一`machine_id`、`other_host_workloads=[]`、明确`cache_state`和当前有效的`measurement_window_unix=[start,end]`。这是对非Docker宿主负载窗口的独立验收，不能由容器探针替代。
- 运行时重新核对证据哈希、Docker至少4 CPU/4 GiB/cgroup v2、空闲容器清单，并持有本项目唯一flock。组内每个W必须在该lease的Docker start事件中恰好出现一次，不能升级历史诊断样本，也不能夹入其他容器启动。
- 新group记录还核对机器、镜像、timer/source/input/resource哈希、空输出、实际cgroup和进程清理。原始worker文件不变。候选超时/OOM/日志限制在合格环境中仍是有效零分，没有完整区间；基线失败不能提供速度分母。已冻结accuracy profile可保留候选正确性reward，efficiency profile的性能reward为null。

这个资源合同可先于profile校准存在，以免循环要求“已有profile才可测profile”。它不解锁final-test；隐藏重放仍另需完整任务freeze。2026-10-23 本机已通过资源门控及独占窗口的三组正式校准，冻结 `efficiency_gate_1.5`，详见[验收记录](resource-timing-acceptance-2026-10-23.md)。

Docker 事件从组开始前实时订阅，以从不启动的标记容器 create 事件确认订阅及结束边界。这样无需比较 macOS 与 Linux VM 的墙钟，也不依赖 Docker 有限的历史事件缓冲。每个 W 必须恰好启动一次，未知启动事件仍导致资格拒绝；完整 start 事件和边界 ID 随资格证据保存。

## 完整批次入口

公开`run_public_evaluation`的T3一次登记使用固定Jacobi比较器和候选各三次，顺序BCCBBC；六次W、检查和准备费用全部计入同一研究截止时间，仍消耗一次注册评估。每批dev为六例。反馈保留各次残差与资源，并区分中位诊断比较和`candidate_cpu_seconds_total`、`baseline_cpu_seconds_total`、`evaluation_cpu_seconds_total`。

隐藏检查点复用`replay_checkpoint`的同一BCCBBC实现，不再外套三次。三组Jacobi/LU校准入口为：

```sh
.venv/bin/python -m runner.t3_calibrate --data authoring/data/v0.3-local --output logs/t3-calibration-new
```

该入口只读取author-calibration，每组12例、六个全新W，始终保留三组。没有`--timing-contract`时profile必为null。可信调用者可在观察到基线不稳定并完成干扰调查后，用`retry_t3_attempt`显式重跑一次整组；必须保留父attempt与调查说明，禁止第三次或按任意结果重跑。

## 已保存证据

- [正式资源与校准005](resource-timing-acceptance-2026-10-23.md)：资源15/15、真实4GiB OOM分类、三组合计216个方法×实例检查通过，18个W均有新正式资格记录；profile及全部证据见[冻结记录](../freezes/t3-profile-local-001.json)。此前拒绝轮次保留。
- [最新W完整回归005](../logs/runtime-probes-005/summary.json)：11/11通过，包括tmpfs配额、PID压力、输出/路径攻击、日志限制与超时。未执行4 GiB OOM压力。后台进程现在自然等待到原预算，超时失败；不沿用旧worker主动reap后的计时结论。
- [最新timer探针004](../logs/process-timer-probe-004/summary.json)：5/5通过，含双fork、setsid、候选subreaper和13项权限/FD检查。002中一次超时分类错误保留；003和004为修复后的独立attempt。
- [公开dev完整比较](../logs/t3-public-bccbbc-local-001/public_feedback.json)：六批BCCBBC、每批六例全部残差通过，仍为诊断。
- [三组校准诊断](../logs/t3-calibration-diagnostic-001/summary.json)：十八个W/J批次、每批12例全部通过，`calibration_not_formal`、`profile=null`。诊断速度比不能作为正式效率结论。
- [定向单测](../logs/t3-timer-unit-local-001.txt)：计时协议、资格门控、历史样本拒绝、失败分类、BCCBBC、三组及一次linked retry的回归。

上述历史功能轮次没有模型调用或final-test成绩。2026-10-23 正式验收按用户授权将Colima调为6 vCPU/10 GiB并停止其他8个服务容器，数据卷保留；此次仍无模型调用或隐藏求解成绩。
