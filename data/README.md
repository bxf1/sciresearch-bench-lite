# 三任务数据交付

数据均由数学模型合成，不使用外部实测样本。数据集共 90 例：每任务 6 个 public-dev、12 个 author-calibration、12 个 final-test；每个 split 内三个难度均衡。数据只按预声明的合法性、独立真值与数值质量检查保留，不按方法成绩筛选。

| 任务 | 仓库直接包含的公开输入 | 完整实例数 | 数据卡 |
|---|---|---:|---|
| Heat 热逆问题 | [6 个 dev 实例](../tasks/heat/environment/public-dev/) | 30 | [公式、格式与 QC](../docs/heat.md) |
| ODE 动力学辨识 | [6 个 dev 实例](../tasks/ode/environment/public-dev/) | 30 | [公式、格式与 QC](../docs/ode.md) |
| Poisson 稀疏求解 | [6 个 dev 实例](../tasks/poisson/environment/public-dev/) | 30 | [公式、格式与 QC](../docs/poisson.md) |

- [case-index.csv](case-index.csv)：90 例逐例索引、task/split/level、文件数、大小、QC 判定、路径与哈希。
- [split-summary.json](split-summary.json)：9 个 task/split 的数量与 QC 通过统计。
- [file-manifest.json](file-manifest.json)：完整作者归档的 1,364 个文件、大小和 SHA256，包括公开输入、作者输入、参考真值、QC 与生成记录。

完整原数据已发布在 [Release](https://github.com/bxf1/sciresearch-bench-lite/releases/tag/v0.3-submission-20261024) 的 `author-data-v0.3.tar.gz`（27,088,532 bytes）。归档根目录为 `author-data-v0.3/`。SHA256：

```text
b4dcff0acd251c9060ce73faf11b85d61217445334017339ec7eba15e33ca68b
```

在仓库根目录下载和只读验证：

```bash
mkdir -p authoring/data/downloads
gh release download v0.3-submission-20261024 --repo bxf1/sciresearch-bench-lite \
  --pattern author-data-v0.3.tar.gz --dir authoring/data/downloads
python3 tools/verify_delivery.py --author-archive authoring/data/downloads/author-data-v0.3.tar.gz
# 确认 authoring/data/author-data-v0.3 尚不存在后解压
tar -xzf authoring/data/downloads/author-data-v0.3.tar.gz -C authoring/data
```

没有 GitHub CLI 时可从 Release 页面直接下载后执行同一校验命令。校验不解压文件、不调用模型、不执行候选。完整归档含参考答案与生成熵，只供作者和可信评分程序使用；运行研究 Agent 时仅挂载对应 public-dev，不挂整个数据目录或仓库。

复现实验的命令和新机器限制见[复现指南](../docs/reproduction.md)。当前索引从已发布归档逐文件对照本地原数据生成，90 例 QC 均通过；这是既有证据核对，不是重新选择数据或重新跑实验。
