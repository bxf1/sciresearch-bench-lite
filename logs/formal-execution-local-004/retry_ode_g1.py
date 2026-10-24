"""One investigated retry after host suspension; preserve the cancelled attempt."""
from pathlib import Path
import json
import subprocess
import sys
from runner.common import read_json, write_json, file_hash
from runner.study import frozen_plan

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
RUN='research-6615cd7900ba0750-ode-g1-r1'
PLAN=ROOT/'freezes/research-run-plan-formal-003.json'
parent=ROOT/'research-runs'/RUN/'result.json'
r=read_json(parent)
assert r['attempt_status']=='cancelled' and r['status']=='research_invalid'
assert r['relay_cleanup']['all_removed'] and not r['bridge_errors'] and not r['cleanup_errors']
assert not subprocess.check_output(['docker','ps','-q'],text=True).strip()
plan,_=frozen_plan(ROOT,PLAN)
machine=subprocess.check_output(['colima','ssh','--','cat','/proc/sys/kernel/random/boot_id'],text=True).strip()
resource=read_json(ROOT/'logs/resource-acceptance-local-002/summary.json')
assert machine==resource['machine_id']
info=json.loads(subprocess.check_output(['docker','info','--format','{{json .}}'],text=True))
assert info['NCPU']>=6 and info['MemTotal']>=8.5*1024**3
investigation=OUT/'ode-g1-host-sleep-investigation'
write_json(investigation/'retry-acceptance.json',{'parent_attempt':RUN+'-a001','parent_result_sha256':file_hash(parent),
    'power_events_sha256':file_hash(investigation/'power-events.txt'),
    'reason':'Host entered Clamshell Sleep at 09:33:36 +0800 and fully woke at 10:03:37; research wall-clock condition was interrupted. Explicit host cancellation retained the original attempt. All owned resources cleaned; unchanged VM and frozen plan validated before one fresh linked retry.',
    'vm_boot_id':machine,'docker':{k:info[k] for k in ('NCPU','MemTotal','CgroupVersion')},
    'power':subprocess.check_output(['pmset','-g','batt'],text=True),
    'retry_limit_this_investigation':1,'hidden_scores_accessed':False})
with (OUT/'04-ode-g1-r1-a002.stdout.log').open('x') as log:
    result=subprocess.run([sys.executable,'-m','runner.study','start','--plan',str(PLAN),
        '--run-id',RUN,'--retry-of',RUN+'-a001'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
print('linked_retry_exit_code',result.returncode,flush=True)
if result.returncode:raise SystemExit(result.returncode)
with (OUT/'research-sequence-002.stdout.txt').open('x') as log:
    result=subprocess.run([sys.executable,str(OUT/'research_sequence.py')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
raise SystemExit(result.returncode)
