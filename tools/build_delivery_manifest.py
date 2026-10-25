"""Hash staged/tracked deliverable files; exclude the manifest and publication receipts."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = ('delivery-manifest.json', 'logs/submission-delivery-2026-10-24/',
            'logs/thinking-delivery-2026-10-25/', 'logs/poisson-timing-delivery-2026-10-25/',
            'logs/final-report-delivery-2026-10-25/', 'logs/thinking-report-delivery-2026-10-25/', 'logs/thinking-r1-report-delivery-2026-10-25/')


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    rows = []
    for name in sorted(filter(None, names)):
        if name == EXCLUDED[0] or name.startswith(EXCLUDED[1:]):
            continue
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Expected a regular file: ' + name)
        value = path.read_bytes()
        rows.append({'path': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()})
    manifest = {'schema_version': 1, 'scope': 'Tracked source, tasks, data indexes, reports and experimental evidence.',
                'exclusions': list(EXCLUDED),
                'exclusion_reason': 'The manifest cannot hash itself; publication receipts are recorded after packaging.',
                'files': rows}
    (ROOT / 'delivery-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'files': len(rows), 'bytes': sum(r['bytes'] for r in rows)}))


if __name__ == '__main__':
    main()
