"""Explicit, bounded real R/W resource acceptance; no model or final-test access.

Run with PYTHONPATH=. python tests/resource_acceptance_probe.py --output <new-dir>.
Only newly created probe containers are changed. Existing services must be stopped.
"""
import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

from runner.common import file_hash, read_json, write_json
from runner.harbor_pilot import require_host_capacity
from runner.phase import RESOURCES
from runner.replay import prepare_judge, replay_single
from runner.worker import docker, run_worker
from tests.runtime_probe import PRELUDE

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3
CG = """import json,pathlib
p=pathlib.Path('/sys/fs/cgroup')
names=['cpu.max','cpu.stat','memory.max','memory.current','memory.peak','memory.swap.max','memory.swap.current','memory.events','pids.max']
print(json.dumps({n:(p/n).read_text().strip() for n in names}|{'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))
"""
ALLOCATE = """blocks=[]
for i in range(BLOCKS):
    block=bytearray(64*1024**2)
    block[::4096]=b'\\xa5'*(len(block)//4096)
    blocks.append(block)
    if (i+1)%4==0: print(json.dumps({'touched_bytes':(i+1)*64*1024**2}),flush=True)
"""
CPU = """import os,time,json
children=[]
for i in range(6):
    pid=os.fork()
    if pid==0:
        end=time.monotonic()+3
        while time.monotonic()<end: sum(range(1000))
        os._exit(0)
    children.append(pid)
for pid in children: assert os.waitpid(pid,0)[1]==0
"""


def cgroup(name):
    return json.loads(docker('exec', name, 'python', '-I', '-c', CG).stdout)


def counters(text):
    return {k:int(v) for k,v in (line.split() for line in text.splitlines())}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    (out/'controller.py').write_bytes(Path(__file__).read_bytes())
    if docker('ps','-q').stdout.strip(): raise RuntimeError('Other containers are running')
    plan=read_json(ROOT/'freezes/research-run-plan-local-draft-007.json')
    image=read_json(ROOT/'freezes/heat-local-draft-007.json')['image_id']
    capacity=require_host_capacity({'research_vcpu':4,'research_memory_bytes':4*GIB})
    inputs=ROOT/'authoring/data/pilot-smoke/inputs/heat/pilot-smoke'
    truth=ROOT/'authoring/data/pilot-smoke/private/heat/pilot-smoke'
    checks={}
    result={'status':'running','formal_resources_accepted':False,'resources':RESOURCES,
            'capacity':capacity,'numeric_image_id':image,'model_calls':0,'final_test_scores_accessed':False,
            'scope':'Offline R images at formal resource limits, actual W executor, concurrent touched memory, and W/J failure classification; no native model trial',
            'controller_sha256':file_hash(Path(__file__)),
            'worker_sha256':file_hash(ROOT/'runner/worker.py'),
            'timer_sha256':file_hash(ROOT/'runner/process_timer.py'),'checks':checks,'research_images':{}}
    write_json(out/'summary.json',result)
    source=out/'sources'
    source.mkdir()
    normal=source/'near-limit';normal.mkdir()
    (normal/'solve.py').write_text(PRELUDE+ALLOCATE.replace('BLOCKS','60')+'time.sleep(3)\nblocks.clear()\nzeros()\n')
    oom=source/'oom';oom.mkdir()
    (oom/'solve.py').write_text('import json\n'+ALLOCATE.replace('BLOCKS','80')+"raise SystemExit('memory limit was not enforced')\n")
    recovery=source/'recovery';recovery.mkdir()
    (recovery/'solve.py').write_text(PRELUDE+'zeros()\n')
    try:
        for task in ('heat','ode','poisson'):
            name='sciresearch-resource-r-'+uuid.uuid4().hex[:10]
            target=out/('r-'+task);target.mkdir()
            holder=None
            created=False
            try:
                r_image=plan['research_images'][task]['image_id']
                docker('create','--name',name,'--label','sciresearch.project=benchmark-v0.3',
                       '--cpus','4','--memory','4g','--memory-swap','4g','--pids-limit','128',
                       '--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
                       '--user','1000:1000',r_image,'sleep','240')
                created=True;docker('start',name)
                info=json.loads(docker('inspect',name).stdout)[0]
                write_json(target/'container.json',{k:info[k] for k in ('Id','Image','HostConfig','Mounts')})
                before=cgroup(name);write_json(target/'cgroup-before.json',before)
                result['machine_id']=before['boot_id']
                checks[task+'_r_limits']=(before['cpu.max']=='400000 100000' and before['memory.max']==str(4*GIB)
                    and before['memory.swap.max']=='0' and before['pids.max']=='128' and not info['Mounts'])
                docker('exec',name,'python','-I','-c',CPU,timeout=15)
                cpu_after=cgroup(name);write_json(target/'cgroup-after-cpu.json',cpu_after)
                cpu_delta=counters(cpu_after['cpu.stat'])['usage_usec']-counters(before['cpu.stat'])['usage_usec']
                checks[task+'_r_cpu_workload']=cpu_delta>1_000_000 and counters(cpu_after['cpu.stat'])['nr_throttled']>counters(before['cpu.stat'])['nr_throttled']
                result['research_images'][task]={'image_id':r_image,'container_id':info['Id'],'cpu_usage_usec':cpu_delta}
                if task=='heat':
                    program='import json,time\nfrom pathlib import Path\n'+ALLOCATE.replace('BLOCKS','60')+"print('MEMORY_READY',flush=True)\nend=time.monotonic()+150\nwhile not Path('/tmp/release').exists() and time.monotonic()<end: time.sleep(.1)\n"
                    with (target/'memory-holder.stdout').open('w') as stdout,(target/'memory-holder.stderr').open('w') as stderr:
                        holder=subprocess.Popen(['docker','exec',name,'python','-I','-c',program],stdout=stdout,stderr=stderr)
                        deadline=time.monotonic()+60
                        while 'MEMORY_READY' not in (target/'memory-holder.stdout').read_text():
                            if holder.poll() is not None or time.monotonic()>deadline: raise RuntimeError('R memory holder failed to become ready')
                            time.sleep(.2)
                        ready=cgroup(name);write_json(target/'cgroup-memory-held.json',ready)
                        checks['r_375gib_physically_touched']=int(ready['memory.current'])>=int(3.75*GIB)
                        worker=run_worker('heat',normal,inputs,out/'concurrent-w',image)
                        after=cgroup(name);write_json(target/'cgroup-after-concurrent-w.json',after)
                        checks['concurrent_r_w_near_limit']=(worker['attempt_status']=='completed' and worker['artifact_valid']
                            and worker.get('memory_peak_bytes',0)>=3.75*GIB and int(after['memory.current'])>=3.75*GIB
                            and holder.poll() is None and after['memory.swap.current']=='0')
                        checks['w_limits_and_cleanup']=worker.get('resource_limits_verified') is True and worker.get('all_processes_terminated') is True
                        docker('exec',name,'touch','/tmp/release');holder.wait(timeout=10)
                        checks['r_holder_clean_exit']=holder.returncode==0
            finally:
                if created: docker('rm','-f',name,check=False)
                if holder is not None:
                    try: holder.wait(timeout=5)
                    except subprocess.TimeoutExpired: holder.kill();holder.wait()
            write_json(out/'summary.json',result)
        judge=prepare_judge(ROOT,out/'judge-source')
        failure=replay_single(oom,task='heat',input_root=inputs,truth_root=truth,output_root=out/'oom-replay',image=image,judge_source_root=judge)
        worker=failure['worker']
        checks['oom_classified_as_valid_scientific_zero']=(failure['attempt_status']=='oom' and failure['evaluation_status']=='valid'
            and failure['score']==0 and failure['reward']==0 and worker.get('oom_killed') is True and not worker['artifact_valid'])
        after_path=out/'oom-replay/worker/cgroup_after.json'
        after=read_json(after_path) if after_path.exists() else {}
        checks['real_4gib_cgroup_oom']=(int(after.get('memory.peak','0'))>=.99*4*GIB
            and counters(after.get('memory.events','oom_kill 0'))['oom_kill']>=1 and after.get('memory.swap.max','').strip()=='0')
        checks['oom_cleanup']=worker.get('all_processes_terminated') is True
        recovered=run_worker('heat',recovery,inputs,out/'recovery-w',image)
        checks['fresh_worker_after_oom']=recovered['attempt_status']=='completed' and recovered['artifact_valid'] and recovered.get('all_processes_terminated') is True
        checks['no_remaining_containers']=not docker('ps','-q').stdout.strip()
        result.update(status='passed' if all(checks.values()) else 'failed',formal_resources_accepted=all(checks.values()))
    except BaseException as exc:
        result.update(status='failed',error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        write_json(out/'summary.json',result)
        print(json.dumps({'status':result['status'],'checks':checks}),flush=True)
    if not all(checks.values()): raise SystemExit(1)


if __name__=='__main__': main()
