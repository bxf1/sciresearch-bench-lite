from pathlib import Path
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
