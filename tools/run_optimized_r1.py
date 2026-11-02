"""Serial nine-session controller, global closure, fixed-candidate tests and restoration."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runner.common import read_json,write_json,file_hash
from runner.study import frozen_plan,start,final,completed_task
from runner.run_plan import _file_ref
from runner.observed import observed_bccbbc
from runner.diagnostics import evaluate_final
from runner.exploration import build_timeline

OUT=ROOT/'logs/optimized-r1-20261101'
DATA=ROOT/'authoring/data/optimized-r1-20261101'
PLAN=ROOT/'freezes/research-run-plan-optimized-r1-20261101.json'
RESULTS=ROOT/'results/optimized-r1-20261101'

def record(stage,**details):
    row={'stage':stage,'updated_at':time.time(),'pid':os.getpid(),**details}
    write_json(OUT/'state.json',row);print(json.dumps(row),flush=True)

def main():
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(143))
    plan,reference=frozen_plan(ROOT,PLAN)
    assert len(plan['runs'])==9 and all(r['repeat']==1 for r in plan['runs'])
    ledger_path=ROOT/'research-runs'/plan['plan_id']/'manifest.json'
    assert not ledger_path.exists(),'This controller never silently resumes research'
    name='dcomp-demo-postgres'
    running=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
    assert set(running).issubset({name})
    restore=name in running
    service={'before_running':restore,'restored':False,'started_at':time.time()}
    write_json(OUT/'study-service-restoration.json',service)
    RESULTS.mkdir(exist_ok=False)
    try:
        if restore:subprocess.run(['docker','stop',name],check=True,stdout=subprocess.DEVNULL)
        for row in plan['runs']:
            assert not subprocess.check_output(['docker','ps','-q'],text=True).strip()
            record('research_running',run_id=row['run_id'],sequence=row['sequence'],closed_sessions=row['sequence']-1,hidden_scores_accessed=False)
            result=asyncio.run(start(ROOT,PLAN,row['run_id']))
            if result['attempt_status'] in {'api_failed','infrastructure_failed'}:
                ledger=read_json(ledger_path);parent=ledger['attempts'][-1]['attempt_id']
                record('linked_infrastructure_retry',run_id=row['run_id'],parent_attempt=parent,reason=result.get('attempt_reason',result.get('error')))
                result=asyncio.run(start(ROOT,PLAN,row['run_id'],retry_of=parent))
            if result['attempt_status']=='cancelled':raise KeyboardInterrupt('research cancelled')
            build_timeline(ROOT,plan,RESULTS/'exploration-timeline.json')
        ledger=read_json(ledger_path)
        latest=completed_task(ROOT,plan,ledger,'heat')  # Global policy checks all nine.
        write_json(OUT/'research-closure.json',{'status':'passed','all_nine_closed':True,'closed_at':time.time(),
                   'manifest_sha256':file_hash(ledger_path),'hidden_scoring_started':False})
        results=[]
        resource=OUT/'resource-acceptance/summary.json'
        def checkpoint(source,checkpoint_id,source_hash,**config):
            config.pop('timing_contract',None)
            value=observed_bccbbc(source,resource_path=resource,**config)
            return {**value,'checkpoint_id':checkpoint_id,'source_hash':source_hash}
        def diagnostic(source,**config):
            return observed_bccbbc(source,resource_path=resource,baseline_source=ROOT/'baselines/poisson',
                                    profile='efficiency_gate_1.5',**config)
        for row in plan['runs']:
            entry=latest[row['run_id']]
            host=read_json(_file_ref(ROOT,entry['result']))
            record('main_scoring',run_id=row['run_id'],all_nine_closed=True)
            if host['attempt_status'] in {'api_failed','infrastructure_failed'}:
                value={'diagnostics':{'evaluation_status':'invalid','score':None,'reward':None},
                       'reason':'infrastructure_attempts_exhausted','attempt_id':entry['attempt_id']}
            else:
                options={'timing_contract':resource,'execute':checkpoint} if row['task']=='poisson' else {}
                value=final(ROOT,PLAN,row['run_id'],DATA,**options)
            results.append({'run':row,'attempt':entry,'host_status':host['attempt_status'],'main':value})
            write_json(RESULTS/'results.json',{'plan':reference,'scientific_sessions':9,'rows':results,'status':'main_scoring'})
        for result in results:
            row=result['run'];record('diagnostic_scoring',run_id=row['run_id'],all_nine_closed=True)
            if result['host_status'] in {'api_failed','infrastructure_failed'}:
                result['diagnostic']={'status':'infrastructure_invalid','score':None}
            else:
                result['diagnostic']=evaluate_final(ROOT,PLAN,row['run_id'],DATA,RESULTS/'diagnostics'/row['run_id'],
                                                     execute=diagnostic if row['task']=='poisson' else None)
            write_json(RESULTS/'results.json',{'plan':reference,'scientific_sessions':9,'rows':results,'status':'diagnostic_scoring'})
        build_timeline(ROOT,plan,RESULTS/'exploration-timeline.json')
        write_json(RESULTS/'results.json',{'plan':reference,'scientific_sessions':9,'rows':results,'status':'scoring_completed'})
        record('results_ready_for_report',plan_id=plan['plan_id'],scientific_sessions=9)
    except BaseException as exc:
        record('stopped',error=type(exc).__name__+': '+str(exc)[:1500])
        raise
    finally:
        if restore:subprocess.run(['docker','start',name],check=True,stdout=subprocess.DEVNULL)
        after=subprocess.check_output(['docker','inspect','--format','{{.State.Running}}',name],text=True).strip()=='true'
        service.update(restored=after==restore,after_running=after,finished_at=time.time())
        write_json(OUT/'study-service-restoration.json',service)
        assert service['restored']

if __name__=='__main__':main()
