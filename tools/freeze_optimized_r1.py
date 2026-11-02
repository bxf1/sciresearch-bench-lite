"""Freeze the new nine-session study only after all measured prerequisites pass."""
import copy
import datetime
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runner import run_plan,phase
from runner.common import read_json,write_json,file_hash,canonical,digest
from runner.replay import prepare_judge
from runner.model_relay import Limits
from runner.study import session_spec

OUT=ROOT/'logs/optimized-r1-20261101'
DATA=ROOT/'authoring/data/optimized-r1-20261101'
PLAN=ROOT/'freezes/research-run-plan-optimized-r1-20261101.json'

def ref(path):
    path=Path(path).resolve(strict=True)
    return {'path':path.relative_to(ROOT).as_posix(),'sha256':file_hash(path)}

def evidence(name,value):
    path=OUT/(name+'.json')
    write_json(path,value)
    return ref(path)

def main():
    assert not PLAN.exists(),'Never overwrite a frozen plan'
    offline=read_json(OUT/'offline-acceptance.json');assert offline['status']=='passed'
    units=read_json(OUT/'unit-acceptance.json');assert units['status']=='passed'
    runtime=read_json(OUT/'runtime-probes/summary.json');assert runtime['passed']==runtime['total']
    timer=read_json(OUT/'timer-probes/summary.json');assert timer['passed']==timer['total']
    timing=read_json(OUT/'timing-calibration/summary.json')
    assert timing['formal_profile_ready'] and timing['profile']=='efficiency_gate_1.5'
    live=read_json(OUT/'live-context-probe/result.json');assert live['status']=='passed' and live['cleanup']['all_removed']
    assert read_json(OUT/'native-offline-tests.json')['status']=='passed'
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    validation=evidence('executor-validation',{'status':'passed','unit_tests':ref(OUT/'unit-acceptance.json'),
        'native_tests':ref(OUT/'native-offline-tests.json'),'live_probe':ref(OUT/'live-context-probe/result.json'),
        'request_output_limit':16384,'native_compaction_retained':True,'native_tool_event_timestamps':True})
    bundle=read_json(OUT/'native-patches-draft.json')
    bundle.update(authorization=ref(OUT/'authorization.json'),validation=validation)
    bundle_ref=evidence('native-patch-bundle',bundle)
    old=read_json(ROOT/'freezes/research-run-plan-unified-ode-poisson-r1-2026-10-29.json')
    # The unexecuted draft only supplies a fresh independent ordering seed. It
    # creates no sessions; the actual scope below contains exactly nine rows.
    base=run_plan.create_draft(ROOT)
    base_ref=evidence('unexecuted-order-draft',base)
    plan=run_plan.create_draft(ROOT,order_entropy=base['order']['entropy_hex'],identity_revision='optimized-r1-20261101',
           run_scope=[{'task':task,'repeat':1} for task in phase.TASKS])
    plan.update(status='frozen',formal_ready=True,frozen_at=now,previous_plan=base_ref,
                revision_authorization=ref(OUT/'authorization.json'),study_kind='fresh_nine_r1_with_independent_diagnostics',
                execution_policy={'budget_reminders':True,'max_infrastructure_retries':1,
                                  'global_research_closure_before_hidden_scoring':True,'max_timing_attempts':3})
    policy=read_json(OUT/'wire-policy/heat/policy.json')
    for task in phase.TASKS:
        other=read_json(OUT/'wire-policy'/task/'policy.json')
        assert other['wire_system_sha256']==policy['wire_system_sha256'] and other['wire_tools_sha256']==policy['wire_tools_sha256']
    plan['system_prompt']=policy['system']
    plan['tool_config'].update(runtime_tools=policy['runtime_tools'],runtime_enforcement=ref(OUT/'wire-policy/heat/policy.json'),native_patch_bundle=bundle_ref)
    plan['tool_config_sha256']=digest(canonical(plan['tool_config']))
    assert units['trusted_tool_hashes']==plan['tool_config']['files'],'Sources changed after unit acceptance'
    model=copy.deepcopy(old['model'])
    enforcement=evidence('model-enforcement',{'status':'verified','request_output_limit':16384,'session_output_limit':200000,
                 'thinking':{'type':'enabled'},'output_config':{'effort':'max'},'temperature':None,'validation':validation})
    for key in ('thinking','output_token_limit','output_config'):model['enforcement'][key]={'status':'verified','evidence':enforcement}
    model['enforcement']['temperature'].update(evidence=ref(OUT/'provider-documentation.json'))
    model['version_resolution'].update(evidence=ref(OUT/'provider-documentation.json'))
    model.update(model_version='DeepSeek-V4.1-Flash-1017',request_output_limit=16384,output_token_limit=200000)
    plan['model']=model
    plan['runtime_policy']=Limits(session_seconds=2700,session_output_limit=200000,request_output_limit=16384,max_requests=3125,
             thinking_effort='max',expected_system_sha256=policy['wire_system_sha256'],expected_tools_sha256=policy['wire_tools_sha256'],
             expected_compaction_system_sha256=policy['native_compaction']['wire_system_sha256']).public()
    plan['research_images']=read_json(OUT/'research-images.json')['research_images']
    judge=prepare_judge(ROOT,OUT/'frozen-judge-source')
    resources=read_json(OUT/'resource-acceptance/summary.json')
    inventory=read_json(DATA/'diagnostic-views/inventory.json')
    for task in phase.TASKS:
        frozen=phase.create_draft(ROOT,DATA,task,resources['numeric_image_id'],judge)
        frozen.update(status='frozen',frozen_at=now,profile='efficiency_gate_1.5' if task=='poisson' else 'accuracy')
        frozen['diagnostic_data']={key:{field:view[field] for field in ('input_hashes','truth_hashes')} for key,view in inventory[task].items()}
        frozen['diagnostic_data_sha256']=digest(canonical(frozen['diagnostic_data']))
        checks={'gt_qc':ref(OUT/'gt-qc.json'),
                'calibration':evidence(task+'-calibration-acceptance',{'status':'passed','main':ref(OUT/'main-calibration/summary.json'),
                      'diagnostic':ref(OUT/'diagnostic-calibration/summary.json'),'rules':ref(OUT/'rule-fixtures.json')}),
                'scorer_tests':ref(OUT/'unit-acceptance.json'),
                'isolation':evidence(task+'-isolation',{'status':'passed','runtime':ref(OUT/'runtime-probes/summary.json'),
                      'timer':ref(OUT/'timer-probes/summary.json'),'offline_native_capture':ref(OUT/'wire-policy'/task/'policy.json'),
                      'resources':ref(OUT/'resource-acceptance/summary.json')}),
                'resources':ref(OUT/'resource-acceptance/summary.json'),
                'model_smoke':evidence(task+'-model-smoke',{'status':'passed','shared_native_executor_live_probe':ref(OUT/'live-context-probe/result.json'),
                      'task_image_wire_capture':ref(OUT/'wire-policy'/task/'policy.json'),'scope':'Shared transport and native recovery live-tested without scientific data; task-specific pinned images captured offline.'})}
        if task=='poisson':checks['timing_profile']=ref(OUT/'timing-calibration/summary.json')
        frozen['acceptance']={key:{'status':'passed','evidence_sha256':value['sha256']} for key,value in checks.items()}
        frozen['research'].update(model_id=model['model_id'],model_version=model['model_version'],pi_version=model['pi_version'],
            harbor_commit=model['harbor_commit'],output_token_limit=200000,request_output_limit=16384,temperature=None,
            reasoning_configuration=model['thinking'],output_config=model['output_config'],
            model_version_resolution=model['version_resolution'],model_parameter_enforcement=model['enforcement'],
            research_image_id=plan['research_images'][task]['image_id'],research_build_context_sha256=plan['research_images'][task]['build_context_sha256'],
            system_prompt_sha256=plan['system_prompt']['sha256'],tool_config_sha256=plan['tool_config_sha256'],run_matrix_sha256=plan['run_matrix_sha256'])
        frozen['limitations']=['One r1 per group; no statistical population ranking.','Independent diagnostics excluded from main score.']
        phase.validate_freeze_document(frozen,task)
        plan['freezes'][task]=evidence(task+'-freeze',frozen)
        plan['acceptance_evidence'][task]=checks
    plan['limitations']=['Exactly nine new r1 scientific sessions, plus separately accounted infrastructure attempts.',
                        'Provider alias identity is documented but not immutable.','Fresh data and multiple protocol improvements do not identify a causal change relative to earlier results.']
    run_plan.validate_start(plan,ROOT)
    write_json(PLAN,plan)
    for row in plan['runs']:
        spec=session_spec(ROOT,PLAN,row['run_id'],row['run_id']+'-a001')
        assert spec['settings']['budget_reminders'] and spec['settings']['request_output_limit']==16384
    for name in plan['tool_config']['files']:
        destination=OUT/'source-snapshot'/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,destination)
    evidence('freeze-validation',{'status':'passed','plan':ref(PLAN),'scientific_sessions':9,'research_started':False})
    print(plan['plan_id'],len(plan['runs']),'frozen')

if __name__=='__main__':main()
