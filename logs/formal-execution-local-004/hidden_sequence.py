"""Run the predeclared hidden phase only after all 15 research sessions close.

No retries: any invalid measurement stops for protocol-specific investigation.
"""
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
    for task in ('heat','ode','poisson'): completed_task(ROOT,plan,manifest,task)
    operations=[]
    for task in ('heat','ode','poisson'):
        for method in METHODS[task]: operations.append(('baseline',task,method))
    for row in plan['runs']: operations.append(('final',row['task'],row['run_id']))
    for kind,task,identity in operations:
        manifest=read_json(ledger)
        if kind=='baseline':
            existing=[x for x in manifest.get('baselines',[]) if x['task']==task and x['method']==identity]
            if existing:
                assert read_json(ROOT/existing[-1]['result']['path'])['diagnostics']['evaluation_status']=='valid'
                continue
        else:
            entry=[x for x in manifest['attempts'] if x['run_id']==identity][-1]
            if entry.get('replay'):
                assert read_json(ROOT/entry['replay']['path'])['diagnostics']['evaluation_status']=='valid'
                continue
        if subprocess.check_output(['docker','ps','-q'],text=True).strip():
            raise RuntimeError('Unexpected running containers before hidden operation')
        name=kind+'-'+task+'-'+identity
        if task=='poisson':
            command=[sys.executable,str(OUT/'observed_final.py'),'--kind',kind,'--identity',identity,
                     '--output',str(OUT/('window-'+name))]
        else:
            command=[sys.executable,'-m','runner.study',kind,'--plan',str(PLAN),
                     '--data',str(ROOT/'authoring/data/v0.3-local')]
            command+=['--task',task,'--method',identity] if kind=='baseline' else ['--run-id',identity]
        print(json.dumps({'event':'starting','kind':kind,'task':task,'identity':identity}),flush=True)
        with (OUT/(name+'.stdout.txt')).open('x') as log:
            proc=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        print(json.dumps({'event':'finished','kind':kind,'task':task,'identity':identity,'exit_code':proc.returncode}),flush=True)
        if proc.returncode: return proc.returncode
    write_json(OUT/'hidden-phase-completion.json',{'status':'completed','operations':len(operations),
        'research_sessions':15,'baseline_methods':11,'manifest_sha256':file_hash(ledger)})
    return 0

if __name__=='__main__': raise SystemExit(main())
