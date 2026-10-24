"""Seal a local checkpoint while Messages API is unavailable."""
import base64
import json
import os
from pathlib import Path
import runpy
import subprocess
from runner.common import file_hash, read_json, write_json

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
assert not subprocess.check_output(['docker','ps','-q'],text=True).strip()
helpers=runpy.run_path(str(ROOT/'logs/formal-freeze-local-003/archive.py'))
key=os.environ.get('ANTHROPIC_AUTH_TOKEN','');assert key
needles={key.encode(),base64.b64encode(key.encode()),json.dumps(key)[1:-1].encode()}
for p in (ROOT/'build').glob('*/admission.json'):
    token=read_json(p).get('token')
    if token:needles.add(token.encode())
plan=read_json(ROOT/'freezes/research-run-plan-formal-003.json')
ledger=ROOT/'research-runs'/plan['plan_id']/'manifest.json'
assert len(read_json(ledger)['attempts'])==5
paths=helpers['collect']([OUT,ROOT/'results/formal-study-progress-003',*(ROOT/'research-runs').glob(plan['plan_id']+'*')])
paths|={ROOT/n for n in ('freezes/research-run-plan-formal-003.json','docs/execution-status-2026-10-23.md',
                        'docs/budget-freeze-2026-10-23.md','docs/submission-diagnosis-2026-10-23.md')}
ref,files=helpers['archive'](ROOT/'logs/formal-execution-delivery-local-004',paths,needles)
frozen=ROOT/'logs/formal-freeze-delivery-local-003/evidence.tar.gz'
write_json(ROOT/'logs/formal-execution-delivery-local-004/checkpoint.json',{'status':'checkpoint_saved',
    'archive':ref,'files':len(files),'manifest_sha256':file_hash(ledger),'valid_research_sessions':3,
    'attempts':5,'hidden_scores_accessed':False,'all_owned_resources_removed':True,
    'freeze_archive':{'path':frozen.relative_to(ROOT).as_posix(),'sha256':file_hash(frozen)},
    'reason':'Messages API HTTP 402 requires account/billing resolution before linked retry.',
    'next_retry_of':'research-6615cd7900ba0750-ode-g1-r1-a002'})
print(json.dumps({'status':'checkpoint_saved','archive':ref,'files':len(files)}))
