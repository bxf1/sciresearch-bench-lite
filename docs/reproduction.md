# 复现与证据使用

本仓库的正式结果来自同一台 M4 MacBook Air / Colima Linux aarch64 环境。历史 freeze 绑定该次源码、数据、镜像与机器。新机器可核验和重放，但必须重新验收资源与计时，不能直接继承旧机器的速度结论。以下命令均在仓库根目录执行；使用新的输出目录，保留原结果。

## 1. 先核验交付内容

只需 Python 3.10+ 标准库：

```bash
python3 tools/verify_delivery.py
```

它验证 `delivery-manifest.json` 中的文件 SHA256、90 例索引、18 例公开输入、11 种基线、15 次正式研究及节选日志来源。该检查不执行候选、不调用模型，不代替数值实验复现。

按[数据说明](../data/README.md)下载并验证 `author-data-v0.3.tar.gz`，解压后数据根目录是 `authoring/data/author-data-v0.3/`，含 `inputs/` 和 `private/`。完整原始轨迹、包内清单和校验记录见 [Release](https://github.com/bxf1/sciresearch-bench-lite/releases/tag/v0.3-submission-20261024)。其历史标签源码 ZIP 对应初次提交；最新交付请使用 main 或命名为 `submission-ready-20261024.tar.gz` 的附件，提交 SHA 记录在附件完整性文件中。

## 2. 安装固定依赖与数值镜像

使用 Python 3.12，Docker 必须可访问：

```bash
python3.12 -m venv .venv
sed '/^harbor[ @=]/d' freezes/host-requirements.lock > /tmp/sciresearch-host-requirements.txt
.venv/bin/python -m pip install -r /tmp/sciresearch-host-requirements.txt
.venv/bin/python -m pip install --no-deps 'git+https://github.com/harbor-framework/harbor.git@38b9be0164a910015a0be9a37ba6e8e78c562dfe'
LITELLM_LOCAL_MODEL_COST_MAP=True ./reproduce.sh test

docker build -f environment/Dockerfile -t sciresearch-numeric:0.3.0 .
```

Dockerfile 固定 Python 3.12.12 基础镜像 digest，NumPy 2.2.6、SciPy 1.15.3；构建上下文是仓库根目录。宿主锁文件与固定 Harbor commit 共同确定依赖。运行的镜像 ID 必须实际核验，重建的镜像不自动等于旧 ID。测试以本次输出为准，历史 `357 passed` 日志不能替代新执行。

## 3. 三任务全部作者基线（不调用模型）

使用下载的原数据，在 author-calibration split 运行 11 种方法：

```bash
.venv/bin/python -m runner.calibrate \
  --data authoring/data/author-data-v0.3 \
  --output results/reproduction-calibration-new \
  --image sciresearch-numeric:0.3.0
```

Heat 5 种、ODE 3 种、Poisson 3 种方法分别记录容器配置、源码/输入/镜像标识、逐例指标、资源日志与 `summary.json`。弱方法失败不会删除。该入口只评价 author-calibration；Poisson 耗时是诊断值，不冒充经过正式计时准入的速度。

如需独立新数据，可先生成，再把上面 `--data` 改成新目录：

```bash
.venv/bin/python -m authoring.generate --output authoring/data/new-local
```

生成器创建 90 个实例、输入、作者真值、QC、根熵与源码快照；只执行预声明的质量检查，不调用逆求解器挑选实例。同根熵重建：

```bash
.venv/bin/python -m authoring.generate \
  --entropy-file authoring/data/author-data-v0.3/private/generation.json \
  --output authoring/data/same-entropy-new
```

严格字节复现应在相同 Linux 数值环境执行。不同平台的浮点和 npz 字节可能不同，还需比较 QC 与数值误差。作者真值与根熵只供作者/评分器使用，不能整体挂载到研究 Agent 的 R 容器。

## 4. 重放已有 Agent 产物（不调用模型）

Heat G3 r1 最终候选的源码快照已保留。以下是在 calibration 上进行新的功能重放，**不等于原 final-test 成绩复现**：

```bash
.venv/bin/python -m runner.replay \
  --task heat \
  --source research-runs/research-6615cd7900ba0750-heat-g3-r1/registry/snapshots/candidate-018 \
  --input authoring/data/author-data-v0.3/inputs/heat/author-calibration \
  --truth authoring/data/author-data-v0.3/private/heat/author-calibration \
  --output results/reproduction-heat-g3-candidate-new \
  --image sciresearch-numeric:0.3.0
```

该命令仍通过隔离 W/J 执行与判题；原 final 的 91.532 分来自 12 例 final-test 的三次独立重放，见[证据链](evidence.md)。正式 final-test 入口会要求完整 freeze 和关闭研究的登记证据，不能删除约束来得到所谓正式成绩。

## 5. 新 Agent 研究到隐藏评分

完整新研究需模型供应商凭据、受控 relay、固定研究镜像、资源准入和新 freeze。凭据由运行环境注入，不写入仓库、镜像、提示或命令参数。研究镜像、网络/资源准备见[Harbor 集成](harbor-integration.md)；研究时仅暴露 `tasks/` 中对应 public-dev 与公开工具。默认 `tests/test.sh` 有意拒绝无可信 registry 的通用 Harbor 运行。

标准步骤是：`runner.run_plan` 生成并验收新计划 → `runner.study start` 运行预声明研究 → 对应任务研究全部关闭 → `runner.study final` 和 `runner.study baseline` 执行隐藏评分 → `runner.study_report` 汇总。命令、研究屏障及显式重试规则见[研究协议](study.md)。新数据、新环境或新提示必须建立新计划，不能篡改旧哈希后宣称复现原实验。

500,000 token 选择性补跑已取消，无新增有效成绩。历史恢复脚本仅用于保留该次尝试的证据，不是复现入口。

## 6. 重新整理表格及证据边界

`tools/prepare_delivery.py` 从既有输入生成数据索引、分难度基线表、first/final 比较和日志节选，不重跑实验。它需要作者本机布局：

- 原数据位于 `authoring/data/v0.3-local/`；
- 原作者数据包位于 `logs/submission-delivery-2026-10-24/author-data-v0.3.tar.gz`；
- 正式 CSV 与引用日志为仓库内已归档文件。

普通读者无需执行此生成脚本即可查看和验证已提交表格。完整性哈希只证明文件与清单一致，不能独立证明科学结论；还应核对评分源码、阈值、QC、运行状态和重放环境。

原 formal-003 证据包含 9,252 个文件，SHA256 为 `a7c6c809dc87340f66c0dd65fef3a88b032d3e0dd6ee50e981d0cc60a9076faa`。历史日志中的 `local_only` 或“未发布”是当时状态，原文不改写。原正式结果、失败尝试与取消记录均保留，交付分析不增加研究分母。


## 已关闭 thinking/max 对照的核验

2026-10-25 对照已完成，结果及计时拒绝见 [thinking-control 报告](thinking-control-2026-10-25.md)。在 main 的完整检出中运行 `python3 tools/analyze_thinking_control.py`，仅从已存 JSON、事件和哈希重建 `reviewed-comparison.json`；不发起模型请求、不执行候选、不追加计时窗口。先执行 `python3 tools/verify_delivery.py` 可校验交付完整性。两个工具均使用标准库。

Release 的 `thinking-control-evidence-20261025.tar.gz` 是本轮独立命名的增量证据，包含全部 17 个 attempt、独立评分、原生轨迹及修复/拒绝记录；`thinking-control-manifest-20261025.json` 列逐文件 SHA256，`thinking-control-SHA256SUMS-20261025.txt` 校验附件。原正式证据及作者数据附件仍保留。增量包不是完整仓库替代品，应与 main 和原作者数据结合使用。包内不含私有 relay admission、环境秘密或依赖缓存。
