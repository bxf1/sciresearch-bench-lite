# 九组 r1 完整实验发布说明

当前结果为 2026-11-01 完成的 Heat / ODE / Poisson × G1 / G2 / G3 × r1 九组配置。正文、图表和 README 均使用 [完整结果视图](../results/r1-complete-20261101/results.json)，来源关系保存在 [选择清单](../results/r1-complete-20261101/selection-manifest.json)。全部执行成本包含十个研究会话。

## 阅读与下载

- [22 页高清 PDF](../output/pdf/sciresearch-r1-complete-report-20261101.pdf)
- [完整报告正文](r1-complete-report-20261101.md)与[离线 HTML](r1-complete-report-20261101.html)
- [分析 JSON](../results/r1-complete-20261101/analysis.json)、[逐例 JSON](../results/r1-complete-20261101/case-results.json)和[逐例 CSV](../results/r1-complete-20261101/case-results.csv)
- [完整实验 Release](https://github.com/bxf1/sciresearch-bench-lite/releases/tag/v0.4-r1-complete-20261101)

仓库包含最新报告、图表、机器可读汇总、当前执行与评测源码，以及报告直接引用的候选和日志。完整附件 `sciresearch-r1-complete-evidence-20261101.tar.gz` 包含 162 例数据及 GT、冻结配置、全部原始记录、候选快照、计时证据和 PDF 排版检查图。相同字节文件以归档内部硬链接去重，文件路径和哈希保持不变。

[发布元数据](../data/r1-complete-20261101/publication.json)记录附件大小与 SHA-256；[归档文件清单](../data/r1-complete-20261101/archive-manifest.json)列出每个文件。Release 同时提供 PDF 和 `SHA256SUMS`。

## 只读核验

以下命令只读取文件，不调用模型、不执行候选、不启动容器：

```bash
python3 tools/verify_r1_publication.py
mkdir -p build/r1-download
gh release download v0.4-r1-complete-20261101 --repo bxf1/sciresearch-bench-lite \
  --pattern sciresearch-r1-complete-evidence-20261101.tar.gz --dir build/r1-download
python3 tools/verify_r1_publication.py \
  --archive build/r1-download/sciresearch-r1-complete-evidence-20261101.tar.gz
```

默认核对 README 与机器可读结果、报告链接和 PDF 哈希；指定附件后还核对附件 SHA-256、所有文件内容及三个原始交付清单。程序无需解压附件，只依赖 Python 标准库。

如需浏览完整目录，请解压到独立空目录，从归档中的 `START-HERE.md` 开始。附件根 README 保留原冻结版本的字节，用于原始清单验证；当前九组结果以 `docs/r1-complete-report-20261101.md` 和 `results/r1-complete-20261101/` 为准。原交付清单里的 `local_only` / `published` 是当时的状态，不因本次发布改写。

历史审计工具检查冻结时的整个目录，包含当时的 README。更新后的仓库首页与历史字节不同，当前发布请使用上述核验入口；需要核验原始交付时，在完整附件的独立目录中操作。

## 结果解释与复现边界

九个选定最终候选主测试均三次 12/12 通过，reward 均为 1。Heat 三组诊断均为 10/12，ODE 和 Poisson 均为 12/12；缓存逆序检查另列。诊断不计入正式主分。九组配置与十个实际研究会话分别统计，不把候选重放或实例数当作独立 Agent 样本。

完整附件含已结束批次的私有实例、真值及生成记录。它们用于复核，不能作为新的盲测数据。开展新研究应使用新批次和独立随机根熵，重新验收数据、规则、执行环境及性能测量；研究容器仅获得公开开发输入。

归档保留本机路径、镜像 ID 和可取得的模型路由证据。精确字节与已记录结果可离线复核；新机器的运行速度、服务商后端权重和新研究轨迹不保证与本批相同。论文式报告重建依赖本地字体和绘图库，因此新 PDF 的字节可以不同，科学数字应保持一致。
