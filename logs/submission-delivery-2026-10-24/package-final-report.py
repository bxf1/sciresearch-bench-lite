"""Package the final report and retained cancellation evidence; scan before publish."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tarfile

ROOT = Path.cwd()
OUT = ROOT / 'logs/submission-delivery-2026-10-24'
files = {ROOT / 'README.md'}
files.update((ROOT / 'docs').glob('*.md'))
files.update((ROOT / '.archify').glob('*/*.html'))
files.update((ROOT / 'results/formal-study-003').glob('*'))
files.update((ROOT / 'results/submission-2026-10-24').glob('*'))
files.update((ROOT / 'freezes').glob('supplemental-500k-2026-10-24*.json'))
files.add(ROOT / 'freezes/research-run-plan-formal-003.json')
for name in ('user-stop-request.json', 'user-stop-confirmation.json', 'repetition-audit-final.json',
             'finalize_cancelled.py', 'recovery-003-state.json'):
    files.add(ROOT / 'logs/supplemental-2026-10-24' / name)
run = ROOT / 'research-runs/supplemental-500k-2026-10-24-poisson-g3-r1-retry-003'
files.update(p for p in run.rglob('*') if p.is_file() and 'build' not in p.relative_to(run).parts)
files.add(ROOT / 'research-runs/supplemental-500k-2026-10-24-recovery-003/manifest.json')
secrets = {os.environ.get(k, '') for k in ('ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY')}
for p in (ROOT / 'build').glob('relay-*/admission.json'):
    secrets.add(json.loads(p.read_text()).get('token', ''))
needles = [variant for s in secrets if s for variant in (s.encode(), base64.b64encode(s.encode()))]
rows = []
for path in sorted(files):
    assert path.is_file() and not path.is_symlink()
    data = path.read_bytes()
    assert not any(n in data for n in needles), 'Credential found in ' + str(path.relative_to(ROOT))
    rows.append({'path': path.relative_to(ROOT).as_posix(), 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
archive = OUT / 'final-report-20261024.tar.gz'
assert not archive.exists()
with tarfile.open(archive, 'w:gz') as tar:
    for row in rows:
        tar.add(ROOT / row['path'], arcname=row['path'], recursive=False)
with tarfile.open(archive) as tar:
    members = {m.name: m for m in tar.getmembers()}
    assert set(members) == {r['path'] for r in rows}
    for row in rows:
        data = tar.extractfile(members[row['path']]).read()
        assert len(data) == row['size'] and hashlib.sha256(data).hexdigest() == row['sha256']
(OUT / 'final-report-manifest.json').write_text(json.dumps({'files': rows}, indent=2) + '\n')
integrity = {'archive': archive.name, 'bytes': archive.stat().st_size,
             'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': len(rows),
             'known_credential_matches': 0, 'archive_members_verified': True,
             'scope': 'Final reports, formal result tables, and user-cancelled supplemental evidence. Original full formal archive and author-data assets remain separate and unchanged.'}
(OUT / 'final-report-integrity.json').write_text(json.dumps(integrity, indent=2) + '\n')
print(json.dumps(integrity))
