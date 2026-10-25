"""Observed macOS/Colima timing window around the existing three-group protocol.

Acceptance thresholds are declared before measurement. The observer records CPU
time for every process (no arguments/environment), swapping and thermal status.
OS services and this benchmark's control/VM processes are recorded as overhead;
active unrelated application workloads invalidate the window.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from runner.common import file_hash, read_json, write_json
from runner.phase import RESOURCES
from runner.replay import replay_single
from runner.t3_calibrate import calibrate_t3
from runner.worker import docker

ROOT=Path(__file__).resolve().parents[1]
POLICY={'revision':3,'preflight_seconds':30,'sample_interval_seconds':2,'maximum_unrelated_process_core_percent':5,
        'maximum_swapout_pages_per_interval':0,'maximum_swapin_pages_per_interval':None,
        'swapin_policy':'Record global macOS swap-ins as diagnostic overhead, not a standalone rejection. Global counters cannot attribute reads of previously swapped pages to the VM. No calibration samples were executed under revision 1. Zero new swap-outs, no active unrelated workloads, guest swap prohibition and the original baseline stability threshold remain required.',
        'cache_policy':'Unmodified warm host/guest page cache; no cache eviction between BCCBBC samples; fresh containers and outputs. Resource probes precede a quiet settling window.'}


def cpu_seconds(value):
    parts=value.split(':')
    total=0.
    for part in parts: total=total*60+float(part)
    return total


def control_or_system(command):
    return (command.startswith(('/System/','/usr/libexec/','/usr/sbin/','/sbin/','/Library/Apple/'))
        or '/Applications/ChatGPT.app/' in command
        or Path(command).name in {'kernel_task','launchd','ps','vm_stat','sysctl','pmset','docker','colima',
          'qemu-system-aarch64','ssh','sshfs','limactl','lima-guestagent','codex','codex-cli','caffeinate'})


def snapshot():
    raw=subprocess.check_output(['ps','-axo','pid=,ppid=,time=,comm='],text=True)
    processes={}
    for line in raw.splitlines():
        parts=line.strip().split(None,3)
        if len(parts)==4:
            pid,parent,cpu,command=parts
            processes[pid]={'parent':parent,'cpu_seconds':cpu_seconds(cpu),'command':command,'control_or_system':control_or_system(command)}
    owned={str(os.getpid())}
    while True:
        descendants={pid for pid,row in processes.items() if row['parent'] in owned}
        if descendants.issubset(owned):break
        owned.update(descendants)
    for pid in owned:
        if pid in processes:processes[pid]['control_or_system']=True
    vm=subprocess.check_output(['vm_stat'],text=True)
    swap={name:int(re.search(r'^'+name+r':\s+(\d+)',vm,re.M).group(1)) for name in ('Swapins','Swapouts')}
    return {'unix':time.time(),'processes':processes,'swap':swap}


class Observer:
    def __init__(self,path):
        self.path=path;self.rows=[];self.errors=[];self.lock=threading.Lock();self.stop=threading.Event()
    def sample(self):
        with self.lock:
            if self.rows and time.time()-self.rows[-1]['unix']<POLICY['sample_interval_seconds']:
                return self.rows[-1]
            current=snapshot()
            issues=[]
            if self.rows:
                old=self.rows[-1];elapsed=current['unix']-old['unix'];active=[]
                for pid,row in current['processes'].items():
                    previous=old['processes'].get(pid)
                    used=max(0,row['cpu_seconds']-(previous['cpu_seconds'] if previous and previous['command']==row['command'] else 0))
                    percent=used/elapsed*100
                    if not row['control_or_system'] and percent>POLICY['maximum_unrelated_process_core_percent']:
                        active.append({'pid':pid,'command':row['command'],'core_percent':percent})
                delta={k:current['swap'][k]-old['swap'][k] for k in current['swap']}
                current.update(unrelated_active=active,swap_delta=delta)
                if active: issues.append('unrelated_active_process')
                swapin_limit=POLICY['maximum_swapin_pages_per_interval']
                if swapin_limit is not None and delta['Swapins']>swapin_limit:issues.append('host_swapin')
                if delta['Swapouts']>POLICY['maximum_swapout_pages_per_interval']:issues.append('host_swapout')
            current['issues']=issues
            self.rows.append(current)
            with self.path.open('a') as stream: stream.write(json.dumps(current,sort_keys=True)+'\n')
        return current
    def watch(self):
        while not self.stop.wait(POLICY['sample_interval_seconds']):
            try:self.sample()
            except Exception as exc:self.errors.append(repr(exc));return
    def violations_since(self,start):
        with self.lock:return [{'unix':r['unix'],'issues':r['issues'],'active':r.get('unrelated_active',[]),'swap':r.get('swap_delta')} for r in self.rows if r['unix']>=start and r['issues']]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resources',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'controller.py').write_bytes(Path(__file__).read_bytes())
    write_json(out/'observation-policy.json',POLICY)
    resource=read_json(args.resources)
    if resource.get('formal_resources_accepted') is not True or resource.get('resources')!=RESOURCES:raise RuntimeError('Resources have not passed')
    if docker('ps','-q').stdout.strip():raise RuntimeError('Other containers are running')
    info=json.loads(docker('info','--format','{{json .}}').stdout)
    write_json(out/'docker-before.json',{k:info[k] for k in ('NCPU','MemTotal','CgroupVersion','KernelVersion','Architecture','OperatingSystem')})
    thermal=subprocess.check_output(['pmset','-g','therm'],text=True)
    (out/'thermal-before.txt').write_text(thermal)
    observer=Observer(out/'host-observations.jsonl');observer.sample()
    thread=threading.Thread(target=observer.watch,daemon=True);thread.start()
    result={'status':'starting','formal_profile_ready':False,'model_calls':0,'final_test_scores_accessed':False}
    try:
        started=time.time();time.sleep(POLICY['preflight_seconds']);observer.sample()
        violations=observer.violations_since(started)
        if violations or observer.errors:
            result.update(status='host_preflight_rejected',violations=violations,observer_errors=observer.errors)
            return 2
        now=time.time()
        exclusive={'status':'passed','machine_exclusive_verified':True,'machine_id':resource['machine_id'],
            'other_host_workloads':[],'cache_state':POLICY['cache_policy'],'measurement_window_unix':[now,now+1800],
            'scope':'Observed quiescent macOS application workloads and dedicated Colima VM; OS/GUI/control overhead remains recorded.',
            'observer_policy':{'path':'observation-policy.json','sha256':file_hash(out/'observation-policy.json')},
            'quiet_preflight_seconds':POLICY['preflight_seconds'],'continuous_observation_required':True}
        write_json(out/'exclusive-window.json',exclusive)
        contract={'status':'frozen','resources':RESOURCES,'image_id':resource['numeric_image_id'],
            'resource_evidence':{'path':str(args.resources.resolve()),'sha256':file_hash(args.resources)},
            'exclusivity_evidence':{'path':'exclusive-window.json','sha256':file_hash(out/'exclusive-window.json')}}
        write_json(out/'timing-contract.json',contract)
        def measured(*args,**kwargs):
            start=time.time();row=replay_single(*args,**kwargs);observer.sample()
            violations=observer.violations_since(start)
            if violations or observer.errors:
                row.update(evaluation_status='evaluation_invalid',score=None,reward=None,host_window_violations=violations,observer_errors=list(observer.errors))
            return row
        calibration=calibrate_t3(ROOT,ROOT/'authoring/data/v0.3-local',out/'calibration',resource['numeric_image_id'],timing_contract=out/'timing-contract.json',execute=measured)
        time.sleep(POLICY['sample_interval_seconds']);observer.sample();violations=observer.violations_since(now)
        thermal_after=subprocess.check_output(['pmset','-g','therm'],text=True)
        (out/'thermal-after.txt').write_text(thermal_after)
        result.update(status='passed' if calibration['formal_profile_ready'] and not violations and not observer.errors else 'rejected',
            formal_profile_ready=calibration['formal_profile_ready'] and not violations and not observer.errors,
            selected_profile=calibration['profile'],violations=violations,observer_errors=observer.errors,
            completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            calibration_summary_sha256=file_hash(out/'calibration/summary.json'),
            host_observations_sha256=file_hash(observer.path))
    except BaseException as exc:
        result.update(status='failed',error=type(exc).__name__+': '+str(exc));raise
    finally:
        observer.stop.set();thread.join(timeout=10)
        result['host_observations_sha256']=file_hash(observer.path)
        write_json(out/'acceptance.json',result)
        print(json.dumps(result),flush=True)
    return 0 if result.get('formal_profile_ready') is True else 2


if __name__=='__main__':raise SystemExit(main())
