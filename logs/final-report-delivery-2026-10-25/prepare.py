"""Scan and stage the readable final report; preserve experimental evidence."""
import base64, hashlib, json, os, re, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
selected={'.gitignore','README.md','docs/submission-report-2026-10-24.md','docs/submission-report-2026-10-24.html',
'docs/poisson-timing-recheck-2026-10-25.md','docs/reproduction.md','docs/survey.md',
'output/pdf/sciresearch-final-report-20261025.pdf','tools/build_final_report.py','tools/render_final_report.cjs',
'tools/report-requirements.txt','tools/build_delivery_manifest.py','tools/verify_delivery.py',
'results/final-report-2026-10-25/analysis.json','results/final-report-2026-10-25/ordered-results.md'}
selected.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'docs/figures/final-report').iterdir() if p.suffix in ('.png','.svg'))
tracked=set(filter(None,subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')))
old=json.loads(subprocess.check_output(['git','show','HEAD:delivery-manifest.json'],cwd=ROOT))
preserved=0
for row in old['files']:
 if row['path'] not in selected:
  assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
  preserved+=1
secrets={v.encode() for k,v in os.environ.items() if len(v)>15 and any(t in k.upper() for t in ('TOKEN','API_KEY','SECRET','PASSWORD'))}
for p in (ROOT/'build').glob('relay-*/admission.json'):
 v=json.loads(p.read_text()).get('token')
 if v:secrets.add(v.encode())
needles=secrets|{base64.b64encode(v) for v in secrets}
patterns=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'gh[pousr]_[A-Za-z0-9]{36,}',rb'github_pat_[A-Za-z0-9_]{50,}',rb'sk-[A-Za-z0-9_-]{32,}',rb'AKIA[A-Z0-9]{16}']
size=0
for name in sorted(selected|tracked):
 p=ROOT/name;assert p.is_file() and not p.is_symlink(),name
 b=p.read_bytes();size+=len(b)
 assert not any(v in b for v in needles),('known credential',name)
 assert not any(re.search(pat,b) for pat in patterns),('credential pattern',name)
subprocess.run(['git','add','-f','--pathspec-from-file=-','--pathspec-file-nul'],cwd=ROOT,input=b'\0'.join(n.encode() for n in sorted(selected))+b'\0',check=True)
subprocess.run([str(ROOT/'.venv/bin/python'),'tools/build_delivery_manifest.py'],cwd=ROOT,check=True)
subprocess.run(['git','add','delivery-manifest.json'],cwd=ROOT,check=True)
rows=[{'path':n,'bytes':(ROOT/n).stat().st_size,'sha256':hashlib.sha256((ROOT/n).read_bytes()).hexdigest()} for n in sorted(selected)]
(OUT/'selected-files.json').write_text(json.dumps({'files':rows},indent=2)+'\n')
r={'status':'passed','files_scanned':len(selected|tracked),'bytes_scanned':size,'selected_files':len(rows),
'old_deliverable_files_unchanged':preserved,'known_credential_matches':0,'credential_pattern_matches':0,
'new_model_calls':0,'new_candidate_executions':0,'g2_formal_score':None}
(OUT/'publication-scan.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
