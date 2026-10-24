from pathlib import Path
import base64, hashlib, json, os, re, subprocess
root=Path.cwd()
tracked=set(filter(None,subprocess.check_output(['git','ls-files','-z']).decode().split('\0')))
docs=['README.md','data/README.md','docs/reproduction.md','docs/submission-report-2026-10-24.md','docs/evidence.md','docs/survey.md','docs/task_cards.md']
broken=[];count=0
for name in docs:
 p=root/name
 for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if link.startswith(('https:','http:','#','mailto:')): continue
  path=(p.parent/link.split('#')[0]).resolve();count+=1
  if not path.exists(): broken.append({'document':name,'target':link,'reason':'missing'})
  elif path.is_file() and str(path.relative_to(root)) not in tracked: broken.append({'document':name,'target':link,'reason':'untracked'})
assert not broken,broken
secrets={v.encode() for k,v in os.environ.items() if any(x in k.upper() for x in ('TOKEN','API_KEY','PASSWORD','SECRET')) and len(v)>15}
for p in (root/'build').glob('relay-*/admission.json'):
 v=json.loads(p.read_text()).get('token','')
 if v: secrets.add(v.encode())
needles=secrets|{base64.b64encode(v) for v in secrets}
patterns=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', rb'gh[pousr]_[A-Za-z0-9]{36,}', rb'github_pat_[A-Za-z0-9_]{50,}', rb'sk-[A-Za-z0-9_-]{32,}', rb'AKIA[A-Z0-9]{16}']
failures=[];size=0
for name in sorted(tracked):
 p=root/name
 if not p.is_file():continue
 b=p.read_bytes();size+=len(b)
 if any(n in b for n in needles): failures.append({'path':name,'reason':'known credential'})
 if any(re.search(pattern,b) for pattern in patterns): failures.append({'path':name,'reason':'credential-shaped string'})
 if p.suffix=='.env' or 'admission.json'==p.name or name.startswith('build/'): failures.append({'path':name,'reason':'private runtime path'})
assert not failures,failures
receipt={'status':'passed','files_scanned':len(tracked),'bytes':size,'known_credential_and_base64_matches':0,'credential_pattern_matches':0,'private_runtime_paths':0,'local_document_links_checked':count,'broken_local_links':0,'new_model_calls':0}
(root/'logs/submission-delivery-2026-10-24/submission-ready-scan.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
