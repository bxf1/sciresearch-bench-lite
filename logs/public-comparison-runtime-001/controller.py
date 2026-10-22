from pathlib import Path
import json,shutil,subprocess
from runner.common import write_json,file_hash,tree_hashes,canonical,digest
from runner.registry import Registry
from runner.public_evaluation import run_public_evaluation
root=Path.cwd(); out=root/'logs/public-comparison-runtime-001'
workspace=out/'workspace'
shutil.copytree(root/'baselines/poisson',workspace/'candidate',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
registry=Registry.create(out/'registry',workspace,'poisson','public-comparison-functional-probe',budget_seconds=180,max_evaluations=1)
image=json.loads(subprocess.check_output(['docker','image','inspect','sciresearch-numeric:0.3.0']))[0]['Id']
row=registry.evaluate('candidate',lambda source,cid,remaining:run_public_evaluation('poisson',source,root/'authoring/data/v0.3-local/inputs/poisson/public-dev',out/'worker',image,remaining))
registry.finalize(row['id']);registry.close()
f=row['result'];b=f.get('comparison',{})
passed=(f.get('artifact_valid') and f.get('public_check_status')=='completed' and len(f.get('cases',[]))==6 and b.get('artifact_valid') and b.get('public_check_status')=='completed' and len(b.get('cases',[]))==6 and b.get('diagnostic_wall_ratio') is not None and f.get('formal_timing') is False and b.get('formal_timing') is False)
result={'formal':False,'status':'passed' if passed else 'failed','feedback':f,'worker_image_id':image,'source_hash':row['source_hash'],'controller_sha256':file_hash(__file__),'trusted_source_hashes':{n:file_hash(root/n) for n in ('runner/worker.py','runner/public_evaluation.py','public/poisson.py','public/poisson_compare.py','runner/artifact_gate.py')}}
write_json(out/'result.json',result)
print(json.dumps({'status':result['status'],'candidate_cases':len(f.get('cases',[])),'comparator_cases':len(b.get('cases',[])),'formal_timing':False,'diagnostic_ratio':b.get('diagnostic_wall_ratio')}))
if not passed:raise SystemExit(1)
