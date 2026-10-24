"""Authorized timing-only replay; the original 15-session barrier is closed."""
import runpy,time
from pathlib import Path
from runner.common import read_json,write_json,file_hash
from runner.worker import docker
from runner import supplemental as sup
ROOT=Path.cwd();sup.PLAN=ROOT/'freezes/supplemental-500k-2026-10-24-recovery-001.json'
plan=sup.load_plan();prior=read_json(sup.checked(plan['previous_plan']));ledger=read_json(sup.checked(plan['previous_ledger']))
latest={e['run_id']:e for e in ledger['attempts']}
for row in prior['runs']:
 e=latest[row['run_id']];state=read_json(sup.checked(e['registry']));result=read_json(sup.checked(e['result']))
 assert state['closed'] and result['status']=='research_frozen'
assert len(prior['runs'])==15 and not docker('ps','-q').stdout.strip()
api=read_json(ROOT/'logs/submission-delivery-2026-10-24/api-probe-2114.json');assert api['http_status']==402
entry=next(e for key,e in latest.items() if key.endswith('poisson-g2-r1'))
out=ROOT/'results/supplemental-2026-10-24';out.mkdir(exist_ok=True)
write_json(out/'original-g2-replay-barrier.json',{'status':'passed','original_closed_sessions':15,'original_plan':plan['previous_plan'],'original_ledger':plan['previous_ledger'],'no_running_containers':True,'model_calls':0,'scope':'Replay original closed G2 snapshots only, while supplemental model batch is stopped for HTTP 402. No new or unfinished research is scored.','timestamp':time.time()})
ns=runpy.run_path(str(ROOT/'logs/supplemental-2026-10-24/score_supplemental.py'))
ns['evaluate']('original-poisson-g2-timing-only','poisson',entry['registry'],prior['freezes']['poisson'],'timing_only')
