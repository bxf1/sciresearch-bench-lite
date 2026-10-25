"""Create a non-overwriting, hash-verified incremental evidence archive."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
selection = json.loads((OUT / 'selected-evidence.json').read_text())
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
archive = OUT / 'thinking-control-evidence-20261025.tar.gz'
manifest = OUT / 'thinking-control-manifest-20261025.json'
checksums = OUT / 'thinking-control-SHA256SUMS-20261025.txt'
assert not any(p.exists() for p in (archive, manifest, checksums)), 'Never overwrite a published or prepared archive'
with tarfile.open(archive, 'w:gz') as tar:
    for row in selection['files']:
        path = ROOT / row['path']
        assert not path.is_symlink() and path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'], row['path']
        tar.add(path, arcname='sciresearch-bench-lite/' + row['path'], recursive=False)
with tarfile.open(archive) as tar:
    members = tar.getmembers()
    assert len(members) == len(selection['files'])
    for member, row in zip(members, selection['files']):
        assert member.isfile() and member.name == 'sciresearch-bench-lite/' + row['path']
        data = tar.extractfile(member).read()
        assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
record = {'source_commit': commit, 'archive': archive.name, 'bytes': archive.stat().st_size,
          'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
          'scope': 'Incremental thinking/max source, reports, 17 attempts, independent scoring, full native traces, repair and rejected-window evidence. Use with main and retained author-data assets.',
          'excluded': selection['excluded'], 'files': selection['files'],
          'archive_members_verified': True}
manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
checksums.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (archive, manifest)))
print(json.dumps({k: v for k, v in record.items() if k not in ('excluded', 'files')}, ensure_ascii=False))
