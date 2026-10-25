"""Select and scan the authorized thinking-control evidence before staging/archiving."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
roots = sorted((ROOT / 'research-runs').glob('research-98719c3c1cf3fc92*'))
roots += [ROOT / 'logs/thinking-control-2026-10-25', ROOT / 'results/thinking-control-2026-10-25']
paths, excluded = set(), []
for directory in roots:
    for p in directory.rglob('*'):
        if not p.is_file():
            continue
        name = p.relative_to(ROOT).as_posix()
        if p.is_symlink() or any(x in p.parts for x in ('__pycache__', '.git', '.venv', 'node_modules')) or p.suffix == '.pyc':
            excluded.append({'path': name, 'reason': 'dependency/cache/symlink'})
            continue
        if p.name in ('admission.json', 'auth.json', '.env') or p.suffix == '.env':
            excluded.append({'path': name, 'reason': 'private credential file'})
            continue
        paths.add(name)
paths.update(['README.md', 'docs/thinking-control-2026-10-25.md',
              'docs/submission-report-2026-10-24.md', 'docs/reproduction.md',
              'tools/analyze_thinking_control.py', 'tools/verify_delivery.py', 'tools/build_delivery_manifest.py'])
paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'freezes').glob('*thinking*2026-10-25*'))
paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'freezes').glob('research-98719c3c1cf3fc92*'))
paths.update(filter(None, subprocess.check_output(
    ['git', 'diff', '--name-only', '3fb25c325db838ab56f06c592ed55ca8b4d51380', 'HEAD'],
    cwd=ROOT).decode().splitlines()))
# Include every directly referenced analysis source, including unchanged old-batch JSON.
review = json.loads((ROOT / 'results/thinking-control-2026-10-25/reviewed-comparison.json').read_text())
paths.update(review['source_sha256'])

secrets = {v.encode() for k, v in os.environ.items()
           if any(word in k.upper() for word in ('TOKEN', 'API_KEY', 'PASSWORD', 'SECRET')) and len(v) > 15}
for p in (ROOT / 'build').glob('relay-*/admission.json'):
    value = json.loads(p.read_text()).get('token')
    if value:
        secrets.add(value.encode())
needles = secrets | {base64.b64encode(v) for v in secrets}
patterns = [rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
            rb'gh[pousr]_[A-Za-z0-9]{36,}', rb'github_pat_[A-Za-z0-9_]{50,}',
            rb'sk-[A-Za-z0-9_-]{32,}', rb'AKIA[A-Z0-9]{16}']
tracked = set(filter(None, subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')))
failures, total = [], 0
for name in sorted(paths | tracked):
    p = ROOT / name
    data = p.read_bytes()
    total += len(data)
    if any(needle in data for needle in needles):
        failures.append({'path': name, 'reason': 'known credential match'})
    if any(re.search(pattern, data) for pattern in patterns):
        failures.append({'path': name, 'reason': 'credential-shaped string'})
    if p.name in ('admission.json', 'auth.json', '.env') or p.suffix == '.env' or name.startswith('build/'):
        failures.append({'path': name, 'reason': 'private runtime path'})
assert not failures, failures
rows = [{'path': name, 'bytes': (ROOT / name).stat().st_size,
         'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest()} for name in sorted(paths)]
(OUT / 'selected-evidence.json').write_text(json.dumps({'files': rows, 'excluded': excluded}, indent=2) + '\n')
# Full numerical outputs and larger trajectories are in the Release evidence archive.
stage = [r['path'] for r in rows if (ROOT / r['path']).suffix not in ('.npy', '.npz', '.gz', '.zip')
         and r['bytes'] <= 8 * 1024**2]
stage = sorted(set(stage) | set(review['source_sha256']))
subprocess.run(['git', 'add', '-u'], cwd=ROOT, check=True)
subprocess.run(['git', 'add', '-f', '--pathspec-from-file=-', '--pathspec-file-nul'], cwd=ROOT,
               input=b'\0'.join(n.encode() for n in stage) + b'\0', check=True)
receipt = {'status': 'passed', 'files_scanned': len(paths | tracked), 'bytes_scanned': total,
           'known_credential_matches': 0, 'credential_pattern_matches': 0,
           'private_runtime_paths': 0, 'archive_files_selected': len(rows),
           'archive_input_bytes': sum(r['bytes'] for r in rows), 'selected_files_staged': len(stage),
           'excluded': excluded, 'new_model_calls': 0, 'new_candidate_executions': 0}
(OUT / 'publication-scan.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({k: v for k, v in receipt.items() if k != 'excluded'}))
