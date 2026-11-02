"""Index local evidence without copying or publishing any artifact."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/optimized-r1-20261101'
LOG = ROOT / 'logs/optimized-r1-20261101'


def read(path):
    return json.loads(path.read_text())


def main():
    assert read(OUT / 'pdf-visual-review.json')['status'] == 'passed'
    selected = set()
    def add(path):
        path = path.resolve(strict=True)
        if path.is_relative_to(ROOT) and path.is_file():
            relative = path.relative_to(ROOT)
            if any(part.startswith('.') for part in relative.parts):
                return
            if path.name in ('auth.json', 'credentials.json', 'admission.json', 'models.json', 'api_key', 'api-key'):
                return
            selected.add(path)
    def tree(path):
        for file in path.rglob('*'):
            if file.is_file() and not file.is_symlink() and not any(part in ('__pycache__', '.pytest_cache', 'matplotlib-cache') for part in file.parts):
                add(file)
    def refs(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value and isinstance(value['path'], str):
                p = ROOT / value['path']
                if p.is_file() and p.resolve().is_relative_to(ROOT):
                    add(p)
            for item in value.values():
                refs(item)
        elif isinstance(value, list):
            for item in value:
                refs(item)
    plan_path = ROOT / 'freezes/research-run-plan-optimized-r1-20261101.json'
    plan = read(plan_path); add(plan_path); refs(plan)
    for folder in ('runner', 'judge', 'public', 'prompts', 'tests', 'baselines', 'tools', 'environment', 'tasks'):
        tree(ROOT / folder)
    for path in (ROOT / 'authoring').glob('*.py'):
        add(path)
    tree(ROOT / 'authoring/data/optimized-r1-20261101')
    tree(OUT)
    tree(ROOT / 'research-runs' / plan['plan_id'])
    for run in plan['runs']:
        root = ROOT / 'research-runs' / run['run_id']
        for folder in ('registry', 'auxiliary-agent', 'file-bridge', 'relay-evidence/evidence'):
            tree(root / folder)
        for name in ('result.json', 'host-events.jsonl', 'host-termination.json', 'record-retention.json',
                     'controller-snapshot-manifest.json', 'research-containers.json'):
            add(root / name)
    for folder in ('resource-acceptance', 'main-calibration', 'diagnostic-calibration', 'timing-calibration', 'source-snapshot'):
        tree(LOG / folder)
    for file in LOG.glob('*.json'):
        add(file)
    for name in ('README.md', 'docs/reproduction.md', 'docs/optimized-r1-reproduction-20261101.md',
                 'docs/optimized-r1-report-20261101.md', 'docs/optimized-r1-report-20261101.html',
                 'output/pdf/sciresearch-optimized-r1-report-20261101.pdf',
                 'archives/pre-optimized-r1-20261101/preserved-reports.json'):
        add(ROOT / name)
    tree(ROOT / 'docs/figures/optimized-r1-20261101')
    # Follow recorded evidence references recursively; do not traverse credential
    # workspaces, dependency caches or the live relay admission/config directory.
    scanned = set()
    while True:
        pending = selected - scanned
        if not pending:
            break
        for path in pending:
            scanned.add(path)
            if path.suffix == '.json':
                try:
                    value = read(path)
                except (ValueError, UnicodeError):
                    continue  # Invalid-JSON test fixtures are still hashed.
                refs(value)
    for name in ('delivery-manifest.json', 'delivery-verification.json'):
        selected.discard((OUT / name).resolve())
    rows = []
    for path in sorted(selected):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        rows.append({'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
    value = {'scope': 'optimized_r1_nine_only', 'plan_id': plan['plan_id'], 'scientific_sessions': 9,
             'data_instances': 162, 'local_only': True, 'published': False,
             'coverage': 'Current implementation, complete 162-instance data/GT and diagnostic views, nine registered candidate stores and retained agent/relay evidence, main and diagnostic scoring artifacts, acceptance/calibration evidence, recursively referenced freeze files, report and page QA. Dependency caches and live authentication configuration excluded.',
             'files': rows, 'total_bytes': sum(r['bytes'] for r in rows)}
    (OUT / 'delivery-manifest.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'indexed', 'files': len(rows), 'bytes': value['total_bytes']}))


if __name__ == '__main__':
    main()
