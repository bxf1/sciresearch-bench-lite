"""Create and verify a separately named timing-recheck evidence archive."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
rows = json.loads((OUT / 'selected-evidence.json').read_text())['files']
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
archive = OUT / 'poisson-timing-recheck-20261025.tar.gz'
manifest = OUT / 'poisson-timing-recheck-manifest-20261025.json'
checksums = OUT / 'poisson-timing-recheck-SHA256SUMS-20261025.txt'
assert not any(p.exists() for p in (archive, manifest, checksums))
for row in rows:
    assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
with tarfile.open(archive, 'w:gz') as tar:
    for row in rows:
        tar.add(ROOT / row['path'], arcname='sciresearch-bench-lite/' + row['path'], recursive=False)
with tarfile.open(archive) as tar:
    members = tar.getmembers()
    assert len(members) == len(rows)
    for member, row in zip(members, rows):
        assert member.isfile() and member.name == 'sciresearch-bench-lite/' + row['path']
        data = tar.extractfile(member).read()
        assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
record = {'source_commit': commit, 'archive': archive.name, 'bytes': archive.stat().st_size,
          'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': rows,
          'archive_members_verified': True,
          'scope': 'Independent timing recheck: G1 valid, G2 invalid; all admission refusals and new W/J outputs preserved, with original parent evidence. No Agent reruns or model calls. Incremental archive for use with main.'}
manifest.write_text(json.dumps(record, indent=2) + '\n')
checksums.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (archive, manifest)))
print(json.dumps({k: v for k, v in record.items() if k != 'files'}))
