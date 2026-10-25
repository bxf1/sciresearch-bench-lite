"""Read-only audit of thinking-only figures, tables and their raw scientific evidence."""
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT/path).read_text())


def sha(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def close(a,b):
    assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9),(a,b)


def audit():
    data=read('results/thinking-report-2026-10-25/analysis.json')
    for p,h in data['source_sha256'].items():assert sha(p)==h,p
    rows=data['rows']
    expected=[(t,g,r) for t in ('heat','ode','poisson') for g in ('g1','g2','g3') for r in range(1,4 if t=='heat' else 2)]
    assert [(r['task'],r['group'],r['repeat']) for r in rows]==expected
    assert not any(k.startswith('old_') or k=='paired_delta' for r in rows for k in r)
    assert [r['display_order'] for r in rows]==list(range(1,16))
    assert sorted(r['execution_sequence'] for r in rows)==list(range(1,16))
    checked_cases=0
    def check_checkpoint(d,task):
        nonlocal checked_cases
        reps=d['repeats']
        scores=[]
        for rep in reps:
            batches=rep['samples']['C'] if task=='poisson' else [rep]
            for batch in batches:
                assert batch['total']==12 and len(batch['cases'])==12
                assert len({c['id'] for c in batch['cases']})==12
                for c in batch['cases']:
                    checked_cases+=1
                    clip=lambda x:max(0,min(1,x))
                    if task=='heat':
                        close(c['score'],100*(.8*clip(1-c['E_init']/.30)+.2*clip(1-c['E_forward']/.06)))
                        assert c['scientific_pass']==(c['E_init']<=.15 and c['E_forward']<=.03)
                    elif task=='ode':
                        if c.get('K') is not None and c['K']<=10 and c.get('E_roll') is not None and c.get('E_field') is not None:
                            close(c['score'],100*(.5*clip(1-c['E_roll']/.10)+.5*clip(1-c['E_field']/.10)))
                            assert c['scientific_pass']==(c['E_roll']<=.05 and c['E_field']<=.05)
                        else:assert c['score']==0 and not c['scientific_pass']
                    else:
                        assert c['scientific_pass']==(c['max_relative_residual']<=1e-8 and c['max_solution_error']<=1e-5)
                assert batch['passed']==sum(c['scientific_pass'] for c in batch['cases'])
                if task!='poisson':close(batch['score'],statistics.mean(c['score'] for c in batch['cases']))
            if task=='poisson':
                b=[s['worker']['execution_wall_seconds'] for s in rep['samples']['B']]
                c=[s['worker']['execution_wall_seconds'] for s in rep['samples']['C']]
                assert len(b)==len(c)==3
                ratio=statistics.median(b)/statistics.median(c)
                if d['score'] is not None:
                    assert rep['formal_environment_qualified'] and rep['formal_evidence_valid']
                    close(rep['speedup'],ratio);close(rep['score'],100*max(0,min(1,math.log(ratio)/math.log(8))))
                    assert rep['reward']==int(ratio>=1.5 and all(s['passed']==12 for s in rep['samples']['C']))
                else:assert rep['score'] is None and rep['reward'] is None
            if rep['score'] is not None:scores.append(rep['score'])
        if d['score'] is not None:close(d['score'],statistics.mean(scores))
    for r in rows:
        host=read(r['host_evidence']['path']);reg=read(r['registry_evidence']['path'])
        assert reg['closed'] and host['relay_cleanup']['all_removed'] and host['worker_cleanup']['all_removed']
        assert not host['cleanup_errors']
        limits=host['relay_status']['limits']
        assert limits['request_output_limit']==4096 and limits['session_output_limit']==200000
        assert limits['thinking']=={'type':'enabled'} and limits['output_config']=={'effort':'max'}
        assert host['research_budget_seconds']==1800 and host['max_evaluations']==20
        events=[json.loads(s) for s in (ROOT/r['relay_evidence']['path']).read_text().splitlines()]
        finished=[e for e in events if e['event']=='request_finished']
        assert sum(e.get('output_tokens') or 0 for e in finished)==r['output_tokens']
        assert len(reg['evaluations'])==r['public_evaluations']
        close(reg['attempt_outcome']['recorded_at']-reg['started_at'],r['research_wall_seconds'])
        d=read(r['score_evidence']['path'])['diagnostics']
        for role in ('first','final'):
            cp=d[role];assert cp['score']==r[f'thinking_{role}_score']
            snapshot=Path(r['registry_evidence']['path']).parent/'snapshots'/r[role+'_id']
            tree={p.relative_to(ROOT/snapshot).as_posix():sha(p) for p in sorted((ROOT/snapshot).rglob('*')) if p.is_file()}
            canonical=json.dumps(tree,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            assert hashlib.sha256(canonical).hexdigest()==r[role+'_source_hash']
            check_checkpoint(cp,r['task'])
        assert d['final']['reward']==r['thinking_reward']
    for b in data['author_baselines']:
        if b['score'] is None:
            assert read(b['evidence']['path'])['status']=='host_preflight_rejected'
        else:check_checkpoint(read(b['evidence']['path'])['diagnostics'],b['task'])
    assert len(rows)==15 and sum(r['thinking_reward']==1 for r in rows)==14
    assert sum(b['score'] is not None for b in data['author_baselines'])==10
    for d in data['g2_diagnostics']:
        close(d['raw_median_ratio_diagnostic_only'],statistics.median(d['baseline_seconds'])/statistics.median(d['candidate_seconds']))
        assert d['formal_score'] is None and not d['formal_timing_accepted']
    report=(ROOT/'docs/submission-report-2026-10-24.md').read_text()
    for phrase in ('原最终分','paired-scores.png','原批次 6/15','关闭 thinking |','research-6615cd7900ba0750'):
        assert phrase not in report,phrase
    # Verify verbatim selected fields against actual raw records, not a generated summary.
    snippets=[json.loads(v) for v in re.findall(r'```json\n(.*?)\n```',report,re.S)]
    example=next(r for r in rows if r['label']=='Heat G1 r2')
    reg=read(example['registry_evidence']['path']);raw=read(example['score_evidence']['path'])['diagnostics']
    assert snippets[0]=={k:reg[k] for k in snippets[0]}
    assert snippets[1]=={role:{k:raw[role][k] for k in snippets[1][role]} for role in snippets[1]}
    assert '93.271450' in report and '93.626867' in report
    # Check all current local Markdown destinations; historical files remain independently hashed.
    link_count=0
    for name in ('README.md','docs/submission-report-2026-10-24.md','docs/thinking-report-evidence-2026-10-25.md','docs/reproduction.md'):
        for target in re.findall(r'\]\(([^)]+)\)',(ROOT/name).read_text()):
            if target.startswith(('https:','http:','#','mailto:')):continue
            path=(ROOT/name).parent/target.split('#')[0]
            assert path.exists(),(name,target)
            link_count+=1
    fig=read('results/thinking-report-2026-10-25/figure-manifest.json')
    assert fig['analysis_sha256']==sha('results/thinking-report-2026-10-25/analysis.json')
    assert len(fig['files'])==6
    for name,h in fig['files'].items():assert sha(name)==h
    assert len(re.findall(r'!\[.*?\]\(figures/thinking-report/.*?\.png\)',report))==3
    archive='archives/pre-thinking-only-20261025/previous-comparison-report.tar.gz'
    saved=read('archives/pre-thinking-only-20261025/manifest.json')
    assert sha(archive)==saved['archive_sha256']
    with tarfile.open(ROOT/archive) as tar:
        members=tar.getmembers();assert len(members)==len(saved['files'])
        for member,row in zip(members,saved['files']):
            assert member.isfile() and member.name.endswith(row['path'])
            assert hashlib.sha256(tar.extractfile(member).read()).hexdigest()==row['sha256']
    return {'status':'passed','scope':'thinking_only','sessions':15,'valid_scores':14,'reward_one':14,
      'baseline_valid':10,'baseline_preflight_rejected':1,'raw_case_records_checked':checked_cases,
      'source_hashes_verified':len(data['source_sha256']),'local_links_checked':link_count,
      'figure_files_verified':6,'previous_report_files_preserved':len(saved['files']),
      'g2_formal_score':None,'new_model_calls':0,'new_candidate_executions':0}


if __name__=='__main__':
    print(json.dumps(audit(),ensure_ascii=False,indent=2))
