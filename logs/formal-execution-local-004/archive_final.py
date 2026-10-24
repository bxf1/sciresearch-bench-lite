"""Seal the authorized local execution, preserving invalid and historical evidence."""
import base64
import json
import os
from pathlib import Path
import runpy
import subprocess
from runner.common import read_json, write_json, file_hash
from runner.study import frozen_plan

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
helpers=runpy.run_path(str(ROOT/'logs/formal-freeze-local-003/archive.py'))
collect,archive=helpers['collect'],helpers['archive']
plan,_=frozen_plan(ROOT,ROOT/'freezes/research-run-plan-formal-003.json')
ledger=ROOT/'research-runs'/plan['plan_id']/'manifest.json'
audit=read_json(OUT/'final-audit-001.json')
assert file_hash(ledger)==audit['manifest_sha256'] and audit['all_planned_operations_attempted']
assert not subprocess.check_output(['docker','ps','-q'],text=True).strip()
secret=os.environ.get('ANTHROPIC_AUTH_TOKEN','');assert secret
needles={secret.encode(),base64.b64encode(secret.encode()),json.dumps(secret)[1:-1].encode()}
for top in (ROOT/'build',ROOT/'research-runs'):
    if top.exists():
        for p in top.rglob('admission.json'):
            value=read_json(p)
            token=value.get('token')
            if isinstance(token,str) and token:needles.add(token.encode())
roots=[OUT,ROOT/'results/formal-study-003',*(ROOT/'research-runs').glob(plan['plan_id']+'*'),
       ROOT/'docs',ROOT/'freezes',ROOT/'runner',ROOT/'judge',ROOT/'baselines',ROOT/'public',ROOT/'prompts',ROOT/'tasks',ROOT/'tests',ROOT/'environment',
       ROOT/'logs/formal-freeze-local-003',ROOT/'logs/resource-acceptance-local-002',ROOT/'logs/t3-formal-calibration-local-005']
paths=collect(roots,exclude={'proposed-source'})
paths|=collect([ROOT/'authoring'],exclude={'data'})
for name in ('README.md','pyproject.toml','reproduce.sh','.gitignore'):
    if (ROOT/name).is_file():paths.add(ROOT/name)
assert not any(p.is_relative_to(ROOT/'authoring/data') for p in paths)
assert not any(p.name=='admission.json' for p in paths)
# Every retained registry evidence file is covered (bytecode caches are not candidate source).
for run in (ROOT/'research-runs').glob(plan['plan_id']+'*'):
    for p in run.rglob('*'):
        if p.is_file() and not p.is_symlink() and 'registry' in p.relative_to(run).parts and '__pycache__' not in p.parts:
            assert p in paths,p
snap=ROOT/'logs/formal-freeze-local-003/source-snapshot'
for relative,digest in read_json(ROOT/'logs/formal-freeze-local-003/source-snapshot-manifest.json')['files'].items():
    assert file_hash(snap/relative)==digest and snap/relative in paths
historical=[]
for name in ('formal-freeze-delivery-local-001','formal-execution-delivery-local-001','formal-freeze-delivery-local-002','formal-execution-delivery-local-003','formal-freeze-delivery-local-003','formal-execution-delivery-local-004'):
    p=ROOT/'logs'/name/'evidence.tar.gz'
    assert p.is_file()
    integrity=read_json(p.parent/'integrity.json');digest=file_hash(p)
    if name == 'formal-freeze-delivery-local-001':
        legacy = integrity['archive']
        assert legacy['path'] == p.relative_to(ROOT).as_posix()
        assert legacy['sha256'] == digest and legacy['bytes'] == p.stat().st_size
    else:
        assert integrity['archive_sha256'] == digest
    historical.append({'path':p.relative_to(ROOT).as_posix(),'sha256':digest})
status=subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)
(OUT/'git-status-final.txt').write_text(status)
paths.add(OUT/'git-status-final.txt')
pre=OUT/'archive-preflight-001.json';assert not pre.exists()
write_json(pre,{'status':'passed','plan_sha256':file_hash(ROOT/'freezes/research-run-plan-formal-003.json'),'manifest_sha256':file_hash(ledger),'source_snapshot_files_verified':213,'retained_registry_files_included':True,'no_running_containers':True,'historical_archives_verified':historical,'scope':'Current source, frozen source snapshot, current-plan raw evidence and candidates, resource/calibration acceptance, final tables, operational scripts and documents. Private numeric data, setup build directories, bytecode caches, dependencies and Docker images are excluded. Prior archives remain separate and hash-bound; no publication.'})
paths.add(pre)
dest=ROOT/'logs/formal-execution-delivery-local-005'
receipt,files=archive(dest,paths,needles)
write_json(dest/'delivery.json',{'status':'closed_with_invalid_performance_measurement','all_planned_operations_attempted':True,'full_valid_scientific_acceptance':False,'valid_research_sessions':15,'valid_scientific_sessions':14,'invalid_measurement_run_ids':audit['invalid_measurement_run_ids'],'archive':receipt,'files':len(files),'plan_sha256':file_hash(ROOT/'freezes/research-run-plan-formal-003.json'),'manifest_sha256':file_hash(ledger),'audit':{'path':(OUT/'final-audit-001.json').relative_to(ROOT).as_posix(),'sha256':file_hash(OUT/'final-audit-001.json')},'report':{'path':'results/formal-study-003/summary.json','sha256':file_hash(ROOT/'results/formal-study-003/summary.json')},'historical_archives':historical,'private_numeric_arrays':'Retained locally in authoring/data/v0.3-local and bound by task freezes; excluded from archive.','publication':'local_only','user_reduced_retry_policy_respected':True})
print(json.dumps({'archive':receipt,'files':len(files),'integrity':read_json(dest/'integrity.json')}))
