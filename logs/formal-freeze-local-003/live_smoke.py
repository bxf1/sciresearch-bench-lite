"""Authorized budget revision acceptance; synthetic summaries only."""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from unittest.mock import patch
from runner import harbor_pilot, relay_transport
from runner.common import file_hash, read_json, write_json

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = read_json(ROOT / 'freezes/research-run-plan-formal-002.json')
POLICY = read_json(ROOT / 'logs/model-policy-capture-compaction-local-003/heat/policy.json')
NUMERIC = read_json(ROOT / OLD['freezes']['heat']['path'])['image_id']
RIMAGE = OLD['research_images']['heat']['image_id']
KW = dict(expected_system_sha256=POLICY['wire_system_sha256'], expected_tools_sha256=POLICY['wire_tools_sha256'],
          expected_compaction_system_sha256=POLICY['native_compaction']['wire_system_sha256'])

def summary_smoke():
    out = OUT / 'native-live-summary'
    out.mkdir(exist_ok=False)
    script = (ROOT / 'logs/formal-execution-local-002/native_summary.mjs').read_text()
    script = script.replace("const token = 'offline-relay-session-token-not-a-credential';", "const token = process.env.BENCH_RELAY_KEY;")
    script = script.replace('Synthetic offline conversation for summarizer wiring only.', 'Synthetic acceptance conversation: user asks for a one-word acknowledgment; assistant says OK. No scientific data.')
    (out / 'native_summary.mjs').write_text(script)
    identity = 'sciresearch-compaction-smoke-' + uuid.uuid4().hex[:12]
    admission = relay_transport.start_relay(ROOT / 'build' / identity, image=NUMERIC, session_seconds=600, session_output_limit=200000, max_requests=3125, **KW)
    record = {'formal': False, 'scope': 'real native Pi summarizer and provider using synthetic conversation only', 'cases': []}
    try:
        for mode in ('initial', 'update'):
            env = os.environ.copy()
            env['BENCH_RELAY_KEY'] = admission['token']
            command = ['docker','run','--rm','--name',identity+'-'+mode,'--network',admission['network_name'],
                '--cpus','1','--memory','1g','--memory-swap','1g','--pids-limit','128','--cap-drop','ALL',
                '--security-opt','no-new-privileges','--read-only','--user','1000:1000',
                '--tmpfs','/tmp:rw,nosuid,nodev,size=33554432','--env','BENCH_RELAY_KEY',
                '--mount',f'type=bind,src={ROOT / "build/pi-policy-cache-local-001/nvm"},dst=/home/researcher/.nvm,readonly',
                '--mount',f'type=bind,src={out / "native_summary.mjs"},dst=/probe/native_summary.mjs,readonly',
                RIMAGE,'/home/researcher/.nvm/versions/node/v22.23.4/bin/node','/probe/native_summary.mjs',admission['base_url'],mode]
            proc = subprocess.run(command,env=env,capture_output=True,text=True,timeout=180)
            (out/(mode+'.stdout.txt')).write_text(proc.stdout.replace(admission['token'],'[REDACTED]'))
            (out/(mode+'.stderr.txt')).write_text(proc.stderr.replace(admission['token'],'[REDACTED]'))
            result = json.loads(proc.stdout.strip().splitlines()[-1])
            assert proc.returncode == 0 and result['status']=='success' and result['text']
            record['cases'].append({'mode':mode,'status':'passed','usage':result['usage']})
        status = relay_transport.read_status(admission)
        assert status['successful_requests']==2 and status['failed_requests']==0 and not status['protocol_violation']
        record['relay_status']=status
        record['status']='passed'
    finally:
        record['cleanup']=relay_transport.cleanup_relay(admission)
        shutil.copytree(Path(admission['output_root'])/'evidence',out/'relay-evidence')
        write_json(out/'result.json',record)
    assert record['cleanup']['all_removed']
    return record

def main():
    result = summary_smoke()
    assert result['relay_status']['limits']['session_output_limit'] == 200000
    assert result['relay_status']['limits']['request_output_limit'] == 4096
    assert result['relay_status']['limits']['max_requests'] == 3125
    write_json(OUT/'live-smoke-result.json', {'status':'passed','formal':False,
        'summary_result':'native-live-summary/result.json',
        'scope':'Fresh relay startup at 200000 cumulative output / 3125 requests plus native initial/update summaries. Prior full Harbor pilot remains version 002 evidence; no final-test data.'})

if __name__ == '__main__': main()
