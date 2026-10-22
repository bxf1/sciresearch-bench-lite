from pathlib import Path
from runner.common import read_json,write_json,file_hash,canonical,digest
from runner import run_plan,phase
from runner.replay import prepare_judge
root=Path.cwd(); out=root/'logs/run-plan-local-draft-005'; out.mkdir(exist_ok=False)
(out/'controller.py').write_bytes(Path(__file__).read_bytes())
def ref(p):
    p=Path(p);return {'path':str(p.relative_to(root)),'sha256':file_hash(p)}
previous=root/'freezes/research-run-plan-local-draft-004.json'; old=read_json(previous)
plan=run_plan.create_draft(root,order_entropy=old['order']['entropy_hex'])
assert plan['runs']==old['runs'] and plan['run_matrix_sha256']==old['run_matrix_sha256']
policy_path=root/'logs/model-policy-capture-local-001/heat/policy.json';policy=read_json(policy_path)
plan['system_prompt']=policy['system'];plan['tool_config'].update(runtime_tools=policy['runtime_tools'],runtime_enforcement=ref(policy_path))
plan['tool_config_sha256']=digest(canonical(plan['tool_config']))
plan['research_images']=old['research_images']
# Actual bounded relay evidence, never a claim of a served model revision or formal resource acceptance.
evidence={'status':'verified','scope':'Trusted relay wire normalization and bounded accounting, supported by the retained native local pilot; formal host resources remain pending','formal':False,'model_id':'deepseek-v4-pro','thinking':{'type':'disabled'},'temperature':0,'request_output_limit':4096,'session_output_limit':32768,'native_pilot':ref(root/'logs/harbor-native-pilot-002/result.json'),'relay_status':ref(root/'logs/harbor-native-pilot-002/relay-status-final.json') if (root/'logs/harbor-native-pilot-002/relay-status-final.json').exists() else None,'model_version':None,'version_resolution':'unresolved; no independent provider revision proof','formal_wire_policy':ref(policy_path)}
write_json(out/'model-enforcement.json',evidence)
plan['model'].update(thinking={'type':'disabled'},temperature=0,output_token_limit=32768,enforcement={key:{'status':'verified','evidence':ref(out/'model-enforcement.json')} for key in run_plan.PARAMETERS})
plan['limitations']=['Draft only; formal resource acceptance, provider revision resolution and final freezes are still pending.','Uses unchanged independently randomized 15-session matrix and exact 1800-second/20-evaluation budgets.','Actual no-turn-extension system/tools JSON captured offline in all three R images; no model request during capture.','Relay values are normalized and bounded by trusted controller; no provider revision is invented.','Final-test arrays are hashed for data identity only; no solver or hidden scoring was executed.']
judge=prepare_judge(root,root/'build/judge-draft005')
for task in phase.TASKS:
    frozen=phase.create_draft(root,root/'authoring/data/v0.3-local',task,'sha256:e0018a98b2495aa3d53698362a4d890794c728d96e7bee618eeefa4d43e2fe6a',judge)
    frozen['research'].update(model_id=plan['model']['model_id'],model_version=None,pi_version=plan['model']['pi_version'],harbor_commit=plan['model']['harbor_commit'],temperature=0,output_token_limit=32768,reasoning_configuration=plan['model']['thinking'],system_prompt_sha256=plan['system_prompt']['sha256'],tool_config_sha256=plan['tool_config_sha256'],run_matrix_sha256=plan['run_matrix_sha256'],model_version_resolution=None,model_parameter_enforcement=plan['model']['enforcement'],research_image_id=plan['research_images'][task]['image_id'],research_build_context_sha256=plan['research_images'][task]['build_context_sha256'])
    path=root/f'freezes/{task}-local-draft-005.json'; assert not path.exists();write_json(path,frozen);plan['freezes'][task]=ref(path)
path=root/'freezes/research-run-plan-local-draft-005.json';assert not path.exists();write_json(path,plan)
blockers=run_plan.start_blockers(plan,root)
write_json(out/'validation.json',{'formal_ready':not blockers,'blockers':blockers,'previous_plan':ref(previous),'current_plan':ref(path),'run_matrix_unchanged':True,'formal_sessions':0,'final_test_scores_accessed':False})
print({'formal_ready':not blockers,'blockers':blockers})
assert blockers
