"""Audit all nine unified r1 sessions and rebuild the current report."""
import argparse, hashlib, json, math, re, statistics
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BATCH=ROOT/'logs/unified-r1-nine-2026-10-29'
OUT=ROOT/'results/unified-r1-nine-2026-10-29'
FIG=ROOT/'docs/figures/unified-r1-nine-2026-10-29'
PLAN='freezes/unified-nine-r1-suite-2026-10-29.json'
TASKS=('heat','ode','poisson')
NAMES={'heat':'Heat','ode':'ODE','poisson':'Poisson'}
REPORT=ROOT/'docs/submission-report-2026-10-24.md'
def read(p):return json.loads((ROOT/p).read_text())
def sha(p):return hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def fmt(v):return '—' if v is None else f'{v:.3f}'
def check_case(c,task):
 clip=lambda x:max(0,min(1,x))
 if c.get('artifact_valid') is False:
  assert c['scientific_pass'] is False and c['score']==0;return
 if task=='heat':
  expected=100*(.8*clip(1-c['E_init']/.30)+.2*clip(1-c['E_forward']/.06));passed=c['E_init']<=.15 and c['E_forward']<=.03
 elif task=='ode':
  valid=c.get('K') is not None and c['K']<=10 and c.get('E_roll') is not None and c.get('E_field') is not None
  expected=100*(.5*clip(1-c['E_roll']/.10)+.5*clip(1-c['E_field']/.10)) if valid else 0
  passed=valid and c['E_roll']<=.05 and c['E_field']<=.05
 else:
  assert c['scientific_pass']==(c['max_relative_residual']<=1e-8 and c['max_solution_error']<=1e-5);return
 assert math.isclose(c['score'],expected,abs_tol=1e-9) and c['scientific_pass']==passed

def build_data():
 suite=read(PLAN);assert len(suite['runs'])==9 and suite['status']=='frozen'
 plans={ref['path']:read(ref['path']) for ref in suite['plans']}
 sources={PLAN:sha(PLAN)};attempts=[]
 execution_observations=read('logs/unified-r1-nine-2026-10-29/execution-observations.json')
 for path,expected in execution_observations['source_sha256'].items():
  assert sha(path)==expected; sources[path]=expected
 sources['logs/unified-r1-nine-2026-10-29/execution-observations.json']=sha('logs/unified-r1-nine-2026-10-29/execution-observations.json')
 for path,plan in plans.items():
  assert sha(path)==next(r['sha256'] for r in suite['plans'] if r['path']==path)
  for name,expected in plan['tool_config']['files'].items():assert sha(name)==expected,name
  manifest_path=f"research-runs/{plan['plan_id']}/manifest.json";m=read(manifest_path)
  sources.update({path:sha(path),manifest_path:sha(manifest_path)});attempts.extend(m['attempts'])
 assert read('logs/unified-r1-nine-2026-10-29/state.json')['stage']=='results_ready_for_review'
 assert read('logs/unified-r1-nine-2026-10-29/service-restoration.json')['restored']
 process_path='logs/unified-r1-nine-2026-10-29/timing-recovery-002/process-restoration.json'
 if (ROOT/process_path).exists():
  process=read(process_path)
  if not process['restored']:
   resolution_path='logs/unified-r1-nine-2026-10-29/timing-recovery-002/resolution.json';resolution=read(resolution_path)
   assert not process['paused'] and resolution['target_process_exited'] and not resolution['process_restore_required']
   sources[resolution_path]=sha(resolution_path)
  sources[process_path]=sha(process_path)
 def checked(r):
  assert sha(r['path'])==r['sha256'],r['path'];sources[r['path']]=r['sha256'];return read(r['path'])
 old=checked(ref('results/thinking-r1-report-2026-10-29/analysis.json'))
 old_attempts=checked(ref('results/thinking-control-2026-10-25/reviewed-comparison.json'))['attempt_records']
 failed_attempts=[]
 for entry in attempts:
  host=checked(entry['result'])
  if host['attempt_status'] not in ('completed','research_timeout'):
   reg=checked(entry['registry']);relay=entry['relay_events']
   assert sha(relay['path'])==relay['sha256'];sources[relay['path']]=relay['sha256']
   events=[json.loads(line) for line in (ROOT/relay['path']).read_text().splitlines()]
   failed_attempts.append({'attempt_id':entry['attempt_id'],'status':host['attempt_status'],
    'reason':host['relay_status']['last_request_failure_reason'],
    'known_output_tokens':sum(e.get('output_tokens') or 0 for e in events if e['event']=='request_finished'),
    'charged_output_tokens':host['relay_status']['charged_output_tokens'],
    'request_outcomes':dict(Counter(e['outcome'] for e in events if e['event']=='request_finished')),
    'research_wall_seconds':reg['attempt_outcome']['recorded_at']-reg['started_at'],
    'public_evaluations':len(reg['evaluations']),'host_evidence':entry['result'],'registry_evidence':entry['registry'],'relay_evidence':relay})
 rows=[];native_sources=[];host_sources=[];checked_cases=0;starts=[];ends=[]
 for row in sorted(suite['runs'],key=lambda x:(TASKS.index(x['task']),x['group'])):
  plan=plans[row['plan']['path']]
  entry=[a for a in attempts if a['run_id']==row['run_id']][-1]
  host=checked(entry['result']);reg=checked(entry['registry']);original_replay=checked(entry['replay']);score_ref=entry['replay']
  overrides_path='logs/unified-r1-nine-2026-10-29/timing-overrides.json'
  overrides=checked(ref(overrides_path)) if (ROOT/overrides_path).exists() else {}
  if row['run_id'] in overrides:
   assert original_replay['diagnostics']['evaluation_status']=='invalid'
   score_ref=overrides[row['run_id']]['score_evidence']
   replay=checked(score_ref);assert replay['parent_replay']==entry['replay'] and not replay['independent_research_sample']
  else:replay=original_replay
  assert replay['formal'] and replay['split']=='final-test'
  assert replay['freeze_sha256']==plan['freezes'][row['task']]['sha256'] and replay['registry_sha256']==entry['registry']['sha256']
  assert host['attempt_status'] in ('completed','research_timeout') and not host['cleanup_errors'] and not host['bridge_errors']
  assert host['relay_cleanup']['all_removed'] and host['worker_cleanup']['all_removed']
  limits=host['relay_status']['limits'];assert limits==plan['runtime_policy']
  assert limits['request_output_limit']==16384 and limits['session_output_limit']==200000
  assert host['research_budget_seconds']==1800 and host['max_evaluations']==20 and reg['closed']
  native_sources.append(host['native_setup_evidence']['installed_source_sha256'])
  host_sources.append({k:v for k,v in host['trusted_source_sha256'].items() if not k.startswith('prompts/')})
  for name in ('common.md',row['group']+'.md'):
   assert host['trusted_source_sha256'][f"prompts/{row['task']}/{name}"]==plan['tasks'][row['task']]['prompt_hashes'][name]
  relay=entry['relay_events'];assert sha(relay['path'])==relay['sha256'];sources[relay['path']]=relay['sha256']
  events=[json.loads(line) for line in (ROOT/relay['path']).read_text().splitlines()]
  requests=[e for e in events if e['event']=='request_accepted'];finished=[e for e in events if e['event']=='request_finished']
  assert len(requests)==len(finished) and host['relay_status']['inflight']==0
  assert not host['relay_status']['protocol_violation'] and not host['relay_status']['evidence_error']
  assert all(0<e['effective_max_tokens']<=16384 for e in requests)
  assert max(e['effective_max_tokens'] for e in requests)==16384
  output=sum(e.get('output_tokens') or 0 for e in finished)
  assert output<=limits['session_output_limit']
  ended={e['request_id']:e for e in finished};compactions=[]
  for index,request in enumerate(requests):
   if request.get('request_kind')!='native_compaction':continue
   end=ended[request['request_id']];following=requests[index+1] if index+1<len(requests) else {}
   compactions.append({'request_number':index+1,'effective_max_tokens':request['effective_max_tokens'],'outcome':end['outcome'],
    'output_tokens':end.get('output_tokens'),'wall_seconds':end['timestamp']-request['timestamp'],
    'following_request_kind':following.get('request_kind'),'following_request_limit':following.get('effective_max_tokens')})
  raw=replay['diagnostics'];assert raw['evaluation_status']=='valid'
  starts.append(entry['replay_started_at']);ends.append(host['finished_at'])
  for role in ('first','final'):
   cp=raw[role];assert cp['checkpoint_id']==reg[role+'_id']
   if cp.get('source_hash'):
    source=Path(entry['registry']['path']).parent/'snapshots'/cp['checkpoint_id']
    tree={p.relative_to(ROOT/source).as_posix():sha(p) for p in sorted((ROOT/source).rglob('*')) if p.is_file()}
    assert hashlib.sha256(json.dumps(tree,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==cp['source_hash']
   reps=cp.get('repeats',[])
   if reps:
    assert len(reps)==(1 if row['task']=='poisson' else 3)
    for rep in reps:
     batches=rep['samples']['C'] if row['task']=='poisson' else [rep]
     for batch in batches:
      assert len(batch['cases'])==batch['total']==12
      for c in batch['cases']:
       checked_cases+=1;check_case(c,row['task'])
      assert batch['passed']==sum(c['scientific_pass'] for c in batch['cases'])
      if row['task']!='poisson':assert math.isclose(batch['score'],statistics.mean(c['score'] for c in batch['cases']),abs_tol=1e-9)
     if row['task']=='poisson':
      if rep['performance_status']=='candidate_failed':
       assert rep['score']==0 and rep['reward']==0 and rep['speedup'] is None
       assert any(x.get('scientific_pass') is False or x.get('artifact_valid') is False or x.get('worker',{}).get('resource_qualified') is False for x in rep['samples']['C'])
      else:
       bt=[x['worker']['execution_wall_seconds'] for x in rep['samples']['B']]
       ratio=statistics.median(bt)/statistics.median(x['worker']['execution_wall_seconds'] for x in rep['samples']['C'])
       assert rep['formal_environment_qualified'] and rep['formal_evidence_valid'] and rep['baseline_correct'] and rep['scientific_pass']
       assert max(bt)/min(bt)<=1.20 and rep['reward']==int(ratio>=1.5)
       assert math.isclose(rep['score'],100*max(0,min(1,math.log(ratio)/math.log(8))),abs_tol=1e-9)
       assert math.isclose(rep['speedup'],ratio,abs_tol=1e-9)
    assert math.isclose(cp['score'],statistics.mean(r['score'] for r in reps),abs_tol=1e-9)
  before=next(r for r in old['rows'] if r['task']==row['task'] and r['group']==row['group'] and r['repeat']==1)
  old_group_attempts=[a for a in old_attempts if a['run_id']==before['run_id']]
  final=raw['final'];reps=final.get('repeats',[])
  run=0;longest=0
  for e in requests:
   run=run+1 if e['effective_max_tokens']==1 else 0;longest=max(longest,run)
  rows.append({'label':f"{NAMES[row['task']]} {row['group'].upper()} r1",'task':row['task'],'group':row['group'],'report_id':f'M{len(rows)+1:02d}',
   'run_id':row['run_id'],'attempt_id':entry['attempt_id'],'execution_sequence':row['suite_sequence'],'status':host['attempt_status'],
   'first_score':raw['first']['score'],'final_score':final['score'],'reward':final['reward'],'evaluation_status':final['evaluation_status'],
   'passed_per_replay':[r['passed'] for r in (reps[0]['samples']['C'] if row['task']=='poisson' and reps else reps)],'speedup':reps[0].get('speedup') if reps else None,'old_speedup':before['formal_speedup'],'unique_cases':12 if reps else 0,'public_evaluations':len(reg['evaluations']),
   'first_id':reg['first_id'],'final_id':reg['final_id'],'output_tokens':output,'charged_output_tokens':host['relay_status']['charged_output_tokens'],
   'research_wall_seconds':reg['attempt_outcome']['recorded_at']-reg['started_at'],'successful_requests':host['relay_status']['successful_requests'],'failed_requests':host['relay_status']['failed_requests'],
   'request_outcomes':dict(Counter(e['outcome'] for e in finished)),
   'compaction_attempts':compactions,
   'compaction_requests':sum(e.get('request_kind')=='native_compaction' for e in requests),'one_token_requests':sum(e['effective_max_tokens']==1 for e in requests),'longest_one_token_request_streak':longest,
   'max_requested_output_limit':max(e['effective_max_tokens'] for e in requests),'responses_exceeding_4096':sum((e.get('output_tokens') or 0)>4096 for e in finished),
   'old_final_score':before['thinking_final_score'],'score_delta':final['score']-before['thinking_final_score'],
   'old_output_tokens_retained':before['output_tokens'],'old_output_tokens_all_attempts':sum(a['known_output_tokens'] for a in old_group_attempts),
   'old_research_wall_seconds_retained':before['research_wall_seconds'],'old_public_evaluations':before['public_evaluations'],'old_research_wall_seconds_all_attempts':sum(a['research_wall_seconds'] for a in old_group_attempts),
   'old_attempt_count':len(old_group_attempts),'old_attempt_id':before['attempt_id'],'old_score_evidence':before['score_evidence'],
   'host_evidence':entry['result'],'registry_evidence':entry['registry'],'relay_evidence':relay,'score_evidence':score_ref,'original_score_evidence':entry['replay']})
 assert max(ends)<min(starts),'All research must close before any hidden scoring'
 assert all(s==native_sources[0] for s in native_sources) and all(s==host_sources[0] for s in host_sources),'Executor drift between groups'
 timing_windows=[]
 for path in sorted(BATCH.glob('poisson-*-window-*/acceptance.json')):
  acceptance_ref=ref(path.relative_to(ROOT));acceptance=checked(acceptance_ref)
  assert acceptance['model_calls']==0
  observations=path.parent/'host-observations.jsonl';assert sha(observations)==acceptance['host_observations_sha256']
  sources[str(observations.relative_to(ROOT))]=sha(observations)
  observer=path.parent/'accepted-observer.py';assert sha(observer)==sha('tests/accepted_t3_calibration.py')
  sources[str(observer.relative_to(ROOT))]=sha(observer)
  if acceptance['status']=='passed':
   assert acceptance['evaluation_status']=='valid' and acceptance['no_running_containers'] and not acceptance['violations'] and not acceptance['observer_errors']
   operation=path.parent/'operation-result.json';assert sha(operation)==acceptance['operation_result_sha256']
   scored=checked(ref(operation.relative_to(ROOT)));row=next(r for r in rows if r['run_id']==acceptance['identity'])
   assert scored['diagnostics']==read(row['score_evidence']['path'])['diagnostics']
  timing_windows.append({'window':path.parent.name,'run_id':acceptance['identity'],'status':acceptance['status'],
   'final_test_scores_accessed':acceptance['final_test_scores_accessed'],'violation_count':len(acceptance.get('violations',[])),
   'observer_error_count':len(acceptance.get('observer_errors',[])),'acceptance_evidence':acceptance_ref})
 for row in rows:
  if row['task']=='poisson':assert sum(w['run_id']==row['run_id'] and w['status']=='passed' for w in timing_windows)==1
 preserved=read('logs/heat-unified-r1-2026-10-29/preservation-before.json')['files']
 for p,h in preserved.items():assert sha(p)==h,'Historical evidence changed: '+p
 preservation={'status':'passed','historical_files_checked':len(preserved),'modified_historical_files':[]}
 (BATCH/'preservation-after.json').write_text(json.dumps(preservation,indent=2)+'\n')
 sources['logs/heat-unified-r1-2026-10-29/preservation-before.json']=sha('logs/heat-unified-r1-2026-10-29/preservation-before.json')
 data={'status':'reviewed_terminal','suite_id':suite['suite_id'],'new_sessions':9,'new_attempts':len(attempts),'historical_sessions':15,'historical_attempts':17,
 'combined_session_inventory':24,'combined_attempt_inventory':17+len(attempts),'failed_attempts':failed_attempts,
 'all_new_attempt_known_output_tokens':sum(r['output_tokens'] for r in rows)+sum(r['known_output_tokens'] for r in failed_attempts),
 'all_new_attempt_charged_output_tokens':sum(r['charged_output_tokens'] for r in rows)+sum(r['charged_output_tokens'] for r in failed_attempts),
 'pooling':'Separate protocols; inventory counts are not pooled success/causal comparisons.',
 'request_output_limit':16384,'session_output_limit':200000,'normal_native_compaction':True,'uniform_installed_sources':native_sources[0],
 'uniform_trusted_sources':host_sources[0],'timing_windows':timing_windows,'raw_case_records_checked':checked_cases,'latest_research_finished_at':max(ends),'first_hidden_replay_started_at':min(starts),
 'new_reward_one':sum(r['reward']==1 for r in rows),'new_output_tokens':sum(r['output_tokens'] for r in rows),
 'new_research_wall_seconds':sum(r['research_wall_seconds'] for r in rows),'new_public_evaluations':sum(r['public_evaluations'] for r in rows),
 'author_baselines':old['author_baselines'],'execution_observations':execution_observations,'rows':rows,'preservation':preservation,'source_sha256':dict(sorted(sources.items()))}
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'reviewed-results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');return data

def result_table(data):
 text='| 序号 | 会话 | 最终分 | 数值通过（三次） | reward | 正式加速比 | 研究结局 |\n|---|---|---:|---|---:|---:|---|\n'
 for r in data['rows']:
  passed=' / '.join(map(str,r['passed_per_replay']))+'（每次 12 例）' if r['passed_per_replay'] else '无有效候选'
  speed=f"{r['speedup']:.3f}×" if r['speedup'] is not None else '—'
  text+=f"| {r['report_id']} | {r['label']} | {fmt(r['final_score'])} | {passed} | {r['reward']} | {speed} | {r['status']} |\n"
 return text

def comparison_table(data):
 text='| 会话 | 旧 r1 最终分 | 新 r1 最终分 | 分差 | 旧保留输出 token | 新保留输出 token |\n|---|---:|---:|---:|---:|---:|\n'
 for r in data['rows']:
  text+=f"| {r['label']} | {fmt(r['old_final_score'])} | {fmt(r['final_score'])} | {r['score_delta']:+.3f} | {r['old_output_tokens_retained']:,} | {r['output_tokens']:,} |\n"
 return text

def details_table(data):
 text='| 会话 | first 分 | final 分 | 公开评估 | 输出 token | 研究分钟 | 正常压缩请求 | 单 token 请求 |\n|---|---:|---:|---:|---:|---:|---:|---:|\n'
 for r in data['rows']:
  text+=f"| {r['label']} | {fmt(r['first_score'])} | {fmt(r['final_score'])} | {r['public_evaluations']} | {r['output_tokens']:,} | {r['research_wall_seconds']/60:.2f} | {r['compaction_requests']} | {r['one_token_requests']} |\n"
 return text

def failures_text(data):
 text=''
 for a in data['failed_attempts']:
  outcomes='、'.join(f'{k}={v}' for k,v in a['request_outcomes'].items())
  text+=f"- `{a['attempt_id']}`：终止原因 `{a['reason']}`，已知输出 {a['known_output_tokens']:,} token，charged 额度 {a['charged_output_tokens']:,}，研究 {a['research_wall_seconds']/60:.2f} 分钟，{a['public_evaluations']} 次公开评估。请求结局：{outcomes}。原记录保留，同一冻结配置关联重试。\n"
 return text or '本次没有关联基础设施重试。\n'

def compaction_text(data):
 paragraphs=[]
 for r in data['rows']:
  for a in r['compaction_attempts']:
   tokens='实际输出未知' if a['output_tokens'] is None else f"输出 {a['output_tokens']:,} token"
   following=f"随后为 `{a['following_request_kind']}` 请求，上限 {a['following_request_limit']:,}" if a['following_request_limit'] is not None else '随后没有新请求'
   paragraphs.append(f"{r['label']} 第 {a['request_number']} 个请求为原生压缩：上限 {a['effective_max_tokens']:,}，结局 `{a['outcome']}`，耗时 {a['wall_seconds']:.2f} 秒，{tokens}；{following}。")
 return '\n\n'.join(paragraphs)

def figures(data,font):
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 from matplotlib import font_manager
 from matplotlib.patches import Patch
 if font:
  font_manager.fontManager.addfont(font);plt.rcParams['font.family']=font_manager.FontProperties(fname=font).get_name()
 plt.rcParams.update({'font.size':11,'axes.unicode_minus':False,'svg.fonttype':'path','svg.hashsalt':'uniform-nine-r1-20261029'})
 FIG.mkdir(parents=True,exist_ok=True)
 def save(fig,name):
  for ext in ('png','svg'):fig.savefig(FIG/(name+'.'+ext),dpi=180,bbox_inches='tight',metadata={'Date':None} if ext=='svg' else None)
  plt.close(fig)
 fig,axs=plt.subplots(1,2,figsize=(10,3.5),layout='constrained')
 for i,task in enumerate(TASKS):
  rs=[r for r in data['rows'] if r['task']==task]
  submitted=sum(r['final_id'] is not None for r in rs);success=sum(r['reward']==1 for r in rs)
  for ax,n in ((axs[0],submitted),(axs[1],success)):
   ax.barh(NAMES[task],n,color='#176B87');ax.text(max(.15,n/2),i,f'{n}/3',ha='center',va='center',color='white' if n else '#203044')
 for ax in axs:ax.set(xlim=(0,3.4),xticks=range(4),xlabel='独立 r1 会话数');ax.invert_yaxis();ax.spines[['top','right']].set_visible(False)
 axs[0].set_title('A. 已登记最终候选');axs[1].set_title('B. 正式成功（reward=1）');save(fig,'outcomes')
 for name,keys,title in [('old-new-scores',('old_final_score','final_score'),'历史 r1 与统一执行器 r1'),('first-final-scores',('first_score','final_score'),'统一执行器：首次与最终候选')]:
  fig,axs=plt.subplots(3,1,figsize=(10.5,9.0),layout='constrained')
  colors=('#8798a7','#176B87') if name=='old-new-scores' else ('#176B87','#D66A28')
  for ax,task in zip(axs,TASKS):
   rs=[r for r in data['rows'] if r['task']==task]
   for i,r in enumerate(rs):
    for dx,key,color in zip((-.18,.18),keys,colors):
     ax.bar(i+dx,r[key],.34,color=color);ax.text(i+dx,r[key]+1.5,f'{r[key]:.3f}',ha='center',fontsize=9)
   ax.set(ylim=(0,110),title=NAMES[task],ylabel='任务内分数（0–100）');ax.set_xticks(range(3),['G1 r1','G2 r1','G3 r1']);ax.spines[['top','right']].set_visible(False)
  labels=('旧 r1','统一执行器 r1') if name=='old-new-scores' else ('首次 first','最终 final')
  fig.legend(handles=[Patch(color=c,label=l) for c,l in zip(colors,labels)],loc='outside lower center',ncol=2);fig.suptitle(title);save(fig,name)
 (OUT/'figure-manifest.json').write_text(json.dumps({'analysis_sha256':sha(OUT/'reviewed-results.json'),'run_ids':[r['run_id'] for r in data['rows']],'files':{str(p.relative_to(ROOT)):sha(p) for p in sorted(FIG.iterdir()) if p.suffix in ('.png','.svg')}},indent=2)+'\n')

def write_reports(data):
 import tarfile
 archive=ROOT/'archives/pre-heat-unified-20261029/previous-current-report.tar.gz'
 with tarfile.open(archive) as tar:text=tar.extractfile('docs/submission-report-2026-10-24.md').read().decode()
 text=text.split('## 附录 A.',1)[0].rstrip()+'\n'
 text=text.replace('正文 r1 版 · 2026 年 10 月 29 日补测更新','九组 r1 统一重测 · 2026 年 10 月 29 日')
 text=text.replace('[完整材料与 Release]','[历史发布材料与 Release]')
 def replace_section(start,end,value):
  nonlocal text
  left=text.index(start);right=text.index(end,left) if end else len(text);text=text[:left]+value.rstrip()+'\n\n'+text[right:]
 summary=f'''## 摘要与阅读说明

本版按用户要求，只展示 **Heat、ODE、Poisson × G1、G2、G3 的 r1，共 9 个独立研究会话**。九组全部使用统一修复后的执行器，取消 4,096 单请求截断，采用 Pi 原生 **16,384** 单请求上限；保留正常上下文自动压缩。每会话累计 200,000 输出 token、30 分钟和 20 次公开评估的预算保持不变。

本次 **{data['new_reward_one']}/9 正式成功**，共 {data['new_attempts']} 个 attempt（含关联基础设施重试）。三组 Heat 已开始后，用户将范围扩展至九组；因此用两个不可变子计划记录同一配置，并以总方案要求 **九组研究全部关闭后才开始隐藏评分**。逐项哈希核验确认九组的宿主执行器源码和 Pi 安装源码一致。

旧 r1 仅用于逐组对照，不进入新批次成功率或用量分母。旧 r2/r3、历史失败、旧 PDF 和原始日志全部保留在[历史档案](../archives/pre-heat-unified-20261029/README.md)，本版不再展示 r2/r3。每组只有一次新 r1，分差不能证明指导方式稳定优劣；本次同时修复执行器并提高请求上限，也不能分离两者的因果效应。

分数保留三位小数；`0` 表示按规则得到零分，`—` 表示不适用或没有有效结果。`reward=1` 表示满足该任务全部成功条件。完整数据、失败开销和来源哈希见[九组结果](../results/unified-r1-nine-2026-10-29/reviewed-results.json)，原始记录见[证据索引](unified-r1-evidence-2026-10-29.md)。
'''
 replace_section('## 摘要与阅读说明','## 1.',summary)
 design='''### 4.2 本次只运行 r1

r1 表示每个任务和指导组在本次新协议下的一次独立研究。共有三任务 × 三组 = 9 个会话，均从全新工作区启动，不继承旧解、旧会话或隐藏评测反馈。a001/a002 表示同一会话的关联尝试；基础设施重试单独计开销，不增加会话数。历史 r2/r3 只保留归档，不出现在当前结果表和图中。

### 4.3 展示、执行与评分顺序

结果按 Heat → ODE → Poisson、G1 → G2 → G3 排列，编号 M01–M09。实际执行顺序沿用原预声明的任务内组顺序，详见[总方案](../freezes/unified-nine-r1-suite-2026-10-29.json)。所有九组研究关闭后，才开始 first/final 的隐藏评分；报告没有根据隐藏分数挑选重试或候选。

### 4.4 统一执行器与冻结预算

| 项目 | 本次统一配置 |
|---|---|
| 研究框架 | Harbor / 原生 Pi 0.84.1，统一应用 relay usage、thinking 续接和上下文衔接修复 |
| 模型路由 | deepseek-flash；供应商文档映射为 DeepSeek-V4.1-Flash-1017 |
| thinking / effort | enabled / max，由可信 relay 强制执行 |
| temperature / top_p | thinking 模式 temperature 不生效，记录 null；top_p=1 |
| 单请求输出上限 | 16,384 token，已取消原 4,096 强制截断 |
| 上下文与压缩 | 128,000 窗口；保留原生自动压缩；压缩输出计入累计预算 |
| 每会话累计输出 | 200,000 token，包含 thinking 和普通输出 |
| 每会话其他上限 | 1,800 秒；20 次公开评估，任一预算先到则停止 |
| 科学设置 | 数据、提示、评分、求解器种子、冻结镜像和研究资源沿用原设置 |

三个 Heat 会话与后续六个 ODE/Poisson 会话分别受[Heat 子计划](../freezes/research-run-plan-heat-unified-r1-2026-10-29.json)和[其余六组子计划](../freezes/research-run-plan-unified-ode-poisson-r1-2026-10-29.json)约束，两者模型、工具配置、资源逐项一致；[九组总方案](../freezes/unified-nine-r1-suite-2026-10-29.json)统一顺序与评分屏障。供应商别名不可独立锁定内部修订；本次沿用已用过的隐藏集，属于事后对照，不能称为全新盲测。
'''
 replace_section('### 4.2','## 5.',design)
 results=f'''## 7. 统一执行器的九组 r1 结果

### 7.1 本次结果

![图1：九组 r1 的候选登记和正式成功](figures/unified-r1-nine-2026-10-29/outcomes.png)

{result_table(data)}
上表只包含本次新协议的九组 r1。数值通过列分别列出三次独立重放的通过例数，每次为同一套 12 例，不能把三次重放当成三个独立研究会话。研究正常返回、到达预算以及最终 reward 分别报告。

### 7.2 与历史 r1 逐组对照

{comparison_table(data)}
![图2：历史 r1 与本次统一执行器 r1 的最终分数](figures/unified-r1-nine-2026-10-29/old-new-scores.png)

历史 Poisson G1、G2 采用各自已获准的独立计时结果；其原无效窗口继续保留。新 Poisson 使用本次新候选及新获准计时窗口。新旧差异同时包含执行器修复、单次输出上限变化及独立会话的随机变化，不能直接作因果解释；三个任务的分数含义不同，不计算跨任务平均分。

### 7.3 会话内迭代与资源

{details_table(data)}
![图3：本次九组 r1 首次与最终候选](figures/unified-r1-nine-2026-10-29/first-final-scores.png)

九个保留 attempt 共输出 **{data['new_output_tokens']:,} token**，研究执行时间合计 **{data['new_research_wall_seconds']/60:.2f} 分钟**，公开评估 **{data['new_public_evaluations']} 次**。计入本次失败 attempt 后，已知输出为 **{data['all_new_attempt_known_output_tokens']:,}**，relay charged 额度为 **{data['all_new_attempt_charged_output_tokens']:,}**；charged 不是货币账单，未完整返回的请求不能把保守额度当成实际输出。执行顺序、逐次请求、压缩次数及重试开销在机器可读数据中保留。

研究墙钟取可信注册表的开始至关闭时间，包含预算到期后的少量终止与登记收尾开销，因此个别读数略超过 30 分钟；研究预算仍统一为 1,800 秒，没有额外续时。

单 token 响应可能是上下文边界的临时现象；应结合后续压缩和恢复判断。原故障是持续无进展循环。此次按真实请求日志核对，单请求上限达到 16,384；每组实际超过 4,096 输出的响应数量也独立记录。

九个保留 attempt 合计 {sum(r['compaction_requests'] for r in data['rows'])} 次原生压缩请求、{sum(r['one_token_requests'] for r in data['rows'])} 次单 token 请求，最长连续单 token 请求为 {max(r['longest_one_token_request_streak'] for r in data['rows'])} 次。{'本批研究没有实际触发上下文压缩；保留和恢复压缩路径的验证来自单列的合成验收，不能写成本批已实测发生压缩。' if not sum(r['compaction_requests'] for r in data['rows']) else '压缩请求和输出已计入上述实际用量。'}

{compaction_text(data)}

九个保留 attempt 内累计有 {sum(r['failed_requests'] for r in data['rows'])} 次失败请求；客户端中断、可恢复的传输错误与整个 attempt 的基础设施失败分别保留在请求结局字段中。未完整返回的请求即使随后续接，其额度和原记录也不删除。

### 7.4 Poisson 正式计时

'''
 results+='| 会话 | 正式加速比 | 最终分 | 计时证据 |\n|---|---:|---:|---|\n'
 for r in data['rows']:
  if r['task']=='poisson':
   speed=f"{r['speedup']:.3f}×" if r['speedup'] is not None else '—'
   results+=f"| {r['label']} | {speed} | {fmt(r['final_score'])} | [独立评分](../{r['score_evidence']['path']}) |\n"
 results+='\n固定 Jacobi-CG 基线 B 与候选 C 按 B、C、C、B、B、C 交错运行，使用新容器并计算完整批次耗时。准入和测量期间持续观察宿主活动；拒绝窗口保留，不以无效计时补成正式成绩。\n'
 results+='\n| 计时窗口 | 结局 | 是否已进入评分 | 准入与观察证据 |\n|---|---|---|---|\n'
 for w in data['timing_windows']:
  results+=f"| {w['window']} | {w['status']} | {'是' if w['final_test_scores_accessed'] else '否'} | [记录](../{w['acceptance_evidence']['path']}) |\n"
 rechecked=[r for r in data['rows'] if r['score_evidence']!=r['original_score_evidence']]
 if rechecked:
  results+='\nPoisson G3 原正式评分窗口通过准入后，测量期间检测到 ToDesk 的 `/usr/bin/log` 子进程活动，因此原计时作废而非记零。对相同 first/final 封存源码另建独立计时记录，原注册表、研究过程和无效评分均未覆盖；没有追加模型研究或修改候选。准入失败与测量中失效的全部窗口均列在上表。\n'
  for row in rechecked:
   results+=f"\n{row['label']}：[原无效评分](../{row['original_score_evidence']['path']}) · [独立计时复核](../{row['score_evidence']['path']})。\n"
  results+='\n用户已允许临时暂停干扰日志进程，但该子进程在管理员认证完成前已退出，因此未实际发送暂停信号；待认证程序已撤销，ToDesk 主服务保持运行。随后重新进行同标准观察，G3、G2、G1 分别在第 8、2、3 个窗口通过。全部 13 个窗口中，9 个在准入阶段被拒绝，1 个测量中失效，3 个通过；此后未再次评分已通过的结果。详情见[进程状态说明](../logs/unified-r1-nine-2026-10-29/timing-recovery-002/resolution.json)和[计时续测策略](../logs/unified-r1-nine-2026-10-29/timing-recovery-003/policy.json)。准入阈值、观察器、冻结资源及样本顺序保持不变。\n'
 replace_section('## 7.','## 8.',results)
 example=next(r for r in data['rows'] if r['task']=='heat' and r['group']=='g1');reg=read(example['registry_evidence']['path']);raw=read(example['score_evidence']['path'])['diagnostics']
 selected={k:reg[k] for k in ('first_id','final_id','selection_reason')};scores={role:{k:raw[role][k] for k in ('checkpoint_id','score','reward','evaluation_status')} for role in ('first','final')}
 case=f'''## 8. 端到端案例：本次 Heat G1 r1

该会话在统一执行器下从新工作区开始，公开评估 {example['public_evaluations']} 次；可信注册表记录首次与最终候选，研究关闭后才进行独立评分。首次分为 {fmt(example['first_score'])}，最终分为 {fmt(example['final_score'])}。以下节选逐字段对应原始记录，完整源码与公开反馈可沿证据链接检查。

首次候选使用 32 阶正弦基展开，通过热方程的衰减系数构造观测矩阵，再以带 k² 平滑权重的 Tikhonov 正则化反演初值。最终候选保留同一基展开，改用噪声方差加权的后验均值，将固定平滑先验与按观测边际似然选择的经验贝叶斯先验各取一半。实现见[首次源码](../{Path(example['registry_evidence']['path']).parent}/snapshots/{reg['first_id']}/solve.py)和[最终源码](../{Path(example['registry_evidence']['path']).parent}/snapshots/{reg['final_id']}/solve.py)。

六个公开开发实例的平均残差指标 R 从 {data['execution_observations']['heat_g1_public_feedback'][0]['mean_R']:.3f} 降至 {data['execution_observations']['heat_g1_public_feedback'][-1]['mean_R']:.3f}，但最终隐藏分未高于首次候选。这说明公开观测拟合改善不等于隐藏初值恢复误差改善，也说明 first/final 应同时保留。

```json
{json.dumps(selected,ensure_ascii=False,indent=2)}
```

```json
{json.dumps(scores,ensure_ascii=False,indent=2)}
```

[研究记录](../{example['host_evidence']['path']}) · [登记与公开反馈](../{example['registry_evidence']['path']}) · [独立评分](../{example['score_evidence']['path']})。每个不同源码候选均独立重放三次，相同源码复用评分，不重复计研究样本。旧 Heat G1 r1 的 252 次单 token 循环记录保留在历史报告中。
'''
 replace_section('## 8.','## 9.',case)
 up=sum(r['score_delta']>1e-9 for r in data['rows']);down=sum(r['score_delta']< -1e-9 for r in data['rows']);same=9-up-down
 missing_notes='\n\n'.join(f"**{r['label']} 未登记最终候选**：研究结局为 `{r['status']}`，用时 {r['research_wall_seconds']/60:.2f} 分钟，公开评估 {r['public_evaluations']} 次，失败请求 {r['failed_requests']} 次，单 token 请求 {r['one_token_requests']} 次。按评分规则保留未提交结局，不使用该会话已关闭的基础设施失败 attempt 作为替补，也不为取得更高分追加研究。" for r in data['rows'] if r['final_id'] is None)
 analysis=f'''## 9. 结果分析与适用范围

### 9.1 本次观察

本次九组共 {data['new_reward_one']}/9 正式成功。相对历史 r1，最终分 **{up} 升、{down} 降、{same} 相同**；这描述九次独立运行的结果，不代表稳定排序或统计显著性。统一执行器消除了新批次内部中途修复造成的版本差异，但无法消除单次模型运行的随机性。

{missing_notes}

ODE G1 的原始工具轨迹显示：内部 `synthetic_test.py` 在第约 10 分钟启动，单条命令设置 1,200 秒超时，实际等待 1,200.108 秒后超时；它占用了约三分之二的研究预算。随后会话到达总预算，仍未公开评估或登记候选。该记录支持“内部计算与提交安排耗尽预算”的解释；没有证据表明此次未提交由旧 4,096 截断或单 token 循环造成。对应时间戳、调用 ID 和轨迹哈希见[执行观察](../logs/unified-r1-nine-2026-10-29/execution-observations.json)。

作为原故障最直接的对照，Heat G1 保留 attempt 的研究墙钟从历史 {example['old_research_wall_seconds_retained']/60:.2f} 分钟变为本次 {example['research_wall_seconds']/60:.2f} 分钟，公开评估从 {example['old_public_evaluations']} 次变为 {example['public_evaluations']} 次；本次结局为 `{example['status']}`，单 token 请求 {example['one_token_requests']} 次，最长连续 {example['longest_one_token_request_streak']} 次。时间与有效研究内容不能直接等同，但这些记录可用于判断旧版循环是否复现。

### 9.2 基础设施失败与恢复

历史批次发生 relay 输入 usage 修订误判、纯 thinking 达到 4,096 后未续接、续接绕过原生压缩三类问题，直接影响 Heat G3/G1 r1。旧 Heat G1 的 252 次无进展请求持续约 12.5 分钟；这些历史代价与源码修复链继续保留，不能归因于模型数学能力。

本次在第一组开始前统一应用修复，380 项 Python 测试、12 项原生循环测试、4 项完整 AgentSession 测试通过；真实接口验收验证了上下文边界后的正常压缩、恢复和 16,384 有效请求额度。合成验收消耗 546 已知输出 token，单列于科学研究用量之外。

{failures_text(data)}
本次基础设施失败 attempt 保留，不给失败流填造科学零分；关联重试使用相同配置和新工作区。有效科学结果不因分数低而重试。数据库按授权临时停止，并在完成或异常退出时恢复。

### 9.3 结论边界

本版支持比较这九个研究会话及已提交候选在固定任务上的结果，检验完整研究、提交和独立评分流程。每任务每组只有一次新 r1，没有足够重复支持稳定排名或显著性结论。修复和输出上限同时变化，不能从新旧分差分离各自贡献；同一隐藏集已使用过，供应商内部模型修订不可锁定，串行执行也可能受到时间变化影响。

历史 r2/r3 仅存档，不进入当前表格、图表、成功率和成本分母。历史 r1 与本次 r1 两种协议分开统计，重试不会增加九组研究的分母。
'''
 replace_section('## 9.','## 10.',analysis)
 text=text.replace('固定修复后的执行器，随机化运行顺序；分别控制 thinking 与 effort','在本次统一执行器基础上随机化运行顺序；分别控制输出上限、thinking 与 effort')
 text=text.replace('本轮 10 项有效基线覆盖三任务，1 项拒绝明示','保留的作者基线有 10 项有效结果，覆盖三任务，1 项拒绝明示')
 text=text.replace('| GitHub 完整交付 | 调研、任务、数据、配置、基线、判题、原始日志、结果和 README |','| 交付材料 | 本地已更新重测结果、报告、README 与证据；九组重测材料尚未推送 |')
 text=text.replace('G2 的历史数值检查与无效计时可作诊断；10 月 29 日新窗口通过完整观察后获得正式成绩。两类证据分列，见第 7.4 节。','历史及本次无效计时仅作诊断，不作为正式速度。本次三个 Poisson 会话均在完整观察通过后取得成绩，所有准入和测量记录分列于第 7.4 节。')
 text=text.replace('ODE/Poisson 也增加组内重复，并引入更多模型和数据种子','三任务均增加组内重复，并引入更多模型和数据种子')
 text=text.replace('无需模型或 Docker 即可核验现有证据并重建排序表：','本次材料在当前本地工作区中核验；下列命令不调用模型或 Docker。GitHub 上的已发布版本仍为历史版本，尚不包含此次九组重测：')
 text=text.replace('git clone https://github.com/bxf1/sciresearch-bench-lite.git\ncd sciresearch-bench-lite\n','')
 text=text.replace('三任务均有成功案例；Heat G1 r1 展示真实候选、公开反馈和独立评分','三任务均完成端到端执行；Heat G1 r1 展示真实登记和独立评分')
 text=text.replace('`research-runs/` 与 `logs/` 保留原始记录，完整轨迹与作者数据由 Release 独立附件提供。历史标签的自动源码 ZIP 不是最新 main；请以 main 的本报告和 README 为入口。上一版阅读材料已[按文件哈希独立暂存](../archives/pre-thinking-only-20261025/README.md)，本次未改写历史证据、失败状态或冻结参数。','`research-runs/` 与 `logs/` 在本地保留此次原始记录；Release 中已有附件仅对应历史批次。本次九组重测及报告尚未推送或上传。上一版本已[按文件哈希独立暂存](../archives/pre-heat-unified-20261029/README.md)，历史证据、失败状态和旧冻结参数均未改写。')
 conclusion=f'''## 12. 结论

本项目完成三条科学计算任务、90 个合成实例、作者基线、隔离环境和自动评分。本版实验范围严格为三任务 × 三指导组的 r1，共九组；九组使用统一修复执行器及 16,384 单请求上限，保留正常上下文压缩，取得 **{data['new_reward_one']}/9 正式成功**。

新旧 r1 结果、基础设施失败和用量分别列出。独立评分验证具体候选的正确性与性能，单次实验仍不足以证明某指导组普遍更好。历史报告、r2/r3、旧候选及原始日志继续归档，未覆盖或删除。
'''
 replace_section('## 12.',None,conclusion)
 text=text.replace('sciresearch-thinking-r1-report-20261029.pdf','sciresearch-unified-r1-report-20261029.pdf')
 text=text.replace('第 7–8 节、[正文与附录证据索引](thinking-report-evidence-2026-10-29.md)','第 7–8 节、[九组证据索引](unified-r1-evidence-2026-10-29.md)')
 text=text.replace('python3 tools/audit_thinking_report.py','python3 tools/audit_unified_r1_report.py').replace('python3 tools/build_final_report.py','python3 tools/build_unified_r1_report.py')
 text=text.replace('../results/thinking-r1-report-2026-10-29/ordered-results.md','../results/unified-r1-nine-2026-10-29/ordered-results.md').replace('../results/thinking-r1-report-2026-10-29/analysis.json','../results/unified-r1-nine-2026-10-29/reviewed-results.json')
 text=text.replace('三张图使用同一数据。','三张图仅使用本次九组 r1 与其历史 r1 配对数据。')
 text=text.replace('本次未改写历史证据、失败状态或冻结参数。','本次新建统一协议，历史证据、失败状态和旧冻结参数均未改写。')
 # Clarify that the fixed author methods are preserved checks, not nine more agent sessions.
 text=text.replace('## 6. 作者基线：任务是否可解、评分是否有区分度','## 6. 保留的作者基线：任务是否可解、评分是否有区分度\n\n本节沿用既有作者方法的独立验证，供任务和评分解释使用；它们不计入本次九组 Agent r1，也不是本次重跑的研究会话。')
 REPORT.write_text(text.rstrip()+'\n')
 (OUT/'ordered-results.md').write_text('# 九组统一执行器 r1\n\n'+result_table(data)+'\n## 历史 r1 对照\n\n'+comparison_table(data)+'\n## 迭代与成本\n\n'+details_table(data)+'\n## 失败尝试\n\n'+failures_text(data))
 evidence='# 九组统一执行器 r1：证据索引\n\n本索引只列 Heat、ODE、Poisson 的 G1/G2/G3 r1。旧 r1 配对保留；r2/r3 仅见历史档案。全部完整精度与哈希见[机器可读结果](../results/unified-r1-nine-2026-10-29/reviewed-results.json)。\n\n| 编号 | 会话 | 研究 | 登记 | 请求 | 新评分 | 旧 r1 评分 |\n|---|---|---|---|---|---|---|\n'
 for r in data['rows']:
  evidence+=f"| {r['report_id']} | {r['label']} | "+' | '.join(f"[{label}](../{r[key]['path']})" for key,label in [('host_evidence','host'),('registry_evidence','登记'),('relay_evidence','relay'),('score_evidence','新评分'),('old_score_evidence','历史评分')])+' |\n'
 evidence+='\n## 配置与验收\n\n[九组总方案](../freezes/unified-nine-r1-suite-2026-10-29.json) · [原生执行器验收](../logs/heat-unified-r1-2026-10-29/executor-validation.json) · [全九组研究关闭屏障](../logs/unified-r1-nine-2026-10-29/research-closure.json) · [历史文件保全](../logs/unified-r1-nine-2026-10-29/preservation-after.json) · [数据库恢复](../logs/unified-r1-nine-2026-10-29/service-restoration.json)。\n\n## 失败尝试\n\n'+failures_text(data)
 (ROOT/'docs/unified-r1-evidence-2026-10-29.md').write_text(evidence)
 write_delivery_docs(data)

def write_delivery_docs(data):
 import tarfile
 with tarfile.open(ROOT/'archives/pre-heat-unified-20261029/previous-current-report.tar.gz') as archive:
  text=archive.extractfile('README.md').read().decode()
 text=text.replace('最终报告 PDF（2026-10-29 补测更新，含附录）','最终报告 PDF（2026-10-29，九组 r1 统一重测）').replace('sciresearch-thinking-r1-report-20261029.pdf','sciresearch-unified-r1-report-20261029.pdf')
 text=text.replace('本地报告已合入 Poisson G2 的有效补测；本次更新尚未推送 GitHub 或上传 Release。','本地报告已更新为九组 r1 的统一执行器重测，保留历史 r1 对照；本次更新尚未推送 GitHub 或上传 Release。')
 text=text.replace('[正文与附录结果数据](results/thinking-r1-report-2026-10-29/analysis.json)、[逐会话原始证据索引](docs/thinking-report-evidence-2026-10-29.md)','[本次九组结果数据](results/unified-r1-nine-2026-10-29/reviewed-results.json)、[逐会话原始证据索引](docs/unified-r1-evidence-2026-10-29.md)')
 left=text.index('## 实验设计与编号');right=text.index('## 快速核验与复现',left)
 section='''## 实验设计与编号

本次仅运行 **Heat、ODE、Poisson × G1、G2、G3 的 r1，共九组**。九组均使用修复后的统一执行器和新工作区，`thinking=enabled`、`effort=max`，模型路由 `deepseek-flash`。已取消 4,096 强制截断，采用 Pi 原生 **16,384 单请求输出上限**，保留正常上下文自动压缩。每会话总预算仍为 **30 分钟、20 次公开评估、200,000 输出 token**。配置与执行顺序见[九组总方案](freezes/unified-nine-r1-suite-2026-10-29.json)。

| 编号 | 含义 |
|---|---|
| G1 | 共同任务说明 + 详细方法指导 |
| G2 | 共同任务说明 + 研究方向，不给具体算法名 |
| G3 | 共同任务说明，Agent 自行选择方法 |
| r1 | 每个任务和组在本次协议下的一次独立研究 |
| a001 / a002 | 同一会话的执行尝试 / 关联基础设施重试，不增加科学样本数 |

全部九组研究关闭后才开始隐藏评分。候选的三次评分重放不增加研究会话数。旧 r1 单独对照，历史 r2/r3 仅[归档保留](archives/pre-heat-unified-20261029/README.md)，不进入当前结果分母。

## 九组 r1 重测结果

下表为最终候选独立评分，保留三位小数；不同任务不计算合并平均分。

| 任务 | G1 r1 | G2 r1 | G3 r1 |
|---|---:|---:|---:|
'''
 for task in TASKS:
  rs=[r for r in data['rows'] if r['task']==task]
  section+='| '+NAMES[task]+' | '+' | '.join(fmt(r['final_score']) for r in rs)+' |\n'
 section+=f"\n本次 **{data['new_reward_one']}/9 正式成功**，涉及 {data['new_attempts']} 个 attempt。{len(data['failed_attempts'])} 个基础设施失败 attempt 的状态、日志和开销保留，不填造科学零分。九个保留 attempt 已知输出 {data['new_output_tokens']:,} token，含失败尝试共 {data['all_new_attempt_known_output_tokens']:,} token。\n\n"
 section+='ODE G1 r1 在 30 分钟预算内未登记候选，按规则记零；其内部合成测试单条命令耗时约 20 分钟并超时，未出现旧版持续单 token 循环。其他八组均通过全部 12 例及各自成功门槛。\n\n'
 section+='### 历史 r1 配对对照\n\n'+comparison_table(data)+'\n每组仅一次新 r1，分差不能证明稳定优劣；修复、输出上限和运行随机性同时变化，不能分别归因。完整 first/final、数值通过、Poisson 加速比及失败开销见[报告](docs/submission-report-2026-10-24.md)与[原始证据索引](docs/unified-r1-evidence-2026-10-29.md)。\n\n'
 text=text[:left]+section+text[right:]
 text=text.replace('git clone https://github.com/bxf1/sciresearch-bench-lite.git\ncd sciresearch-bench-lite\n','# 在包含此次重测材料的本地仓库根目录运行\n')
 text=text.replace('python3 tools/audit_thinking_report.py','python3 tools/audit_unified_r1_report.py')
 text=text.replace('[交付核对清单](docs/delivery-audit-thinking-r1-2026-10-29.md)记录正文/附录统计口径及图表、日志、PDF 的对应关系。','[交付核对清单](docs/delivery-audit-unified-r1-2026-10-29.md)记录九组统计口径及图表、日志、PDF 的对应关系。')
 text=text.replace('小样本、同宿主运行、已使用过的隐藏集、中途基础设施修复及供应商模型路由变化限制了结论','小样本、同宿主运行、已使用过的隐藏集、新旧协议变化及供应商模型路由变化限制了结论')
 (ROOT/'README.md').write_text(text)
 note=f'''# 九组统一执行器 r1：交付核对

当前研究范围严格为三任务 × 三组的 r1，共 **9 个会话、{data['new_attempts']} 个 attempt**。历史 r1 作为配对对照，r2/r3 仅归档；当前结果、图表和成功率均不纳入 r2/r3。

| 检查项 | 证据 |
|---|---|
| 统一配置、来源与预算 | [总方案](../freezes/unified-nine-r1-suite-2026-10-29.json)；两个子计划的执行器、模型、资源一致 |
| 取消 4,096 截断 | 单请求 16,384；正常原生压缩保留；每会话总输出 200,000 |
| 全九组研究关闭后评分 | [关闭记录](../logs/unified-r1-nine-2026-10-29/research-closure.json)；结果审计核对时间顺序 |
| 原始数值与速度 | [结果 JSON](../results/unified-r1-nine-2026-10-29/reviewed-results.json)与[证据索引](unified-r1-evidence-2026-10-29.md) |
| 历史保全 | {data['preservation']['historical_files_checked']:,} 个原文件哈希未变；[旧版快照](../archives/pre-heat-unified-20261029/README.md) |
| 服务恢复 | [恢复记录](../logs/unified-r1-nine-2026-10-29/service-restoration.json) |
| 当前成品 | [Markdown](submission-report-2026-10-24.md)、[离线 HTML](submission-report-2026-10-24.html)、[PDF](../output/pdf/sciresearch-unified-r1-report-20261029.pdf) |
| 图表数据对应 | [图表清单](../results/unified-r1-nine-2026-10-29/figure-manifest.json)绑定结果 JSON 哈希 |

`python3 tools/audit_unified_r1_report.py` 逐例重算评分、核对请求用量、源码、图表和历史文件。`python3 tools/audit_thinking_report.py --archived` 审核归档报告。`python3 tools/verify_delivery.py` 检查整体交付哈希与新旧证据链。上述命令只核验保存的证据，不调用模型或启动新实验。

本次更新只在本地，尚未推送 GitHub 或上传 Release。旧 PDF 和原始失败记录未覆盖。
'''
 (ROOT/'docs/delivery-audit-unified-r1-2026-10-29.md').write_text(note)

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--figures',action='store_true');parser.add_argument('--html',action='store_true');parser.add_argument('--font');args=parser.parse_args()
 data=build_data();write_reports(data)
 if args.figures:figures(data,args.font)
 if args.html:
  from build_final_report import html_report
  html_report(local_evidence=True)
 print(json.dumps({'status':data['status'],'new_sessions':9,'attempts':data['new_attempts'],'reward_one':data['new_reward_one'],'historical_files_preserved':data['preservation']['historical_files_checked'],'raw_cases_checked':data['raw_case_records_checked']},ensure_ascii=False))
