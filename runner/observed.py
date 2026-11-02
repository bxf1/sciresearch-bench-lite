"""Bounded BCCBBC attempts under continuous, independently recorded host observation."""
from pathlib import Path
import threading
import time

from tests.accepted_t3_calibration import Observer, POLICY
from .common import file_hash, read_json, write_json
from .phase import RESOURCES
from .replay import replay_single, run_t3_attempt
from .worker import docker


def observed_bccbbc(snapshot, *, resource_path, baseline_source, output_root,
                    profile=None, candidate_method=None, max_attempts=3, **config):
    """Select the first valid measurement, retaining rejected windows and all raw samples."""
    if max_attempts != 3:
        raise ValueError("optimized protocol permits at most three timing attempts")
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=False)
    resource_path = Path(resource_path).resolve(strict=True)
    resource = read_json(resource_path)
    if resource.get('formal_resources_accepted') is not True or resource.get('resources') != RESOURCES:
        raise ValueError('resource acceptance is incomplete')
    history=[]
    selected=None
    last_measured=None
    measurement_attempts=0
    # Quiet-window admission is not a measurement. Bound both independently;
    # never spend a BCCBBC retry on a window where no candidate was executed.
    for number in range(1,13):
        window=output/f'window-{number:02d}'
        window.mkdir()
        write_json(window/'observation-policy.json',POLICY)
        if docker('ps','-q').stdout.strip():
            raise ValueError('other containers are running before a timing window')
        observer=Observer(window/'host-observations.jsonl')
        observer.sample()
        thread=threading.Thread(target=observer.watch,daemon=True);thread.start()
        acceptance={'number':number,'status':'preflight','measured':False}
        value=None
        try:
            started=time.time()
            time.sleep(POLICY['preflight_seconds'])
            observer.sample()
            violations=observer.violations_since(started)
            if violations or observer.errors:
                acceptance.update(status='host_preflight_rejected',violations=violations,errors=list(observer.errors))
                continue
            window_start=time.time()
            exclusive={'status':'passed','machine_exclusive_verified':True,'machine_id':resource['machine_id'],
                       'other_host_workloads':[],'cache_state':POLICY['cache_policy'],
                       'measurement_window_unix':[window_start,window_start+1800],
                       'continuous_observation_required':True,'quiet_preflight_seconds':POLICY['preflight_seconds']}
            write_json(window/'exclusive-window.json',exclusive)
            contract={'status':'frozen','resources':RESOURCES,'image_id':resource['numeric_image_id'],
                      'resource_evidence':{'path':str(resource_path),'sha256':file_hash(resource_path)},
                      'exclusivity_evidence':{'path':'exclusive-window.json','sha256':file_hash(window/'exclusive-window.json')}}
            write_json(window/'timing-contract.json',contract)
            def measured(*args,**kwargs):
                row=replay_single(*args,**kwargs)
                observer.sample()
                violations=observer.violations_since(window_start)
                if violations or observer.errors:
                    row={**row,'evaluation_status':'evaluation_invalid','score':None,'reward':None,
                         'host_window_violations':violations,'observer_errors':list(observer.errors)}
                return row
            acceptance['measured']=True
            measurement_attempts+=1
            acceptance['measurement_attempt']=measurement_attempts
            value=run_t3_attempt(snapshot,baseline_source=baseline_source,output_root=window/'measurement',
                                 timing_contract=window/'timing-contract.json',profile=profile,
                                 candidate_method=candidate_method,execute=measured,**config)
            time.sleep(POLICY['sample_interval_seconds'])
            observer.sample()
            violations=observer.violations_since(window_start)
            if violations or observer.errors:
                value.update(evaluation_status='evaluation_invalid',performance_status='invalid_environment',
                             score=None,reward=None,speedup=None,formal_timing=False,formal_evidence_valid=False,
                             host_window_violations=violations,observer_errors=list(observer.errors))
            acceptance.update(status=value['performance_status'],violations=violations,errors=list(observer.errors))
            write_json(window/'qualified-result.json',value)
            last_measured=value
            if value['evaluation_status']=='valid' and value['performance_status'] in ('valid','candidate_failed'):
                selected=number
                break
            if value['performance_status'] not in ('baseline_unstable','invalid_environment','invalid_evaluation','diagnostic_only'):
                break  # Invalid numerical baseline is not fixed by choosing a faster repeat.
            if measurement_attempts >= max_attempts:
                break
        finally:
            observer.stop.set();thread.join(timeout=10)
            acceptance['host_observations_sha256']=file_hash(observer.path)
            write_json(window/'acceptance.json',acceptance)
            history.append(acceptance)
    if value is None:
        value=last_measured
    if value is None:
        value={'evaluation_status':'evaluation_invalid','performance_status':'invalid_environment',
               'score':None,'reward':None,'speedup':None,'samples':{'B':[],'C':[]},'formal_timing':False}
    if selected is None:
        value.update(score=None,reward=None,speedup=None)
    value.update(timing_attempts=history,selected_window=selected,selection_policy='first_valid_not_fastest',
                 max_timing_attempts=max_attempts,measurement_attempts=measurement_attempts,max_admission_windows=12)
    write_json(output/'result.json',value)
    return value
