"""Archive the new freeze and sealed predecessor attempts locally."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tarfile
from runner.common import file_hash, read_json, write_json

ROOT=Path(__file__).resolve().parents[2]

def collect(roots, exclude=()):
    paths=set()
    for root in roots:
        for p in root.rglob('*'):
            rel=p.relative_to(root)
            if p.is_file() and not p.is_symlink() and not set(rel.parts).intersection({'__pycache__','.pytest_cache','build',*exclude}):
                assert p.name!='admission.json',p
                paths.add(p)
    return paths

def archive(out, paths, needles):
    out.mkdir(exist_ok=False)
    files={}
    for p in sorted(paths):
        data=p.read_bytes()
        assert not any(n in data for n in needles),p.relative_to(ROOT).as_posix()
        files[p.relative_to(ROOT).as_posix()]=hashlib.sha256(data).hexdigest()
    write_json(out/'file-manifest.json',files)
    path=out/'evidence.tar.gz'
    with tarfile.open(path,'w:gz') as tar:
        for p in sorted(paths):tar.add(p,arcname=p.relative_to(ROOT).as_posix(),recursive=False)
    with tarfile.open(path,'r:gz') as tar:
        members=tar.getmembers();assert len(members)==len(files)
        for m in members:
            assert m.isfile() and hashlib.sha256(tar.extractfile(m).read()).hexdigest()==files[m.name]
    receipt={'status':'verified','archive_sha256':file_hash(path),'archive_bytes':path.stat().st_size,
        'files':len(files),'member_content_hashes_verified':True,'private_credentials_scan':'clean','publication':'local_only'}
    write_json(out/'integrity.json',receipt)
    return {'path':path.relative_to(ROOT).as_posix(),'sha256':file_hash(path)},files

def main():
    key=os.environ.get('ANTHROPIC_AUTH_TOKEN','');assert key
    needles={key.encode(),base64.b64encode(key.encode()),json.dumps(key)[1:-1].encode()}
    for p in (ROOT/'build').glob('*/admission.json'):
        token=read_json(p).get('token')
        if token:needles.add(token.encode())
    old=read_json(ROOT/'freezes/research-run-plan-formal-002.json')
    closed=read_json(ROOT/'logs/formal-freeze-local-003/predecessor-closed.json')
    assert closed['status']=='closed_for_budget_revision'
    assert file_hash(ROOT/closed['ledger']['path'])==closed['ledger']['sha256']
    oldpaths=collect([*(ROOT/'research-runs').glob(old['plan_id']+'*'),ROOT/'logs/formal-execution-local-003'])
    oldarchive,_=archive(ROOT/'logs/formal-execution-delivery-local-003',oldpaths,needles)
    paths=collect([ROOT/'logs/formal-freeze-local-003'],exclude={'proposed-source'})
    for name in ('research-run-plan','heat','ode','poisson'):
        paths.add(ROOT/f'freezes/{name}-formal-003.json')
    files={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(paths)}
    receipt=ROOT/'freezes/formal-freeze-local-003.json';assert not receipt.exists()
    previous=ROOT/'logs/formal-freeze-delivery-local-002/evidence.tar.gz'
    write_json(receipt,{'status':'frozen','formal_ready':True,'plan':'freezes/research-run-plan-formal-003.json',
        'plan_sha256':file_hash(ROOT/'freezes/research-run-plan-formal-003.json'),'files':files,
        'predecessor_archive':{'path':previous.relative_to(ROOT).as_posix(),'sha256':file_hash(previous)},
        'predecessor_attempts_archive':oldarchive,
        'private_numeric_arrays':'Retained locally in authoring/data/v0.3-local and bound by task freezes.'})
    paths.add(receipt)
    newarchive,_=archive(ROOT/'logs/formal-freeze-delivery-local-003',paths,needles)
    print(json.dumps({'new_freeze':newarchive,'predecessor_attempts':oldarchive}))

if __name__=='__main__':main()
