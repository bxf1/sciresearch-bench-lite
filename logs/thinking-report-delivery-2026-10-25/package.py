"""Package the final readable report without replacing historical evidence."""
import hashlib,json,shutil,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
rows=json.loads((OUT/'selected-files.json').read_text())['files']
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
archive=OUT/'thinking-only-report-20261025.tar.gz'
manifest=OUT/'thinking-only-report-manifest-20261025.json'
checksums=OUT/'thinking-only-report-SHA256SUMS-20261025.txt'
pdf=OUT/'sciresearch-thinking-report-20261025.pdf';html=OUT/'sciresearch-thinking-report-20261025.html'
assert not any(p.exists() for p in (archive,manifest,checksums,pdf,html))
for row in rows:assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
with tarfile.open(archive,'w:gz') as tar:
 for row in rows:tar.add(ROOT/row['path'],arcname='sciresearch-bench-lite/'+row['path'],recursive=False)
with tarfile.open(archive) as tar:
 members=tar.getmembers();assert len(members)==len(rows)
 for member,row in zip(members,rows):
  assert member.isfile() and member.name=='sciresearch-bench-lite/'+row['path']
  b=tar.extractfile(member).read();assert len(b)==row['bytes'] and hashlib.sha256(b).hexdigest()==row['sha256']
shutil.copyfile(ROOT/'output/pdf/sciresearch-thinking-report-20261025.pdf',pdf)
shutil.copyfile(ROOT/'docs/submission-report-2026-10-24.html',html)
record={'source_commit':commit,'scope':'Readable final report and derived analysis; incremental package. Existing experimental evidence unchanged. G2 remains formally invalid; 2.488x is diagnostic only. No new model calls or candidate executions.',
'archive':archive.name,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':rows,'archive_members_verified':True}
manifest.write_text(json.dumps(record,indent=2)+'\n')
checksums.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (archive,manifest,pdf,html)))
assets=[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (archive,manifest,checksums,pdf,html)]
(OUT/'local-assets.json').write_text(json.dumps(assets,indent=2)+'\n')
prior=json.loads((OUT/'release-before.json').read_text())
assert not {a['name'] for a in assets}&{a['name'] for a in prior['assets']}
notes=f"""## 最终作业报告：thinking/max 专版（2026-10-25）

[当前主报告](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/submission-report-2026-10-24.md)已按作业要求复核；主报告、README、表格、图表、作者基线和端到端案例只展示 thinking/max 本批结果。解释 G1/G2/G3 与 r1/r2/r3，按任务、指导组、repeat 排序，并保留实际执行序号。

**结果：15/15 有提交，14 项正式有效且成功，Poisson G2 正式计时无效。** G2 数值通过 12/12，独立补测原始耗时比 2.488× 仅作诊断，不换算成绩。作者基线 10 项有效、Jacobi-CG 独立准入拒绝，三条任务均有基线与端到端验证。修复、关联重试和无进展续接完整保留。

- [下载 16 页 PDF](https://github.com/bxf1/sciresearch-bench-lite/releases/download/v0.3-submission-20261024/sciresearch-thinking-report-20261025.pdf)
- [下载离线 HTML](https://github.com/bxf1/sciresearch-bench-lite/releases/download/v0.3-submission-20261024/sciresearch-thinking-report-20261025.html)
- [15 行原始证据索引](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/thinking-report-evidence-2026-10-25.md)
- [作业要求检查与修正清单](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/delivery-audit-thinking-2026-10-25.md)
- [上一版材料暂存](https://github.com/bxf1/sciresearch-bench-lite/tree/main/archives/pre-thinking-only-20261025)：21 个文件与逐文件 SHA256，含上版报告、PDF、图表、分析和生成脚本。

本次审计核对 77 个来源哈希、1,440 条保存的逐例评分记录、178 个本地链接和全部图表/日志节选；这些是已有重复记录的复核，不是新增实验。干净副本验证与数据表重建通过，无模型调用、无候选执行、未改冻结参数。

报告源码提交：`{commit}`。新增 `thinking-only-report-20261025.tar.gz`、同名 manifest 与 SHA256SUMS，另提供 PDF/HTML。增量包包含当前报告、图表、机器可读数据、审计脚本和上一版快照；与 main、作者数据及既有实验附件配合使用。

全部既有 22 个附件保留，包含作者数据、完整原始实验、thinking 轨迹、修复、失败和计时拒绝。先前发布说明保存在 [release-before.json](https://github.com/bxf1/sciresearch-bench-lite/blob/main/logs/thinking-report-delivery-2026-10-25/release-before.json)。历史标签的自动源码 ZIP 不是当前 main 报告版本；旧阅读附件属于历史快照。

局限：小样本、已使用过的隐藏集、模型路由内部版本不可锁定、中途执行器修复和宿主计时干扰；本版不宣称 thinking 的因果收益或真正 RSI。
"""
(OUT/'release-notes.md').write_text(notes)
print(json.dumps({'source_commit':commit,'archive_files':len(rows),'assets':assets}))
