from pathlib import Path
import csv, hashlib, json, subprocess, sys, tarfile, tempfile
root=Path.cwd()
out=root/'logs/submission-delivery-2026-10-24'
commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
archive=out/'submission-ready-20261024.tar.gz'
assert not archive.exists(), 'Do not overwrite an existing evidence archive'
subprocess.run(['git','archive','--format=tar.gz','--prefix=sciresearch-bench-lite/','-o',str(archive),commit],check=True)
rows=[]
with tarfile.open(archive) as tar:
 assert tar.pax_headers.get('comment') == commit
 for member in tar.getmembers():
  if member.isdir(): continue
  assert member.isfile() and member.name.startswith('sciresearch-bench-lite/')
  data=tar.extractfile(member).read()
  local=root/Path(member.name).relative_to('sciresearch-bench-lite')
  assert data==local.read_bytes(),member.name
  rows.append({'path':member.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
 with tempfile.TemporaryDirectory(prefix='sciresearch-delivery-audit-') as temporary:
  tar.extractall(temporary,filter='data')
  fresh=Path(temporary)/'sciresearch-bench-lite'
  assert not (fresh/'.git').exists() and not (fresh/'.venv').exists()
  command=[sys.executable,'-I',str(fresh/'tools/verify_delivery.py'),'--author-archive',str(out/'author-data-v0.3.tar.gz')]
  result=subprocess.run(command,cwd=fresh,capture_output=True,text=True,check=True)
  audit=json.loads(result.stdout)
  with (fresh/'data/case-index.csv').open() as stream:
   case=next(csv.DictReader(stream))
  probe=next((fresh/case['public_repo_path']).glob('observations.csv'))
  original=probe.read_bytes()
  probe.write_bytes(original+b'\n# intentional integrity probe\n')
  failed=subprocess.run(command,cwd=fresh,capture_output=True,text=True)
  assert failed.returncode!=0 and 'Hash mismatch:' in failed.stderr
  probe.write_bytes(original)
audit.update({'source_commit':commit,'extracted_git_archive':True,'isolated_python_mode':True,
              'uses_same_host_interpreter':True,'no_git_or_venv_in_copy':True,
              'intentional_public_input_corruption_rejected':True,'corruption_probe_returncode':failed.returncode})
(out/'submission-ready-clean-copy-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
manifest={'source_commit':commit,'files':rows}
(out/'submission-ready-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
integrity={'archive':archive.name,'source_commit':commit,'bytes':archive.stat().st_size,
           'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(rows),
           'members_verified_against_committed_worktree':True,'clean_copy_audit':'passed',
           'scope':'Complete tracked source, public task data, reports, results and retained logs. Full author data and original large trajectories remain separate unchanged Release assets.'}
(out/'submission-ready-integrity.json').write_text(json.dumps(integrity,indent=2)+'\n')
print(json.dumps(integrity));print(json.dumps(audit))
