"""Real non-root R -> file bridge -> immutable snapshot -> W functional probe.

No model calls, GT access, host mounts, or final-test inputs are used. All
containers created by this probe are uniquely named and removed on exit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .common import canonical, digest, file_hash, read_json, tree_hashes, write_json
from .file_bridge import FileBridge
from .phase import validate_manifest
from .registry import Registry


SOURCE = '''import argparse,json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser()
p.add_argument('--input');p.add_argument('--output');p.add_argument('--seed')
a=p.parse_args()
for c in json.loads((Path(a.input)/'manifest.json').read_text())['cases']:
    out=Path(a.output)/'cases'/c['id']
    out.mkdir(parents=True)
    np.save(out/'u0.npy',np.zeros(256,dtype='<f8'),allow_pickle=False)
'''


def command(*argv, data=None, check=True, timeout=150):
    result = subprocess.run([str(a) for a in argv], input=data, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"{argv[:2]}: {result.stderr[-2000:]}")
    return result


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output/'controller.py').write_bytes(Path(__file__).read_bytes())
    manifest = validate_manifest('heat', args.input, expected_split='public-dev')
    name = 'bench-file-bridge-probe-' + uuid.uuid4().hex[:12]
    result = {'formal': False, 'model_calls': 0, 'status': 'starting', 'started_at': time.time(),
              'controller_sha256': file_hash(Path(__file__)), 'public_input_hashes': tree_hashes(args.input),
              'probes': [], 'research_container': name}
    created = False
    stop = threading.Event()
    thread = None
    errors = []
    registry = None

    def probe(name, passed, **details):
        result['probes'].append({'name': name, 'passed': bool(passed), **details})
        write_json(output/'result.json', result)
        if not passed:
            raise AssertionError(name)

    try:
        numeric_image = json.loads(command('docker','image','inspect',args.numeric_image).stdout)[0]['Id']
        research_image = json.loads(command('docker','image','inspect',args.research_image).stdout)[0]['Id']
        result.update(numeric_image_id=numeric_image, research_image_id=research_image)
        command('docker','create','--name',name,'--label','sciresearch.project=benchmark-v0.3',
                '--network','none','--cpus','1','--memory','1g','--memory-swap','1g',
                '--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges',research_image)
        created = True
        command('docker','start',name)
        info = json.loads(command('docker','inspect',name).stdout)[0]
        write_json(output/'research-container.json', {k:info[k] for k in ('Id','Image','Config','HostConfig','Mounts')})
        security_code = "import json,os,pathlib;print(json.dumps({'uid':os.getuid(),'status':pathlib.Path('/proc/self/status').read_text(),'socket':pathlib.Path('/var/run/docker.sock').exists()}))"
        security = json.loads(command('docker','exec',name,'python','-c',security_code).stdout)
        probe('nonroot_no_host_mounts_no_socket', security['uid']==1000 and not info['Mounts'] and not security['socket'])
        # Ensure the image's dev bytes exactly match the host-selected public batch.
        hashing = "import hashlib,json,pathlib; r=pathlib.Path('/input');print(json.dumps({p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file()}))"
        embedded = json.loads(command('docker','exec',name,'python','-c',hashing).stdout)
        probe('exact_public_input_match', embedded==tree_hashes(args.input), cases=len(manifest['cases']))
        protection = '''import json,pathlib
checks={}
for name,path in [('helper','/opt/bench/file_bench.py'),('response','/workspace/.bench/responses/forged.json')]:
    try:
        pathlib.Path(path).write_text('forged')
        checks[name]=False
    except PermissionError: checks[name]=True
try:
    pathlib.Path('/workspace/.bench').rename('/workspace/stolen-bench')
    checks['protocol_rename']=False
except PermissionError: checks['protocol_rename']=True
print(json.dumps(checks))
'''
        denied = json.loads(command('docker','exec',name,'python','-c',protection).stdout)
        probe('researcher_cannot_replace_helpers_or_feedback', all(denied.values()), checks=denied)
        workspace = output/'imports'
        workspace.mkdir()
        registry = Registry.create(output/'registry',workspace,'heat','file-bridge-functional-probe',budget_seconds=240,max_evaluations=3)
        bridge = FileBridge(name,registry,args.input,numeric_image,output/'file-bridge')
        def serve():
            try: bridge.serve(stop,interval=.2)
            except BaseException as exc: errors.append(f'{type(exc).__name__}: {exc}')
        thread = threading.Thread(target=serve,daemon=True)
        thread.start()
        def bench(*args):
            r=command('docker','exec',name,'bench',*args,check=False)
            row=json.loads(r.stdout)
            write_json(output/('client-'+str(len(result['probes']))+'.json'),row)
            return row
        invalid=bench('evaluate','../etc')
        probe('escaping_source_rejected_and_charged', invalid.get('candidate_id')=='candidate-001' and not invalid['feedback']['artifact_valid'])
        install="import pathlib,sys; p=pathlib.Path('/workspace/candidate');p.mkdir(exist_ok=True);(p/'solve.py').write_text(sys.stdin.read())"
        command('docker','exec','-i',name,'python','-c',install,data=SOURCE)
        valid=bench('evaluate','candidate')
        feedback=valid.get('feedback',{})
        probe('registered_source_executes_in_independent_worker', valid.get('candidate_id')=='candidate-002' and feedback.get('artifact_valid') and len(feedback.get('cases',[]))==6)
        serialized=canonical(feedback).decode()
        probe('public_feedback_has_no_hidden_metrics', not any(k in serialized for k in ('E_init','E_forward','u0_true','future_true','truth_root','reward')))
        snapshot=registry.verified_snapshot('candidate-002')
        recorded=tree_hashes(snapshot)
        command('docker','exec','-i',name,'python','-c',install,data="raise SystemExit('changed after evaluate')\n")
        probe('r_mutation_cannot_change_registered_source',tree_hashes(registry.verified_snapshot('candidate-002'))==recorded and (snapshot/'solve.py').read_text()==SOURCE)
        finalized=bench('finalize','candidate-002')
        probe('finalize_selects_registered_snapshot',finalized.get('finalized')=='candidate-002')
        stop.set()
        thread.join(timeout=20)
        if thread.is_alive() or errors:
            raise RuntimeError(f'bridge did not stop cleanly: {errors}')
        state=registry.close()
        probe('first_and_final_preserved',state['first_id']==state['final_id']=='candidate-002' and len(state['evaluations'])==2)
        result.update(status='functional_probe_passed',source_hash=valid['source_hash'],first_id=state['first_id'],final_id=state['final_id'])
    except Exception as exc:
        result.update(status='functional_probe_failed',error=f'{type(exc).__name__}: {exc}')
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=10)
            result['bridge_thread_stopped']=not thread.is_alive()
        if registry is not None and (thread is None or not thread.is_alive()):
            registry.close()
        if created:
            cleanup=command('docker','rm','-f',name,check=False,timeout=30)
            result['research_container_removed']=cleanup.returncode==0
        result['bridge_errors']=errors
        result['finished_at']=time.time()
        write_json(output/'result.json',result)
    print(json.dumps({k:result.get(k) for k in ('status','error','source_hash','research_container_removed')}))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--research-image',default='sciresearch-heat-r:0.3.1')
    p.add_argument('--numeric-image',default='sciresearch-numeric:0.3.0')
    args=p.parse_args()
    if run(args)['status']!='functional_probe_passed':
        raise SystemExit(1)
