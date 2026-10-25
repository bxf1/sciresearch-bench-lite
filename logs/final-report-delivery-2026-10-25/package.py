"""Package the final readable report without replacing historical evidence."""
import hashlib,json,shutil,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
rows=json.loads((OUT/'selected-files.json').read_text())['files']
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
archive=OUT/'final-report-readable-20261025.tar.gz'
manifest=OUT/'final-report-readable-manifest-20261025.json'
checksums=OUT/'final-report-readable-SHA256SUMS-20261025.txt'
pdf=OUT/'sciresearch-final-report-20261025.pdf';html=OUT/'sciresearch-final-report-20261025.html'
assert not any(p.exists() for p in (archive,manifest,checksums,pdf,html))
for row in rows:assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
with tarfile.open(archive,'w:gz') as tar:
 for row in rows:tar.add(ROOT/row['path'],arcname='sciresearch-bench-lite/'+row['path'],recursive=False)
with tarfile.open(archive) as tar:
 members=tar.getmembers();assert len(members)==len(rows)
 for member,row in zip(members,rows):
  assert member.isfile() and member.name=='sciresearch-bench-lite/'+row['path']
  b=tar.extractfile(member).read();assert len(b)==row['bytes'] and hashlib.sha256(b).hexdigest()==row['sha256']
shutil.copyfile(ROOT/'output/pdf/sciresearch-final-report-20261025.pdf',pdf)
shutil.copyfile(ROOT/'docs/submission-report-2026-10-24.html',html)
record={'source_commit':commit,'scope':'Readable final report and derived analysis; incremental package. Existing experimental evidence unchanged. G2 remains formally invalid; 2.488x is diagnostic only. No new model calls or candidate executions.',
'archive':archive.name,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':rows,'archive_members_verified':True}
manifest.write_text(json.dumps(record,indent=2)+'\n')
checksums.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (archive,manifest,pdf,html)))
assets=[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (archive,manifest,checksums,pdf,html)]
(OUT/'local-assets.json').write_text(json.dumps(assets,indent=2)+'\n')
prior=json.loads((OUT/'release-before.json').read_text())
assert not {a['name'] for a in assets}&{a['name'] for a in prior['assets']}
notes=f'''## 最终作业阅读版（2026-10-25）

[最终实验报告](https://github.com/bxf1/sciresearch-bench-lite/blob/main/docs/submission-report-2026-10-24.md)已按背景、调研、设计、评测规则、实验结果、原因与预期分析、改进和复现重新整理。明确解释 G1/G2/G3、r1/r2/r3、attempt 与评分重放；15 格结果按任务、指导组、repeat 顺序排列，另保留实际执行序号。

新增 16 页 PDF、离线 HTML、3 张结果图、可重建排序数据和脚本。源码提交 `{commit}`。PDF 和 HTML 可直接下载；`final-report-readable-20261025.tar.gz` 是阅读与分析增量包，配套 manifest 和 SHA256SUMS，不替代已有实验和作者数据。

科学结果保持：原批次 6/15 成功；thinking/max 对照 15/15 有提交、14 项正式成功、G2 正式成绩仍为空。G2 数值通过 12/12，其独立补测原始中位耗时比 2.488× 明确仅作诊断，不换算为正式分数，也不计入成功数。此次整理无模型调用、无候选重跑、未改冻结参数。

此前全部 17 个附件及原始失败、重试、计时拒绝证据保留。下文为既有发布说明。

---

'''
(OUT/'release-notes.md').write_text(notes+(prior.get('body') or ''))
print(json.dumps({'source_commit':commit,'archive_files':len(rows),'assets':assets}))
