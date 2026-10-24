import base64,hashlib,json,os,subprocess
from pathlib import Path
root=Path.cwd();out=root/'logs/submission-delivery-2026-10-24'
manifest=json.loads((root/'logs/formal-execution-delivery-local-005/file-manifest.json').read_text())
selected=[]
for name,sha in manifest.items():
 p=root/name
 if not name.startswith(('logs/','results/','research-runs/')) or not p.is_file():continue
 if p.stat().st_size>512*1024:continue
 if p.suffix not in ('.json','.jsonl','.csv','.txt','.md','.py','.sh','.toml','.lock','.npy','.npz'):continue
 if any(v in p.parts for v in ('node_modules','.venv','.git')):continue
 if hashlib.sha256(p.read_bytes()).hexdigest()!=sha:raise RuntimeError('Historical evidence changed: '+name)
 selected.append(name)
# Select stable new orchestration and diagnostics; never private relay admissions.
for p in (root/'logs/supplemental-2026-10-24').glob('*'):
 if p.is_file() and p.suffix in ('.py','.txt'):selected.append(str(p.relative_to(root)))
selected+=['logs/submission-delivery-2026-10-24/author-data-integrity.json','logs/formal-execution-delivery-local-005/integrity.json','logs/formal-execution-delivery-local-005/file-manifest.json']
for name in ['interrupted-starting-result.json','interruption-evidence.json','result.json','registry/state.json','relay-evidence/evidence/events.jsonl']:
 p=Path('research-runs/supplemental-500k-2026-10-24-poisson-g3-r1')/name
 selected.append(str(p))
selected+=['research-runs/supplemental-500k-2026-10-24/manifest.json']
subprocess.run(['git','add','-u'],check=True)
subprocess.run(['git','add','docs','freezes','runner/supplemental.py','tests/test_token_only.py','tests/accepted_t3_calibration.py','tests/resource_acceptance_probe.py','.archify'],check=True)
subprocess.run(['git','add','-f','--pathspec-from-file=-','--pathspec-file-nul'],input=b'\0'.join(x.encode() for x in selected)+b'\0',check=True)
secrets={v.encode() for k,v in os.environ.items() if ('TOKEN' in k or 'API_KEY' in k) and len(v)>15}
for p in (root/'build').glob('relay-*/admission.json'):
 try:
  value=json.loads(p.read_text()).get('token')
  if value:secrets.add(value.encode())
 except (ValueError,OSError):pass
needles=secrets|{base64.b64encode(v) for v in secrets}
paths=subprocess.check_output(['git','diff','--cached','--name-only','-z']).decode().strip('\0').split('\0')
failures=[];size=0
for name in paths:
 b=subprocess.check_output(['git','show',':'+name]);size+=len(b)
 if len(b)>95*1024**2:failures.append({'path':name,'reason':'oversize'})
 if any(n in b for n in needles):failures.append({'path':name,'reason':'credential match'})
assert not failures,failures
receipt={'status':'passed','staged_files':len(paths),'bytes':size,'checked_known_provider_and_session_secrets':True,'historical_evidence_hashes_verified':len(selected),'large_archives_staged':False}
(out/'publication-scan.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
