# 复现与证据使用

本仓库的正式结果来自同一台 M4 MacBook Air / Colima Linux aarch64 环境。代码和数值数据支持重放；新的机器必须重新验收镜像、资源和计时窗口，不能直接继承旧机器的速度结论。历史 freeze 是该次实验的凭据，不是任意新机器都能通过的通用配置。

## 安装固定依赖

在仓库根目录使用 Python 3.12：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
sed '/^harbor[ @=]/d' freezes/host-requirements.lock > /tmp/sciresearch-host-requirements.txt
.venv/bin/python -m pip install -r /tmp/sciresearch-host-requirements.txt
.venv/bin/python -m pip install --no-deps 'git+https://github.com/harbor-framework/harbor.git@38b9be0164a910015a0be9a37ba6e8e78c562dfe'
LITELLM_LOCAL_MODEL_COST_MAP=True ./reproduce.sh test
```

数值镜像：

```bash
docker build -f environment/Dockerfile -t sciresearch-numeric:0.3.0 .
```

Dockerfile 固定 Python 基础镜像 digest，数值库为 NumPy 2.2.6、SciPy 1.15.3；宿主锁文件固定 Harbor 及测试依赖。研究镜像和网络/资源准备详见[Harbor 集成](harbor-integration.md)。运行的镜像 ID 必须实际核验；重建的镜像不自动等于原 ID。

## 新数据及全部基线（不调用模型）

```bash
.venv/bin/python -m authoring.generate --output authoring/data/new-local
.venv/bin/python -m runner.calibrate \
  --data authoring/data/new-local \
  --output results/new-local-calibration \
  --image sciresearch-numeric:0.3.0
```

输出目录必须不存在。生成器创建 90 个实例、输入、作者真值、QC、根熵和源码快照。校准器运行 Heat 5 种、ODE 3 种、Poisson 3 种方法，写 `summary.json`，弱方法失败不会删除。该入口只评价 author-calibration，Poisson 耗时属于诊断，不冒充正式速度。

若需验证原 90 例，可从 [GitHub Release](https://github.com/bxf1/sciresearch-bench-lite/releases/tag/v0.3-submission-20261024) 下载作者数据归档，校验公开的 SHA256 后解压到专门数据目录。该归档含作者真值和根熵，**只供作者/评分器复现使用，不能整个挂入 R**。可用 `authoring.generate --entropy-file <解压目录>/private/generation.json --output <新目录>` 在相同 Linux 数值环境重建；不同平台的浮点与 npz 字节可能不同，需比较 QC 和数值误差，不仅比较压缩包时间戳。

## Agent 到隐藏评分

完整运行需模型供应商凭据、受控 relay、固定研究镜像、资源准入和 freeze。凭据只能由运行环境注入，不写入仓库、镜像、提示或命令参数。已有 `tasks/` 只含 public-dev 和公开工具。默认 `tests/test.sh` 有意拒绝无可信 registry 的通用 Harbor 运行，不能改为总是输出通过。

标准入口为 `runner.run_plan` → `runner.study start` → 研究关闭 → `runner.study final` → `runner.study report`。先运行各模块 `--help` 并参考[研究协议](study.md)、[接线说明](harbor-integration.md)。旧 formal-003 绑定旧源码和机器；新数据、新环境、新提示或新的控制器都必须建立新的计划，不通过篡改旧哈希“复现”。

本次 50 万批次使用 `runner.supplemental`，冻结文件记录 six-run 白名单、nullable 的总时限/请求数/评估数以及 500,000 token。中断恢复和追加评分控制脚本保存在 `logs/supplemental-2026-10-24/`；其路径/计划用于记录这次运行，不能在其他机器无条件重用。恢复脚本会清理明确匹配的遗留容器，普通复现者不要执行历史恢复脚本。

## 证据层次

- 仓库直接提供任务公开数据、生成/QC/评分代码、基线、提示、冻结记录、正式结果表和关键诊断。
- [正式报告](formal-results-2026-10-23.md)对应原 15 次研究；[补充报告](supplemental-results-2026-10-24.md)对应 6 次选择性补跑和 1 次原候选计时补测。
- 完整 formal-003 证据包约 467 MiB，包含 9,252 个文件，作为 GitHub Release 附件发布；成员哈希和完整性记录随包提供。原包 SHA256：`a7c6c809dc87340f66c0dd65fef3a88b032d3e0dd6ee50e981d0cc60a9076faa`。包内历史“local_only”是原归档时的状态，发布记录另存，原包不改写。
- 部分历史文档引用大型原始轨迹或本机父目录设计材料。仓库内直接可读的是汇总与关键证据；完整原始轨迹通过 Release 包获取。正文科学结论以当前独立报告与固定源码引用为准。

完整性哈希证明文件与记录一致，不独立证明实验结论正确。必须同时检查评分源码、科学阈值、独立 QC 和运行状态。
