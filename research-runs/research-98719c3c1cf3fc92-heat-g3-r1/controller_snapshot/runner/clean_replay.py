"""Re-run fixed references and one registered model snapshot from a Git archive.

Uses a fresh source/data/output directory and fresh W/J containers on the same
Docker host. This is a clean-directory functional check, not independent-host
or formal resource/performance acceptance. Only pilot-smoke input is accepted.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from .common import canonical, digest, file_hash, read_json, tree_hashes, write_json
from .registry import Registry

SCRIPT = '''from pathlib import Path
import json,sys
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'source'))
from runner.replay import prepare_judge,replay_single
from runner.common import write_json
config=json.loads((root/'config.json').read_text())
judge=prepare_judge(root/'source',root/'judge-source')
rows=[]
for task,method,source in [('heat','tikhonov',root/'source/baselines/heat'),('ode','fixed',root/'source/baselines/ode'),('poisson','lu',root/'source/baselines/poisson'),('heat',None,root/'model-source')]:
    label=task+'-'+(method or 'model')
    row=replay_single(source,task=task,input_root=root/'data/inputs'/task/'pilot-smoke',truth_root=root/'data/private'/task/'pilot-smoke',output_root=root/'replays'/label,image=config['image'],judge_source_root=judge,method=method)
    rows.append({'label':label,'result':row})
write_json(root/'result.json',{'formal':False,'scope':'fresh Git archive and fresh containers on the same host','config':config,'runs':rows,'status':'completed' if all(r['result']['evaluation_status']=='valid' for r in rows) else 'evaluation_invalid'})
print(json.dumps([{'label':r['label'],'passed':r['result'].get('passed'),'total':r['result'].get('total'),'score':r['result'].get('score'),'reward':r['result'].get('reward'),'status':r['result']['evaluation_status']} for r in rows]))
'''


def registered_source(registry):
    state=read_json(registry.root/'state.json')
    if not state['closed'] or state['task']!='heat' or not state['final_id']:
        raise ValueError('A closed heat pilot registry with a final candidate is required')
    if state.get('attempt_status') not in (None,'completed','research_timeout') or state.get('finalization_invalid'):
        raise ValueError('A failed research attempt cannot satisfy clean replay acceptance')
    rows=[row for row in state['evaluations'] if row['id']==state['final_id']]
    if len(rows)!=1 or not rows[0].get('completed_at') or not rows[0].get('artifact_valid'):
        raise ValueError('Final candidate must be a completed, valid registered evaluation')
    snapshot=registry.verified_snapshot(state['final_id'])
    source_hash=digest(canonical(tree_hashes(snapshot)))
    if source_hash!=rows[0]['source_hash']:
        raise ValueError('Snapshot hash differs from the registered evaluation')
    return snapshot,source_hash


def run(args):
    project=Path(__file__).resolve().parents[1]
    output=args.output.resolve()
    registry=Registry(args.registry.resolve(strict=True))
    snapshot,source_hash=registered_source(registry)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip()
    output.mkdir(parents=True,exist_ok=False)
    archive=output/'source.tar'
    with archive.open('xb') as stream:
        subprocess.run(['git','archive','--format=tar',revision,'authoring','baselines','judge','public','runner','tasks','prompts','requirements.txt','pytest.ini','tests'],cwd=project,stdout=stream,check=True)
    source=output/'source'
    source.mkdir()
    with tarfile.open(archive) as stream:
        stream.extractall(source,filter='data')
    data=args.data.resolve(strict=True)
    for task in ('heat','ode','poisson'):
        for side in ('inputs','private'):
            shutil.copytree(data/side/task/'pilot-smoke',output/'data'/side/task/'pilot-smoke')
    shutil.copytree(snapshot,output/'model-source')
    if digest(canonical(tree_hashes(output/'model-source')))!=source_hash:
        raise RuntimeError('Registered source changed during clean-directory preparation')
    image=json.loads(subprocess.check_output(['docker','image','inspect',args.image]))[0]['Id']
    write_json(output/'config.json',{'source_commit':revision,'archive_sha256':file_hash(archive),'image':image,
        'model_registry_sha256':file_hash(registry.root/'state.json'),'model_source_hash':source_hash,
        'source_tree_hashes':tree_hashes(source),'pilot_data_hashes':tree_hashes(output/'data'),
        'controller_sha256':file_hash(__file__),'formal':False,'final_test_accessed':False})
    (output/'controller.py').write_bytes(Path(__file__).read_bytes())
    (output/'execute.py').write_text(SCRIPT)
    executed=subprocess.run([sys.executable,'-I',str(output/'execute.py')],cwd=output,capture_output=True,text=True)
    (output/'stdout.txt').write_text(executed.stdout)
    (output/'stderr.txt').write_text(executed.stderr)
    print(executed.stdout)
    if executed.returncode:
        raise RuntimeError('Clean-directory replay failed; retained stderr and all outputs')
    return read_json(output/'result.json')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('registry','data','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--image',default='sciresearch-numeric:0.3.0')
    run(p.parse_args())
