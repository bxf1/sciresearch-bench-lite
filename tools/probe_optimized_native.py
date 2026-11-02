"""Offline native regression and a bounded live context-recovery check, no task data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runner import relay_transport
from runner.common import read_json,write_json,file_hash
OUT=ROOT/'logs/optimized-r1-20261101'
BASE='/home/researcher/.nvm/versions/node/v22.23.4/lib/node_modules/@earendil-works/pi-coding-agent/'
NODE='/home/researcher/.nvm/versions/node/v22.23.4/bin/node'


def command(image,name,network):
    args=['docker','run','--rm','--name',name,'--network',network,'--cpus','1','--memory','1g','--memory-swap','1g',
          '--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--user','1000:1000',
          '--tmpfs','/tmp:rw,nosuid,nodev,size=67108864']
    mounts=[(ROOT/'build/pi-policy-cache-local-001/nvm','/home/researcher/.nvm'),
            (OUT,'/probe'),(OUT/'agent-loop.patched.js',BASE+'node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js'),
            (OUT/'agent.patched.js',BASE+'node_modules/@earendil-works/pi-agent-core/dist/agent.js')]
    for src,dst in mounts:args += ['--mount',f'type=bind,src={src},dst={dst},readonly']
    return args


def main():
    image=read_json(OUT/'research-images.json')['research_images']['heat']['image_id']
    numeric=read_json(OUT/'resource-acceptance/summary.json')['numeric_image_id']
    offline=[]
    for script in ('native-loop-test.mjs','native-session-test.mjs'):
        name='sciresearch-native-test-'+uuid.uuid4().hex[:12]
        proc=subprocess.run(command(image,name,'none')+[image,NODE,'/probe/'+script],capture_output=True,text=True,timeout=120)
        (OUT/(script+'.stdout')).write_text(proc.stdout)
        (OUT/(script+'.stderr')).write_text(proc.stderr)
        assert proc.returncode==0,(script,proc.stderr[-500:])
        offline.append({'script':script,'sha256':file_hash(OUT/script),'exit_code':proc.returncode,'result':json.loads(proc.stdout.strip().splitlines()[-1])})
    write_json(OUT/'native-offline-tests.json',{'status':'passed','tests':offline,'model_calls':0})
    output=OUT/'live-context-probe';output.mkdir(exist_ok=False)
    admission=relay_transport.start_relay(ROOT/'build'/('relay-optimized-probe-'+uuid.uuid4().hex[:12]),image=numeric,
             session_seconds=600,session_output_limit=200000,request_output_limit=16384,max_requests=32,thinking_effort='max')
    name='sciresearch-native-live-'+uuid.uuid4().hex[:12]
    record={'status':'starting','scientific_data_accessed':False}
    try:
        env={**os.environ,'BENCH_RELAY_KEY':admission['token']}
        proc=subprocess.run(command(image,name,admission['network_name'])+['--env','BENCH_RELAY_KEY',image,NODE,
                            '/probe/native-context-probe.mjs',admission['base_url']],env=env,capture_output=True,text=True,timeout=420)
        for label,text in [('stdout',proc.stdout),('stderr',proc.stderr)]:
            for secret in (admission['token'],os.environ.get('ANTHROPIC_AUTH_TOKEN','')):
                if secret:text=text.replace(secret,'[REDACTED]')
            (output/(label+'.txt')).write_text(text)
        record['native']=json.loads(proc.stdout.strip().splitlines()[-1])
        record['relay_status']=relay_transport.read_status(admission)
        assert proc.returncode==0 and record['native']['status']=='passed'
        assert record['relay_status']['failed_requests']==0
        record['status']='passed'
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True)
        record['cleanup']=relay_transport.cleanup_relay(admission)
        shutil.copytree(Path(admission['output_root'])/'evidence',output/'relay-evidence')
        write_json(output/'result.json',record)
    assert record['cleanup']['all_removed']
    print(json.dumps({'status':record['status'],'live_calls':record['native']['real_calls']}))


if __name__=='__main__':main()
