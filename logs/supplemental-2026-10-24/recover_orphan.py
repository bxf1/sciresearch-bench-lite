"""Preserve an externally interrupted attempt; authorize a linked fresh attempt."""
import copy,json,os,subprocess,time,uuid
from pathlib import Path
from runner.common import read_json,write_json,file_hash
from runner.registry import Registry
from runner import supplemental as sup, relay_transport as transport
from runner.harbor_pilot import retain_safe_records
root=Path.cwd(); out=root/'logs/supplemental-2026-10-24'
old=sup.load_plan(); run=old['runs'][0]; assert run['settings']['task']=='poisson'
r=root/'research-runs'/run['settings']['run_id']; result=read_json(r/'result.json')
assert result['status']=='starting'
processes=subprocess.check_output(['ps','-axo','pid,comm,args'],text=True)
assert not any('runner.supplemental run' in line and 'python' in line.lower() for line in processes.splitlines())
(r/'interrupted-starting-result.json').write_bytes((r/'result.json').read_bytes())
admission=transport.load_admission(result['relay']['admission_path'])
project=run['settings']['attempt_id']+'__env'
containers=transport.docker('ps','-aq','--filter','label=com.docker.compose.project='+project).stdout.split()
infos=json.loads(transport.docker('inspect',*containers).stdout)
main=next(i for i in infos if i['Config']['Labels']['com.docker.compose.service']=='main')
transport.docker('stop','-t','5',main['Id'],timeout=30)
# Native logs are retained privately, then session-token redaction is applied.
native=next((r/'harbor').iterdir())
for source,name in [('/logs/agent','interrupted-agent'),('/workspace','interrupted-workspace')]:
 dest=r/name;dest.mkdir(exist_ok=False)
 transport.docker('cp',main['Id']+':'+source+'/.',str(dest),check=False,timeout=60)
for c in containers: transport.docker('rm','-f',c)
networks=transport.docker('network','ls','-q','--filter','label=com.docker.compose.project='+project).stdout.split()
for n in networks: transport.docker('network','rm',n)
for _ in range(140):
 status=transport.read_status(admission)
 if not status.get('inflight'): break
 time.sleep(1)
cleanup=transport.cleanup_relay(admission)
assert cleanup['all_removed'] and not cleanup['errors']
retain_safe_records(r,native,admission)
for folder in (r/'interrupted-agent',r/'interrupted-workspace'):
 for p in folder.rglob('*'):
  if p.is_file() and not p.is_symlink():
   b=p.read_bytes(); n=b.replace(admission['token'].encode(),b'[RELAY_SESSION_TOKEN_REDACTED]')
   if n!=b:p.write_bytes(n)
evidence={'reason':'Host Codex exec/controller terminated during connection failure; research container survived without host bridge. Infrastructure-invalid, not scientific failure.','recorded_at':time.time(),'relay_status':status,'relay_cleanup':cleanup,'containers_removed':containers,'networks_removed':networks,'model_requests_observed':True}
write_json(r/'interruption-evidence.json',evidence)
state=Registry(r/'registry').close(attempt_status='infrastructure_failed',reason=evidence['reason'],evidence_sha256=file_hash(r/'interruption-evidence.json'))
result.update(status='research_invalid',attempt_status='infrastructure_failed',error=evidence['reason'],finished_at=time.time(),model_run_started=True,registry=state,relay_status=status,relay_cleanup=cleanup,evaluation_status='not_run',score=None,reward=None)
write_json(r/'result.json',result)
ledger=root/'research-runs'/old['plan_id']/'manifest.json'; m=read_json(ledger)
m['attempts'][0].update(status='research_invalid',attempt_status='infrastructure_failed',result=sup.reference(r/'result.json'),registry=sup.reference(r/'registry/state.json'))
write_json(ledger,m)
new=copy.deepcopy(old);new['plan_id']=old['plan_id']+'-recovery-001'
new['parent_supplemental_plan']=sup.reference(sup.PLAN)
new['recovery_evidence']=sup.reference(r/'interruption-evidence.json')
new['created_at']=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
s=new['runs'][0]['settings'];s['parent_attempt']=s['attempt_id'];s['run_id']+='-retry-001';s['attempt_id']=s['run_id']+'-a002';s['session_id']=str(uuid.uuid4())
p=root/'freezes'/('supplemental-500k-2026-10-24-recovery-001.json');assert not p.exists();write_json(p,new)
print(json.dumps({'orphan_closed':result['status'],'new_plan':str(p),'known_usage':status.get('charged_output_tokens'),'clean':not transport.docker('ps','-q').stdout.strip()}))
