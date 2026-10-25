"""Scan and stage the authorized independent timing recheck, preserving history."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
selected = set()
for folder in ('logs/poisson-timing-recheck-2026-10-25', 'results/poisson-timing-recheck-2026-10-25'):
    for path in (ROOT / folder).rglob('*'):
        if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts:
            assert path.name not in ('admission.json', 'auth.json', '.env') and path.suffix != '.env'
            selected.add(path.relative_to(ROOT).as_posix())
selected.update(['README.md', 'docs/thinking-control-2026-10-25.md', 'docs/submission-report-2026-10-24.md',
                 'docs/poisson-timing-recheck-2026-10-25.md', 'docs/reproduction.md',
                 'tools/analyze_poisson_timing_recheck.py', 'tools/verify_delivery.py', 'tools/build_delivery_manifest.py'])
review = json.loads((ROOT / 'results/poisson-timing-recheck-2026-10-25/reviewed-results.json').read_text())
selected.update(review['source_sha256'])
tracked = set(filter(None, subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')))
secrets = {v.encode() for k, v in os.environ.items() if len(v) > 15 and any(x in k.upper() for x in ('TOKEN', 'API_KEY', 'SECRET', 'PASSWORD'))}
for path in (ROOT / 'build').glob('relay-*/admission.json'):
    value = json.loads(path.read_text()).get('token')
    if value:
        secrets.add(value.encode())
needles = secrets | {base64.b64encode(v) for v in secrets}
patterns = [rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', rb'gh[pousr]_[A-Za-z0-9]{36,}',
            rb'github_pat_[A-Za-z0-9_]{50,}', rb'sk-[A-Za-z0-9_-]{32,}', rb'AKIA[A-Z0-9]{16}']
size = 0
for name in sorted(selected | tracked):
    data = (ROOT / name).read_bytes()
    size += len(data)
    assert not any(v in data for v in needles), ('known credential', name)
    assert not any(re.search(pattern, data) for pattern in patterns), ('credential-shaped string', name)
stage = sorted(n for n in selected if (ROOT / n).suffix not in ('.npy', '.npz', '.gz', '.zip') and (ROOT / n).stat().st_size < 8 * 1024**2)
subprocess.run(['git', 'add', '-u'], cwd=ROOT, check=True)
subprocess.run(['git', 'add', '-f', '--pathspec-from-file=-', '--pathspec-file-nul'], cwd=ROOT,
               input=b'\0'.join(n.encode() for n in stage) + b'\0', check=True)
subprocess.run([str(ROOT / '.venv/bin/python'), 'tools/build_delivery_manifest.py'], cwd=ROOT, check=True)
selected.add('delivery-manifest.json')
subprocess.run(['git', 'add', 'delivery-manifest.json'], cwd=ROOT, check=True)
rows = [{'path': n, 'bytes': (ROOT / n).stat().st_size, 'sha256': hashlib.sha256((ROOT / n).read_bytes()).hexdigest()} for n in sorted(selected)]
(OUT / 'selected-evidence.json').write_text(json.dumps({'files': rows}, indent=2) + '\n')
receipt = {'status': 'passed', 'files_scanned': len(selected | tracked), 'bytes_scanned': size,
           'archive_files': len(rows), 'archive_source_bytes': sum(r['bytes'] for r in rows),
           'known_credential_matches': 0, 'credential_pattern_matches': 0, 'staged_evidence_files': len(stage)}
(OUT / 'publication-scan.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
