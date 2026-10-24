"""Audit retained formal results without rerunning models, solvers, or scoring."""
import csv
from collections import Counter
import json
from pathlib import Path
import subprocess
import time
from runner.common import read_json, write_json, file_hash
from runner.calibrate import METHODS
from runner.study import completed_task, frozen_plan

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
PLAN=ROOT/'freezes/research-run-plan-formal-003.json'
REPORT=ROOT/'results/formal-study-003'

def ref(value):
    path=ROOT/value['path']
    assert file_hash(path)==value['sha256'], path
    return read_json(path)

def scalar_rows(name):
    with (REPORT/(name+'.csv')).open() as f:
        return list(csv.DictReader(f))

def main():
    plan,_=frozen_plan(ROOT,PLAN)
    ledger=ROOT/'research-runs'/plan['plan_id']/'manifest.json'
    m=read_json(ledger);summary=read_json(REPORT/'summary.json')
    for task in METHODS:completed_task(ROOT,plan,m,task)
    assert len(m['attempts'])==19 and len(plan['runs'])==15
    assert summary['manifest_sha256']==file_hash(ledger)
    assert summary['scientific_sessions']==14 and summary['scientific_guidance_cells']==8
    assert summary['pending_run_ids']==[plan['plan_id']+'-poisson-g2-r1']
    assert summary['pending_baselines']==[]
    for entry in m['attempts']:
        r=ref(entry['result'])
        assert not r.get('cleanup_errors') and not r.get('bridge_errors')
        assert r['relay_cleanup']['all_removed'] and r['worker_cleanup']['all_removed']
        ref(entry['registry'])
        assert file_hash(ROOT/entry['relay_events']['path'])==entry['relay_events']['sha256']
    workers={};groups=[];checkpoints=[]
    def checkpoint(cp,task,owner,kind):
        if cp.get('checkpoint_id') is None:
            assert not cp.get('repeats')
            return
        if cp.get('reused_from'):
            assert cp['replay_count']==0 and not cp.get('repeats')
            return
        repeats=cp['repeats'];assert len(repeats)==(1 if task=='poisson' else 3)
        checkpoints.append({'owner':owner,'kind':kind,'task':task,'checkpoint_id':cp['checkpoint_id'],'source_hash':cp['source_hash'],'physical_replay_count':len(repeats),'evaluation_status':cp['evaluation_status']})
        for repeat in repeats:
            if task=='poisson':
                assert len(repeat['attempts'])==1 and repeat['selected_attempt']==0
                record=repeat['attempts'][0]['record'];samples=record['samples']
                assert [s['role'] for s in samples]==list('BCCBBC')
                invalid=repeat['evaluation_status']!='valid'
                if invalid:
                    assert repeat['speedup'] is None and repeat['score'] is None and repeat['reward'] is None
                else:
                    assert repeat['formal_timing'] and repeat['formal_environment_qualified'] and repeat['formal_evidence_valid']
                groups.append({'owner':owner,'kind':kind,'checkpoint_id':cp['checkpoint_id'],'evaluation_status':repeat['evaluation_status'],'performance_status':repeat['performance_status'],'speedup':repeat['speedup'],'score':repeat['score'],'reward':repeat['reward'],'order':[s['role'] for s in samples],'candidate_passed_counts':[s['passed'] for s in samples if s['role']=='C'],'baseline_passed_counts':[s['passed'] for s in samples if s['role']=='B']})
            else:samples=[repeat]
            for sample in samples:
                w=sample['worker'];key=w['container_id']
                assert key not in workers
                assert len(sample['cases'])==12 and len(w['cases'])==12
                assert w['all_processes_terminated'] and w['resource_limits_verified'] and w['resource_qualified']
                assert w['image']=='sha256:e0018a98b2495aa3d53698362a4d890794c728d96e7bee618eeefa4d43e2fe6a'
                workers[key]={'owner':owner,'kind':kind,'task':task,'role':sample.get('role'),'cpu_seconds':w['cpu_seconds'],'execution_wall_seconds':w['execution_wall_seconds'],'cases':len(sample['cases']),'evaluation_status':sample['evaluation_status']}
    assert len(m['baselines'])==11
    assert {(b['task'],b['method']) for b in m['baselines']}=={(t,m) for t,methods in METHODS.items() for m in methods}
    for b in m['baselines']:
        assert not b['parent_attempt']
        v=ref(b['result']);assert v['formal'] and v['split']=='final-test'
        assert v['diagnostics']['evaluation_status']=='valid'
        checkpoint(v['diagnostics'],b['task'],b['attempt_id'],'author')
    final_states=[]
    for row in plan['runs']:
        entry=[a for a in m['attempts'] if a['run_id']==row['run_id']][-1]
        assert not entry.get('replay_history')
        d=ref(entry['replay'])['diagnostics']
        final_states.append(d['evaluation_status'])
        for role in ('first','final'):checkpoint(d[role],row['task'],row['run_id']+':'+role,'research')
    assert Counter(final_states)=={'valid':14,'invalid':1}
    assert len(groups)==7 and sum(g['evaluation_status']=='valid' for g in groups)==5
    assert len(workers)==93 and sum(w['task']!='poisson' for w in workers.values())==51
    assert sum(w['cases'] for w in workers.values())==1116
    windows=[]
    for p in sorted(OUT.glob('window-*/acceptance.json')):
        a=read_json(p)
        assert not a['observer_errors']
        windows.append({'path':p.relative_to(ROOT).as_posix(),'sha256':file_hash(p),'kind':a['kind'],'identity':a['identity'],'status':a['status'],'final_test_scores_accessed':a['final_test_scores_accessed'],'violations':a.get('violations',[])})
    assert Counter(w['status'] for w in windows)=={'passed':5,'rejected':1,'host_preflight_rejected':1}
    assert not subprocess.check_output(['docker','ps','-q'],text=True).strip()
    vm=subprocess.check_output(['colima','ssh','--','cat','/proc/sys/kernel/random/boot_id'],text=True).strip()
    assert vm==read_json(ROOT/'logs/resource-acceptance-local-002/summary.json')['machine_id']
    a=scalar_rows('attempts');public=scalar_rows('public-evaluations')
    diagnosis=read_json(OUT/'closed-submission-diagnosis-016.json')['attempts']
    good=[x for x in diagnosis if x['status']=='research_frozen']
    value={'status':'execution_closed_with_one_invalid_performance_measurement','observed_at_unix':time.time(),'all_planned_operations_attempted':True,'full_valid_scientific_acceptance':False,'valid_research_sessions':15,'research_attempts':19,'non_scientific_research_attempts':4,'valid_final_scientific_results':14,'valid_scientific_guidance_cells':8,'invalid_measurement_run_ids':summary['pending_run_ids'],'unattempted_operations':[],'author_methods':11,'author_attempts':11,'with_first_final':sum(bool(x['first_id']) for x in good),'no_valid_submission':sum(not x['first_id'] for x in good),'iteration_status':dict(Counter(x['iteration_status'] for x in a if x['research_valid']=='true')),'physical_worker_batches':len(workers),'physical_worker_case_executions':1116,'heat_ode_independent_replays':51,'poisson_bccbbc_groups':len(groups),'poisson_batches':42,'model_api_requests':sum(int(x['total_api_requests']) for x in a),'successful_output_tokens_all_attempts':sum(x['known_successful_output_tokens'] for x in diagnosis),'charged_output_tokens_all_attempts':sum(x['charged_output_tokens'] for x in diagnosis),'successful_output_tokens_valid_research':sum(x['known_successful_output_tokens'] for x in good),'research_wall_seconds_all_attempts':sum(float(x['research_wall_seconds']) for x in a),'research_wall_seconds_valid_research':sum(float(x['research_wall_seconds']) for x in a if x['research_valid']=='true'),'known_public_candidate_cpu_seconds':sum(float(x['cpu_seconds']) for x in public if x['cpu_seconds']!='null'),'public_rows_with_unknown_cpu':sum(x['cpu_seconds']=='null' for x in public),'hidden_worker_cpu_seconds':sum(w['cpu_seconds'] for w in workers.values()),'hidden_worker_cpu_seconds_by_kind':{k:sum(w['cpu_seconds'] for w in workers.values() if w['kind']==k) for k in ('author','research')},'cost_usd':None,'no_running_containers':True,'vm_boot_id':vm,'plan_sha256':file_hash(PLAN),'manifest_sha256':file_hash(ledger),'report_files':{p.name:file_hash(p) for p in sorted(REPORT.iterdir()) if p.is_file()},'timing_windows':windows,'poisson_groups':groups,'checkpoints':checkpoints,'workers':workers,'interpretation':'All prescribed operations were attempted. Poisson G2 final scores and speedups remain null because its continuous host window was invalid. It is not an unexecuted run or a scientific zero. No measurement retry was performed.'}
    target=OUT/'final-audit-001.json';assert not target.exists();write_json(target,value)
    print(json.dumps({k:v for k,v in value.items() if k not in ('workers','checkpoints','timing_windows','poisson_groups','report_files')}))

if __name__=='__main__':main()
