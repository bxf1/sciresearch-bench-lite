"""Recertify the unchanged Poisson 1.5x gate on the fresh author calibration set."""
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runner.common import read_json,write_json,file_hash
from runner.observed import observed_bccbbc
from runner.performance import calibrate_profile
from runner.replay import prepare_judge

OUT=ROOT/'logs/optimized-r1-20261101'
DATA=ROOT/'authoring/data/optimized-r1-20261101'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--resume-admission',action='store_true')
    args=parser.parse_args()
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(143))
    name='dcomp-demo-postgres'
    running=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
    assert set(running).issubset({name})
    restore=name in running
    service={'before_running':restore,'restored':False,'started_at':time.time()}
    write_json(OUT/'timing-calibration-service-restoration.json',service)
    resource=OUT/'resource-acceptance/summary.json'
    image=read_json(resource)['numeric_image_id']
    target=OUT/'timing-calibration';target.mkdir(exist_ok=args.resume_admission)
    judge=prepare_judge(ROOT,target/'judge-source')
    source=ROOT/'baselines/poisson'
    groups=[];results=[]
    if args.resume_admission:
        previous=read_json(target/'progress.json')
        assert len(previous['group_results'])==2
        assert previous['group_results'][0]['selected_window'] is not None
        assert all(not item['measured'] for item in previous['group_results'][1]['timing_attempts'])
        write_json(target/'progress-before-admission-recovery.json',previous)
        results=previous['group_results'][:1]
        groups=[[results[0]['protocol_attempt']]]
        write_json(target/'admission-policy-revision.json',{'status':'pre_research_protocol_revision',
            'reason':'Prior three rejected admissions executed zero BCCBBC samples. Count actual measurement attempts separately from quiet-window admission.',
            'measurement_attempt_limit':3,'admission_window_limit':12,'observation_thresholds_unchanged':True,
            'retained_first_valid_group':1,'previous_progress_sha256':file_hash(target/'progress-before-admission-recovery.json')})
    try:
        if restore:subprocess.run(['docker','stop',name],check=True,stdout=subprocess.DEVNULL)
        for index in range(len(results),3):
            print('Calibration group',index+1,'started',flush=True)
            group_name=f'group-{index+1}'+('-admission-recovery' if args.resume_admission else '')
            result=observed_bccbbc(source,resource_path=resource,baseline_source=source,output_root=target/group_name,
                candidate_method='lu',task='poisson',input_root=DATA/'inputs/poisson/author-calibration',
                truth_root=DATA/'private/poisson/author-calibration',image=image,judge_source_root=judge)
            results.append(result)
            write_json(target/'progress.json',{'group_results':results})
            assert result['selected_window'] is not None,'No valid timing window; retain all evidence and stop before research'
            groups.append([result['protocol_attempt']])
        summary=calibrate_profile(groups)
        summary.update(group_results=results,model_calls=0,final_test_scores_accessed=False,
                       selection_policy='First valid of at most three windows for each calibration group; all rejected windows retained.')
        write_json(target/'summary.json',summary)
        assert summary['formal_profile_ready'] and summary['profile']=='efficiency_gate_1.5','Original efficiency gate could not be recertified'
        print(json.dumps({'status':'passed','profile':summary['profile'],'speedups':[r['speedup'] for r in results]}),flush=True)
    finally:
        if restore:subprocess.run(['docker','start',name],check=True,stdout=subprocess.DEVNULL)
        after=subprocess.check_output(['docker','inspect','--format','{{.State.Running}}',name],text=True).strip()=='true'
        service.update(restored=after==restore,after_running=after,finished_at=time.time())
        write_json(OUT/'timing-calibration-service-restoration.json',service)
        assert service['restored']

if __name__=='__main__':main()
