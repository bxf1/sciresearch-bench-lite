"""Synthetic native AgentSession context handoff probe, isolated from research."""
import json
import os
import sys
from pathlib import Path
import shutil
import subprocess
import uuid
from runner import relay_transport
from runner.common import read_json,write_json

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
plan=read_json(ROOT/'freezes/research-run-plan-thinking-max-2026-10-25.json')
numeric=read_json(ROOT/plan['freezes']['heat']['path'])['image_id']
image=plan['research_images']['heat']['image_id']
out=OUT/(sys.argv[1] if len(sys.argv)>1 else 'live-context-probe');out.mkdir(exist_ok=False)
admission=relay_transport.start_relay(ROOT/'build'/('relay-continuation-probe-'+uuid.uuid4().hex[:12]),image=numeric,session_seconds=600,session_output_limit=200000,request_output_limit=4096,max_requests=3125,thinking_effort='max')
record={'status':'starting','formal':False,'scientific_data_accessed':False}
probe_name='sciresearch-context-probe-'+uuid.uuid4().hex[:12]
shutil.copy2(Path(admission['output_root'])/'startup.json',out/'relay-startup.json')
try:
 env=os.environ.copy();env['BENCH_RELAY_KEY']=admission['token']
 prefix='/home/researcher/.nvm/versions/node/v22.23.4/lib/node_modules/@earendil-works/pi-coding-agent/'
 command=['docker','run','--rm','--name',probe_name,'--network',admission['network_name'],'--cpus','1','--memory','1g','--memory-swap','1g','--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--user','1000:1000','--tmpfs','/tmp:rw,nosuid,nodev,size=67108864','--env','BENCH_RELAY_KEY',
 '--mount',f'type=bind,src={ROOT / "build/pi-policy-cache-local-001/nvm"},dst=/home/researcher/.nvm,readonly',
 '--mount',f'type=bind,src={OUT / "agent-loop.patched.js"},dst={prefix}node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js,readonly',
 '--mount',f'type=bind,src={OUT / "agent.patched.js"},dst={prefix}node_modules/@earendil-works/pi-agent-core/dist/agent.js,readonly',
 '--mount',f'type=bind,src={OUT / "native-context-probe.mjs"},dst=/probe/run.mjs,readonly',image,'/home/researcher/.nvm/versions/node/v22.23.4/bin/node','/probe/run.mjs',admission['base_url']]
 proc=subprocess.run(command,env=env,capture_output=True,text=True,timeout=420)
 for name,value in [('stdout',proc.stdout),('stderr',proc.stderr)]:
  for secret in (admission['token'],os.environ.get('ANTHROPIC_AUTH_TOKEN','')):
   if secret:value=value.replace(secret,'[REDACTED]')
  (out/(name+'.txt')).write_text(value)
 record['native']=json.loads(proc.stdout.strip().splitlines()[-1])
 record['relay_status']=relay_transport.read_status(admission)
 assert proc.returncode==0 and record['native']['status']=='passed',record['native']
 assert record['relay_status']['failed_requests']==0
 record['status']='passed'
finally:
 subprocess.run(['docker','rm','-f',probe_name],capture_output=True,text=True)
 record['cleanup']=relay_transport.cleanup_relay(admission)
 shutil.copytree(Path(admission['output_root'])/'evidence',out/'relay-evidence')
 write_json(out/'result.json',record)
assert record['cleanup']['all_removed']
print(json.dumps({'status':record['status'],'native':record['native'],'charged_output_tokens':record['relay_status']['charged_output_tokens']}))
