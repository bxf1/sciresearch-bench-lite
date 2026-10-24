# 2026-10-23 正式冻结：DeepSeek-V4.1-Flash-1017

三任务配置和15会话运行计划均已正式冻结。现有启动守卫校验返回 `formal_ready=true`、`blockers=[]`，15个会话配置均已逐一构造核对。正式研究尚未启动，正式会话为0，final-test求解成绩未读取。

- [正式运行计划](../freezes/research-run-plan-formal-001.json)
- 任务freeze：[heat](../freezes/heat-formal-001.json) · [ode](../freezes/ode-formal-001.json) · [poisson](../freezes/poisson-formal-001.json)
- [冻结交付清单](../freezes/formal-freeze-local-001.json) · [启动校验](../logs/formal-freeze-local-001/cli-validation.json)

## 模型和运行参数

用户在冻结生成前决定从Pro切换至Flash。[官方模型表](https://api-docs.deepseek.com/quick_start/pricing/)和[本次复核记录](../logs/model-policy-documentation-local-003/result.json)确认 `deepseek-flash` 对应 `DeepSeek-V4.1-Flash-1017`。这是供应商公开的别名版本映射，不是可由客户端钉住的服务端二进制身份；后续若发现公开映射改变，应停止新增正式会话并创建新协议版本。

| 项目 | 冻结值 |
|---|---|
| 请求模型 / 公开版本 | `deepseek-flash` / `DeepSeek-V4.1-Flash-1017` |
| API | Anthropic Messages，`https://api.deepseek.com/anthropic` |
| 采样 | temperature=0，thinking=`disabled`，top_p=1.0，stream=true |
| 输出额度 | 每请求至多4096 token；每会话累计32768 token，按可信代理的剩余额度约束 |
| 其他代理限额 | 单请求120秒、最多512请求、最多4个并发请求；代理TTL 2700秒，研究仍以1800秒截止 |
| 研究预算 | 每次1800秒、20次已接受公开评估、无max-turns扩展、solver seed=0 |
| R / W | R 4 vCPU、4 GiB；W 1 vCPU、4 GiB、禁swap、数值线程1 |
| Pi / Harbor | Pi `0.84.1`；Harbor `38b9be0164a910015a0be9a37ba6e8e78c562dfe` |
| 数值依赖 | Python 3.12.12、NumPy 2.2.6、SciPy 1.15.3 |
| 工具 | `read`、`bash`、`edit`、`write`；额外skills/extensions/MCP为空，不resume |

`top_p=1.0`与Flash非thinking模式的服务端固定值一致，见[兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)。系统提示与完整工具JSON在三个固定R镜像中重新离线捕获，哈希一致；实际请求还要经过可信代理逐次核验。

## 镜像、数据和评分

数值镜像及三个R镜像均按完整不可变SHA256 ID冻结，本次现场检查存在且与原验收一致；详见[环境核对](../logs/formal-freeze-local-001/environment-inspection.json)。模型路由来自宿主生成的固定配置，切换模型未改变这些镜像。

三任务共90例，每任务6例public-dev、12例author-calibration、12例final-test。输入、真值、清单和QC的逐文件哈希均重新核对，与旧007草稿一致。此次仅对final-test做身份哈希和既有GT QC复核，没有执行隐藏求解或评分。

阈值沿用原执行契约，heat/ode采用accuracy，poisson采用已验收的 `efficiency_gate_1.5`。已绑定11方法作者校准、348项当前源码单测、隔离与原生网络证据、15/15资源验收、T3三组正式校准。弱基线的正常失败保留。后续隐藏重放仍要求相关任务全部预声明研究会话结束；T3需建立新的连续观察独占窗口，不能复用校准005的旧窗口。

49个可信Python文件、三任务公共包、共同提示与三组guidance、系统提示、完整工具schema、模型参数及运行矩阵均有哈希绑定；源码快照和主机依赖锁另纳入交付清单。旧草稿和旧证据不改写。

## 模型切换的证据与影响

本次仅替换7个模型接线模块及对应3个测试文件中的请求模型名，切换后的完整单测为348通过、2条既有Harbor弃用提示。数值求解器、评分器、W执行器、可信计时器、T3聚合与事件采集源码均保持与正式校准005一致；[影响核对](../logs/formal-freeze-local-001/model-switch-impact.json)逐项绑定旧/新哈希。因此既有资源、数值基线和T3性能校准继续适用。

[Flash原生smoke](../logs/harbor-native-flash-pilot-001/result.json)完成12次成功请求，失败0，累计计入2921个输出token；工具调用、一个有效候选登记、独立W/J重放、代理和容器清理均完成。该smoke使用600秒/4次公开评估/12回合上限，实际约102秒结束。没有显式finalize，按已定义的 `deadline_fallback` 选取唯一候选，first/final同一源码；pilot-smoke分数43.221、reward=0，保留其科学未通过结果。

此处通过的是模型接线与执行链路验收；它不是正式研究、没有迭代收益证据，也不能与历史Pro pilot分数作模型优劣比较。ODE/Poisson的模型smoke门槛采用共用Flash传输/工具链实测加各自R镜像的离线请求策略核验，没有声称已执行它们的正式模型研究。

## 固定运行顺序

沿用007草稿的独立顺序熵和原session ID，矩阵哈希不变。

| 序号 | 任务 / 重复轮次 | 组顺序 |
|---|---|---|
| 1–3 | heat / 1 | G2 → G3 → G1 |
| 4–6 | ode / 1 | G1 → G2 → G3 |
| 7–9 | poisson / 1 | G3 → G2 → G1 |
| 10–12 | heat / 2 | G3 → G1 → G2 |
| 13–15 | heat / 3 | G3 → G1 → G2 |

所有15个正式会话统一使用Flash。每次新session和工作目录，不继承候选或对话；所有失败attempt保留。前9次覆盖三任务三组，后6次补齐heat每组3次。

## 校验与后续执行

```sh
.venv/bin/python -m runner.run_plan validate \
  --plan freezes/research-run-plan-formal-001.json
```

本次返回退出码0。入口仍会检查源码、提示、证据哈希、实际资源和新会话配置；`frozen`状态不能绕过这些检查。

首个预声明会话为 `research-5db960ec2eb8d256-heat-g2-r1`。后续启动命令为：

```sh
PYTHONPATH=. LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m runner.study start \
  --plan freezes/research-run-plan-formal-001.json \
  --run-id research-5db960ec2eb8d256-heat-g2-r1
```

此次只完成冻结和Flash smoke，未执行上述正式启动命令，也未发布GitHub。所有新增运行容器已清理，原8个服务继续保持停止。

## 本机归档

[冻结证据包](../logs/formal-freeze-delivery-local-001/evidence.tar.gz)保存正式清单、227文件源码/公共包快照、新Flash策略捕获、原生smoke及引用的验收元数据；[完整性记录](../logs/formal-freeze-delivery-local-001/integrity.json)保存压缩包和逐文件核验结果。此前完整资源/T3原始记录继续保存在[上一证据包](../logs/resource-t3-delivery-local-001/evidence.tar.gz)，其哈希已被本次冻结清单引用；避免在新包重复保存。私有数据数组仍位于本机 `authoring/data/`，由三份任务freeze逐文件绑定。
