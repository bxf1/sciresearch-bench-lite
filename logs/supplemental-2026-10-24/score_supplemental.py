"""Independent replays after all six research sessions close; originals immutable."""
import argparse,json,runpy,subprocess,threading,time
from pathlib import Path
from runner import supplemental as sup
from runner.common import read_json,write_json,file_hash,tree_hashes
from runner.registry import Registry
from runner.replay import prepare_judge,replay_single,replay_checkpoint
from runner.study import score_checkpoints
from runner.phase import guard_replay,RESOURCES
from runner.worker import docker
ROOT=Path.cwd();sup.PLAN=ROOT/'freezes/supplemental-500k-2026-10-24-recovery-001.json'
OUT=ROOT/'results/supplemental-2026-10-24'

def barrier():
 plan=sup.load_plan();p=ROOT/'research-runs'/plan['plan_id']/'manifest.json'
 manifest=read_json(p);entries={e['run_id']:e for e in manifest['attempts']}
 if any(e['status']=='research_invalid' for e in entries.values()):raise RuntimeError('invalid infrastructure attempt requires investigation')
 if len(entries)!=6 or any(e['status']!='research_frozen' for e in entries.values()):return None
 for e in entries.values():
  result=read_json(sup.checked(e['result']));state=read_json(sup.checked(e['registry']))
  assert result['status']=='research_frozen' and state['closed']
  assert result['attempt_status'] in ('completed','research_timeout')
 assert not docker('ps','-q').stdout.strip(),'research containers still present'
 return plan,entries

def timed(out,action):
 module=runpy.run_path(str(ROOT/'tests/accepted_t3_calibration.py'))
 Observer,POLICY=module['Observer'],module['POLICY']
 assert file_hash(ROOT/'tests/accepted_t3_calibration.py')==file_hash(ROOT/'logs/t3-formal-calibration-local-005/controller.py')
 resource_path=ROOT/'logs/resource-acceptance-local-002/summary.json';resource=read_json(resource_path)
 assert resource['formal_resources_accepted'] and resource['resources']==RESOURCES
 machine=subprocess.check_output(['colima','ssh','--','cat','/proc/sys/kernel/random/boot_id'],text=True).strip()
 assert machine==resource['machine_id']
 out.mkdir(parents=True,exist_ok=False)
 write_json(out/'observation-policy.json',POLICY)
 observer=Observer(out/'host-observations.jsonl');observer.sample()
 thread=threading.Thread(target=observer.watch,daemon=True);thread.start()
 acceptance={'status':'starting','model_calls':0,'hidden_scores_accessed':False}
 try:
  start=time.time();time.sleep(POLICY['preflight_seconds']);observer.sample()
  violations=observer.violations_since(start)
  if violations or observer.errors:
   acceptance.update(status='host_preflight_rejected',violations=violations,observer_errors=observer.errors)
   return None
  start=time.time()
  exclusive={'status':'passed','machine_exclusive_verified':True,'machine_id':machine,'other_host_workloads':[],'cache_state':POLICY['cache_policy'],'measurement_window_unix':[start,start+1800],'scope':'New supplemental timing window; original invalid measurement retained.','observer_policy':{'path':'observation-policy.json','sha256':file_hash(out/'observation-policy.json')},'quiet_preflight_seconds':POLICY['preflight_seconds'],'continuous_observation_required':True}
  write_json(out/'exclusive-window.json',exclusive)
  write_json(out/'timing-contract.json',{'status':'frozen','resources':RESOURCES,'image_id':resource['numeric_image_id'],'resource_evidence':{'path':str(resource_path),'sha256':file_hash(resource_path)},'exclusivity_evidence':{'path':'exclusive-window.json','sha256':file_hash(out/'exclusive-window.json')}})
  def measured(*args,**kwargs):
   row=replay_single(*args,**kwargs);observer.sample()
   violations=observer.violations_since(start)
   if violations or observer.errors:row.update(evaluation_status='evaluation_invalid',score=None,reward=None,host_window_violations=violations,observer_errors=list(observer.errors))
   return row
  def checkpoint(*args,**kwargs):
   row=replay_checkpoint(*args,execute=measured,**kwargs)
   time.sleep(POLICY['sample_interval_seconds']);observer.sample();violations=observer.violations_since(start)
   if violations or observer.errors:
    row.update(evaluation_status='evaluation_invalid',performance_status='invalid_environment',score=None,reward=None,speedup=None,formal_timing=False,formal_environment_qualified=False,formal_evidence_valid=False,retry_permitted=False,host_window_violations=violations)
    write_json(Path(kwargs['output_root'])/'result.json',row)
   return row
  acceptance['hidden_scores_accessed']=True
  value=action(out/'timing-contract.json',checkpoint)
  observer.sample();violations=observer.violations_since(start)
  acceptance.update(status='passed' if value['evaluation_status']=='valid' and not violations and not observer.errors else 'rejected',violations=violations,observer_errors=observer.errors)
  return value
 finally:
  observer.stop.set();thread.join(timeout=10)
  acceptance['host_observations_sha256']=file_hash(observer.path)
  write_json(out/'acceptance.json',acceptance)

def evaluate(identity,task,registry_ref,freeze_ref,kind):
 target=OUT/identity
 result_path=target/'result.json'
 if result_path.exists():return read_json(result_path)
 target.mkdir(parents=True,exist_ok=False)
 state_path=sup.checked(registry_ref);state=read_json(state_path);assert state['closed']
 registry=Registry(state_path.parent);freeze_path=sup.checked(freeze_ref);freeze=read_json(freeze_path)
 judge=prepare_judge(ROOT,target/'judge-source');assert tree_hashes(judge)==freeze['judge_source_hashes']
 data=ROOT/'authoring/data/v0.3-local'
 config={'task':task,'input_root':data/'inputs'/task/'final-test','truth_root':data/'private'/task/'final-test','output_root':target/'replays','image':freeze['image_id'],'judge_source_root':judge,'freeze_path':freeze_path,'profile':freeze['profile']}
 guard_replay(task,config['input_root'],config['truth_root'],config['image'],judge,freeze_path=freeze_path,profile=freeze['profile'])
 wrapper={'kind':kind,'run_id':identity,'task':task,'registry':registry_ref,'freeze':freeze_ref,'original_results_replaced':False,'model_calls':0}
 if task=='poisson':
  def action(contract,execute):
   return score_checkpoints(registry,state,dict(config,baseline_source=ROOT/'baselines/poisson',timing_contract=contract),execute=execute)
  diagnostics=timed(target/'timing',action)
  if diagnostics is None:diagnostics={'evaluation_status':'not_run','score':None,'reward':None,'reason':'host_preflight_rejected; no hidden replay performed'}
 else:diagnostics=score_checkpoints(registry,state,config)
 sup.checked(registry_ref)
 wrapper['diagnostics']=diagnostics;write_json(result_path,wrapper)
 print(json.dumps({'run_id':identity,'evaluation_status':diagnostics['evaluation_status'],'score':diagnostics.get('score'),'reward':diagnostics.get('reward')}),flush=True)
 return wrapper

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--wait',action='store_true');args=parser.parse_args()
 while True:
  ready=barrier()
  if ready:break
  if not args.wait:raise RuntimeError('research incomplete; hidden data not accessed')
  time.sleep(20)
 plan,entries=ready;OUT.mkdir(parents=True,exist_ok=True)
 write_json(OUT/'research-barrier.json',{'status':'passed','plan':sup.reference(sup.PLAN),'closed_entries':list(entries.values()),'checked_at':time.time(),'all_six_closed':True,'no_running_containers':True})
 results=[]
 # Timing-only replay uses the exact original G2 snapshots, no model session.
 original=read_json(sup.checked(plan['previous_plan']));m=read_json(sup.checked(plan['previous_ledger']))
 e=next(e for e in reversed(m['attempts']) if e['run_id'].endswith('poisson-g2-r1'))
 results.append(evaluate('original-poisson-g2-timing-only','poisson',e['registry'],original['freezes']['poisson'],'timing_only'))
 for row in plan['runs']:
  s=row['settings'];e=entries[s['run_id']]
  results.append(evaluate(s['run_id'],s['task'],e['registry'],row['freeze'],'selective_500k_supplemental'))
 write_json(OUT/'summary.json',{'study_kind':'selective_supplemental','not_equal_budget_comparison':True,'original_results_replaced':False,'results':results})
if __name__=='__main__':main()
