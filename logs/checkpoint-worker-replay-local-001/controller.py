from pathlib import Path
from runner.clean_replay import registered_source
from runner.registry import Registry
from runner.replay import replay_single,prepare_judge
from runner.common import read_json,write_json,file_hash
root=Path.cwd(); out=root/'logs/checkpoint-worker-replay-local-001'; out.mkdir(exist_ok=False)
(out/'controller.py').write_bytes(Path(__file__).read_bytes())
image='sha256:e0018a98b2495aa3d53698362a4d890794c728d96e7bee618eeefa4d43e2fe6a'
judge=prepare_judge(root,out/'judge-source')
report={'formal':False,'split':'pilot-smoke','reason':'Uniform replay of all distinct retained real-model heat candidates after W process timer/lifecycle change','final_test_accessed':False,'source_hashes':{str(p.relative_to(root)):file_hash(p) for p in (root/'runner').glob('*.py')},'checkpoints':[]}
for name in ('pilot-model-registry-wj-001','research-loop-pilot-001','harbor-native-pilot-001'):
    registry=Registry(root/'logs'/name/'registry'); state=read_json(registry.root/'state.json')
    source,sha=registered_source(registry)
    results=[]
    for repeat in range(1,4):
        results.append(replay_single(source,task='heat',input_root=root/'authoring/data/pilot-smoke/inputs/heat/pilot-smoke',truth_root=root/'authoring/data/pilot-smoke/private/heat/pilot-smoke',output_root=out/name/f'replay-{repeat}',image=image,judge_source_root=judge))
    report['checkpoints'].append({'parent_run':name,'registry_sha256':file_hash(registry.root/'state.json'),'source_hash':sha,'first_id':state['first_id'],'final_id':state['final_id'],'first_final_same':state['first_id']==state['final_id'],'replays':results})
    write_json(out/'result.json',report)
    print(name,[(r['evaluation_status'],r.get('passed'),r.get('score')) for r in results],flush=True)
report['status']='completed' if all(r['evaluation_status']=='valid' for c in report['checkpoints'] for r in c['replays']) else 'evaluation_invalid'
write_json(out/'result.json',report)
