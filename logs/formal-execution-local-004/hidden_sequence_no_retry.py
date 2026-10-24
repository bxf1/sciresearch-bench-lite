"""Finish pending hidden operations once, retaining prior invalid measurements."""
import json
from pathlib import Path
import subprocess
import sys
from runner.common import file_hash, read_json, write_json
from runner.calibrate import METHODS
from runner.study import completed_task, frozen_plan

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
PLAN=ROOT/'freezes/research-run-plan-formal-003.json'

def main():
    plan,_=frozen_plan(ROOT,PLAN)
    ledger=ROOT/'research-runs'/plan['plan_id']/'manifest.json'
    manifest=read_json(ledger)
    for task in ('heat','ode','poisson'):completed_task(ROOT,plan,manifest,task)
    for task in ('heat','ode','poisson'):
        for method in METHODS[task]:
            rows=[b for b in manifest.get('baselines',[]) if b['task']==task and b['method']==method]
            assert len(rows)==1
            assert read_json(ROOT/rows[0]['result']['path'])['diagnostics']['evaluation_status']=='valid'
    outcomes=[]
    for row in plan['runs']:
        manifest=read_json(ledger)
        entry=[a for a in manifest['attempts'] if a['run_id']==row['run_id']][-1]
        if entry.get('replay'):
            replay=read_json(ROOT/entry['replay']['path'])
            assert file_hash(ROOT/entry['replay']['path'])==entry['replay']['sha256']
            outcomes.append({'run_id':row['run_id'],'status':replay['diagnostics']['evaluation_status'],'replay':entry['replay'],'action':'retained_without_retry'})
            continue
        if subprocess.check_output(['docker','ps','-q'],text=True).strip():raise RuntimeError('Unexpected running containers')
        task,identity=row['task'],row['run_id']
        if task=='poisson':
            command=[sys.executable,str(OUT/'observed_final.py'),'--kind','final','--identity',identity,'--output',str(OUT/('window-final-'+task+'-'+identity))]
        else:
            command=[sys.executable,'-m','runner.study','final','--plan',str(PLAN),'--data',str(ROOT/'authoring/data/v0.3-local'),'--run-id',identity]
        print(json.dumps({'event':'starting','kind':'final','task':task,'identity':identity}),flush=True)
        with (OUT/('final-'+task+'-'+identity+'.stdout.txt')).open('x') as log:
            proc=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        manifest=read_json(ledger)
        entry=[a for a in manifest['attempts'] if a['run_id']==identity][-1]
        if subprocess.check_output(['docker','ps','-q'],text=True).strip():raise RuntimeError('Containers remain after hidden operation')
        if entry.get('replay'):
            replay=read_json(ROOT/entry['replay']['path'])
            status=replay['diagnostics']['evaluation_status']
            outcomes.append({'run_id':identity,'status':status,'replay':entry['replay'],'action':'attempted_once'})
        else:
            status='not_admitted'
            outcomes.append({'run_id':identity,'status':status,'action':'not_retried','exit_code':proc.returncode})
        print(json.dumps({'event':'finished','identity':identity,'exit_code':proc.returncode,'status':status}),flush=True)
    record={'status':'all_planned_operations_processed_without_retries','research_sessions':15,'research_attempts':len(manifest['attempts']),'baseline_methods':11,'outcomes':outcomes,'valid_final_replays':sum(x['status']=='valid' for x in outcomes),'invalid_final_replays':sum(x['status'] not in ('valid','not_admitted') for x in outcomes),'not_admitted_final_replays':sum(x['status']=='not_admitted' for x in outcomes),'manifest_sha256':file_hash(ledger)}
    target=OUT/'hidden-phase-completion.json';assert not target.exists();write_json(target,record)
    print(json.dumps({k:v for k,v in record.items() if k!='outcomes'}),flush=True)
    return 0 if not record['not_admitted_final_replays'] else 2

if __name__=='__main__':raise SystemExit(main())
