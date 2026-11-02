"""Read-only independent audit of the uniform nine-r1 comparison and historical preservation."""
import hashlib,json,math,re,statistics
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads((ROOT/p).read_text())
def sha(p):return hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
def audit():
 data=read('results/unified-r1-nine-2026-10-29/reviewed-results.json')
 for p,h in data['source_sha256'].items():assert sha(p)==h,p
 assert len(data['rows'])==9
 assert [(r['task'],r['group']) for r in data['rows']]==[(t,g) for t in ('heat','ode','poisson') for g in ('g1','g2','g3')]
 assert data['latest_research_finished_at']<data['first_hidden_replay_started_at']
 report=(ROOT/'docs/submission-report-2026-10-24.md').read_text()
 records=0
 for r in data['rows']:
  host=read(r['host_evidence']['path']);reg=read(r['registry_evidence']['path']);raw=read(r['score_evidence']['path'])['diagnostics']
  assert host['native_setup_evidence']['installed_source_sha256']==data['uniform_installed_sources']
  assert {k:v for k,v in host['trusted_source_sha256'].items() if not k.startswith('prompts/')}==data['uniform_trusted_sources']
  assert host['relay_status']['limits']['request_output_limit']==16384 and host['relay_status']['limits']['session_output_limit']==200000
  assert raw['final']['score']==r['final_score'] and raw['first']['score']==r['first_score']
  original=r['original_score_evidence'];assert sha(original['path'])==original['sha256']
  if original!=r['score_evidence']:
   value=read(r['score_evidence']['path'])
   assert read(original['path'])['diagnostics']['evaluation_status']=='invalid'
   assert value['parent_replay']==original and value['independent_research_sample'] is False
   assert value['registry_sha256']==r['registry_evidence']['sha256']
  old=read(r['old_score_evidence']['path'])['diagnostics']['final']['score'];assert old==r['old_final_score']
  assert math.isclose(r['score_delta'],r['final_score']-old,abs_tol=1e-10)
  assert f"| {r['label']} | {old:.3f} | {r['final_score']:.3f} | {r['score_delta']:+.3f} |" in report
  events=[json.loads(l) for l in (ROOT/r['relay_evidence']['path']).read_text().splitlines()]
  ends=[e for e in events if e['event']=='request_finished'];requests=[e for e in events if e['event']=='request_accepted']
  assert sum(e.get('output_tokens') or 0 for e in ends)==r['output_tokens']
  assert sum(e.get('charged_output_tokens') or 0 for e in ends)==r['charged_output_tokens']
  assert sum(e['outcome']!='success' for e in ends)==r['failed_requests']
  assert dict(Counter(e['outcome'] for e in ends))==r['request_outcomes']
  assert sum(e['effective_max_tokens']==1 for e in requests)==r['one_token_requests']
  assert sum(e.get('request_kind')=='native_compaction' for e in requests)==r['compaction_requests']
  assert len(r['compaction_attempts'])==r['compaction_requests']
  for item in r['compaction_attempts']:
   i=item['request_number']-1;request=requests[i];end=next(e for e in ends if e['request_id']==request['request_id']);following=requests[i+1] if i+1<len(requests) else {}
   assert request['request_kind']=='native_compaction' and item['effective_max_tokens']==request['effective_max_tokens']
   assert item['outcome']==end['outcome'] and item['output_tokens']==end.get('output_tokens')
   assert item['wall_seconds']==end['timestamp']-request['timestamp']
   assert item['following_request_kind']==following.get('request_kind') and item['following_request_limit']==following.get('effective_max_tokens')
  assert len(reg['evaluations'])==r['public_evaluations']
  for role in ('first','final'):
   cp=raw[role]
   if cp.get('source_hash'):
    source=Path(r['registry_evidence']['path']).parent/'snapshots'/cp['checkpoint_id']
    hashes={p.relative_to(ROOT/source).as_posix():sha(p) for p in sorted((ROOT/source).rglob('*')) if p.is_file()}
    assert hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()==cp['source_hash']
   for rep in cp.get('repeats',[]):
    batches=rep['samples']['C'] if r['task']=='poisson' else [rep]
    for batch in batches:
     assert batch['total']==len(batch['cases'])==12
     for c in batch['cases']:
      records+=1;clip=lambda x:max(0,min(1,x))
      if c.get('artifact_valid') is False:
       assert c['scientific_pass'] is False and c['score']==0;continue
      if r['task']=='heat':
       expected=100*(.8*clip(1-c['E_init']/.30)+.2*clip(1-c['E_forward']/.06));passed=c['E_init']<=.15 and c['E_forward']<=.03
      elif r['task']=='ode':
       valid=c.get('K') is not None and c['K']<=10 and c.get('E_roll') is not None and c.get('E_field') is not None
       expected=100*(.5*clip(1-c['E_roll']/.10)+.5*clip(1-c['E_field']/.10)) if valid else 0;passed=valid and c['E_roll']<=.05 and c['E_field']<=.05
      else:
       assert c['scientific_pass']==(c['max_relative_residual']<=1e-8 and c['max_solution_error']<=1e-5);continue
      assert math.isclose(expected,c['score'],abs_tol=1e-9) and c['scientific_pass']==passed
     assert batch['passed']==sum(c['scientific_pass'] for c in batch['cases'])
     if r['task']!='poisson':assert math.isclose(batch['score'],statistics.mean(c['score'] for c in batch['cases']),abs_tol=1e-9)
    if r['task']=='poisson':
     if rep['performance_status']=='candidate_failed':
      assert rep['score']==0 and rep['reward']==0 and rep['speedup'] is None
      assert any(x.get('scientific_pass') is False or x.get('artifact_valid') is False or x.get('worker',{}).get('resource_qualified') is False for x in rep['samples']['C'])
     else:
      bt=[x['worker']['execution_wall_seconds'] for x in rep['samples']['B']]
      ratio=statistics.median(bt)/statistics.median(x['worker']['execution_wall_seconds'] for x in rep['samples']['C'])
      assert max(bt)/min(bt)<=1.20 and rep['reward']==int(ratio>=1.5)
      assert math.isclose(rep['score'],100*max(0,min(1,math.log(ratio)/math.log(8))),abs_tol=1e-9)
      assert rep['formal_environment_qualified'] and rep['formal_evidence_valid'] and rep['baseline_correct'] and rep['scientific_pass']
   if cp.get('repeats'):assert math.isclose(cp['score'],statistics.mean(x['score'] for x in cp['repeats']),abs_tol=1e-9)
 assert records==data['raw_case_records_checked']
 observations=data['execution_observations']
 for path,expected in observations['source_sha256'].items():assert sha(path)==expected
 timeout=observations['ode_g1_internal_timeout'];assert timeout['timeout_seconds']==1200 and timeout['elapsed_seconds']==1200.108
 trace=next(p for p in observations['source_sha256'] if '/sessions/' in p)
 events=[json.loads(line) for line in (ROOT/trace).read_text().splitlines()]
 returns=[e for e in events if e.get('message',{}).get('toolCallId')==timeout['tool_call_id']]
 assert len(returns)==1 and returns[0]['timestamp']==timeout['returned_at']
 assert timeout['result_tail'] in str(returns[0]['message']['content'])
 for a in data['failed_attempts']:
  host=read(a['host_evidence']['path']);registry=read(a['registry_evidence']['path'])
  events=[json.loads(line) for line in (ROOT/a['relay_evidence']['path']).read_text().splitlines()]
  ends=[event for event in events if event['event']=='request_finished']
  assert dict(Counter(event['outcome'] for event in ends))==a['request_outcomes']
  assert sum(event.get('output_tokens') or 0 for event in ends)==a['known_output_tokens']
  assert sum(event.get('charged_output_tokens') or 0 for event in ends)==a['charged_output_tokens']==host['relay_status']['charged_output_tokens']
  assert host['attempt_status']==a['status'] and len(registry['evaluations'])==a['public_evaluations']
 assert data['new_attempts']==9+len(data['failed_attempts'])
 assert data['new_output_tokens']==sum(r['output_tokens'] for r in data['rows'])
 assert data['all_new_attempt_known_output_tokens']==data['new_output_tokens']+sum(a['known_output_tokens'] for a in data['failed_attempts'])
 assert data['all_new_attempt_charged_output_tokens']==sum(r['charged_output_tokens'] for r in data['rows'])+sum(a['charged_output_tokens'] for a in data['failed_attempts'])
 for window in data['timing_windows']:
  evidence=window['acceptance_evidence'];acceptance=read(evidence['path']);directory=Path(evidence['path']).parent
  assert sha(evidence['path'])==evidence['sha256'] and acceptance['status']==window['status'] and acceptance['identity']==window['run_id']
  assert acceptance['model_calls']==0 and sha(directory/'host-observations.jsonl')==acceptance['host_observations_sha256']
  assert sha(directory/'accepted-observer.py')==sha('tests/accepted_t3_calibration.py')
  if window['status']=='passed':
   assert not acceptance['violations'] and not acceptance['observer_errors'] and acceptance['no_running_containers']
   assert sha(directory/'operation-result.json')==acceptance['operation_result_sha256']
   row=next(r for r in data['rows'] if r['run_id']==window['run_id'])
   assert read(directory/'operation-result.json')['diagnostics']==read(row['score_evidence']['path'])['diagnostics']
 for row in data['rows']:
  if row['task']=='poisson':assert sum(w['run_id']==row['run_id'] and w['status']=='passed' for w in data['timing_windows'])==1
 fig=read('results/unified-r1-nine-2026-10-29/figure-manifest.json')
 assert fig['analysis_sha256']==sha('results/unified-r1-nine-2026-10-29/reviewed-results.json') and len(fig['files'])==6
 for p,h in fig['files'].items():assert sha(p)==h
 original=read('logs/heat-unified-r1-2026-10-29/preservation-before.json')['files']
 for p,h in original.items():assert sha(p)==h,p
 links=0
 for file in ('docs/unified-r1-evidence-2026-10-29.md','docs/submission-report-2026-10-24.md','README.md','docs/reproduction.md'):
  for target in re.findall(r'\]\(([^)]+)\)',(ROOT/file).read_text()):
   if target.startswith(('https:','http:','#','mailto:')):continue
   assert ((ROOT/file).parent/target.split('#')[0]).exists(),(file,target);links+=1
 assert not re.search(r'\|[^\n]*Heat G[123] r[23] \|',report)
 assert '## 附录 A.' not in report
 assert len(re.findall(r'\| M\d\d \|',report))==9
 assert read('logs/unified-r1-nine-2026-10-29/service-restoration.json')['restored']
 process=ROOT/'logs/unified-r1-nine-2026-10-29/timing-recovery-002/process-restoration.json'
 if process.exists() and not read(process)['restored']:
  resolution=read(process.parent/'resolution.json')
  assert not read(process)['paused'] and resolution['target_process_exited'] and not resolution['process_restore_required']
 return {'status':'passed','new_sessions':9,'new_attempts':data['new_attempts'],'reward_one':data['new_reward_one'],'raw_case_records_checked':records,'historical_files_unchanged':len(original),'local_links_checked':links,'uniform_executor_verified':True,'request_limit':16384,'normal_compaction':True}
if __name__=='__main__':print(json.dumps(audit(),ensure_ascii=False,indent=2))
