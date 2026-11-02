"""Hash tracked deliverables and declared report supplement files; exclude receipts."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = ('delivery-manifest.json', 'logs/submission-delivery-2026-10-24/',
            'logs/thinking-delivery-2026-10-25/', 'logs/poisson-timing-delivery-2026-10-25/',
            'logs/final-report-delivery-2026-10-25/', 'logs/thinking-report-delivery-2026-10-25/', 'logs/thinking-r1-report-delivery-2026-10-25/', 'logs/thinking-r1-report-delivery-2026-10-29/',
            'logs/unified-r1-report-delivery-2026-10-29/', 'logs/ode-g1-rerun-report-delivery-2026-10-29/',
            'logs/final-report-delivery-2026-10-31/', 'logs/pdf-quality-delivery-2026-10-31/',
            'logs/second-edition-report-delivery-2026-11-01/')

SUPPLEMENT_PATHS = (
    'archives/pre-second-edition-report-20261101',
    'tools/build_second_edition_report.py', 'tools/audit_second_edition_report.py',
    'tools/templates/second-edition-report-20261101.md',
    'docs/second-edition-report-20261101.md', 'docs/second-edition-report-20261101.html',
    'results/second-edition-report-2026-11-01', 'docs/figures/second-edition-report-2026-11-01',
    'output/pdf/sciresearch-second-edition-report-20261101.pdf',
    'archives/pre-pdf-quality-20261031',
    'output/pdf/sciresearch-final-report-20261031-hq.pdf',
    'archives/pre-final-pdf-20261031',
    'tools/finalize_submission_report.py', 'tools/audit_final_submission_report.py',
    'results/final-report-2026-10-31', 'docs/figures/final-report-2026-10-31',
    'output/pdf/sciresearch-final-report-20261031.pdf',
    'archives/pre-ode-g1-rerun-20261029',
    'logs/ode-g1-r1-rerun-2026-10-29', 'results/ode-g1-r1-rerun-2026-10-29',
    'docs/ode-g1-r1-rerun-2026-10-29.md',
    'tools/build_ode_g1_rerun_report.py', 'tools/audit_ode_g1_rerun_report.py',
    'output/pdf/sciresearch-unified-r1-ode-rerun-report-20261029.pdf',
    'freezes/research-run-plan-ode-g1-template-2026-10-29.json',
    'freezes/heat-ode-g1-rerun-2026-10-29.json', 'freezes/ode-ode-g1-rerun-2026-10-29.json',
    'freezes/poisson-ode-g1-rerun-2026-10-29.json',
    'research-runs/research-de32855106df2081', 'research-runs/research-de32855106df2081-ode-g1-r1',
    'archives/pre-heat-unified-20261029',
    'docs/unified-r1-evidence-2026-10-29.md', 'docs/delivery-audit-unified-r1-2026-10-29.md',
    'docs/figures/unified-r1-nine-2026-10-29',
    'output/pdf/sciresearch-unified-r1-report-20261029.pdf',
    'results/unified-r1-nine-2026-10-29', 'logs/heat-unified-r1-2026-10-29', 'logs/unified-r1-nine-2026-10-29',
    'tools/build_unified_r1_report.py', 'tools/audit_unified_r1_report.py',
    'freezes/unified-nine-r1-suite-2026-10-29.json',
    'freezes/research-run-plan-unified-ode-poisson-r1-2026-10-29.json',
    'freezes/heat-unified-nine-r1-2026-10-29.json',
    'freezes/ode-unified-nine-r1-2026-10-29.json',
    'freezes/poisson-unified-nine-r1-2026-10-29.json',
    'research-runs/research-fcc3d4b300a336f8',
    'research-runs/research-fcc3d4b300a336f8-ode-g1-r1',
    'research-runs/research-fcc3d4b300a336f8-ode-g2-r1',
    'research-runs/research-fcc3d4b300a336f8-ode-g3-r1',
    'research-runs/research-fcc3d4b300a336f8-poisson-g1-r1',
    'research-runs/research-fcc3d4b300a336f8-poisson-g2-r1',
    'research-runs/research-fcc3d4b300a336f8-poisson-g3-r1',
    'freezes/research-run-plan-heat-unified-r1-2026-10-29.json',
    'freezes/heat-heat-unified-r1-2026-10-29.json',
    'freezes/ode-heat-unified-r1-2026-10-29.json',
    'freezes/poisson-heat-unified-r1-2026-10-29.json',
    'research-runs/research-a1eac24f70df21fd',
    'research-runs/research-a1eac24f70df21fd-heat-g1-r1',
    'research-runs/research-a1eac24f70df21fd-heat-g2-r1',
    'research-runs/research-a1eac24f70df21fd-heat-g3-r1',
    'archives/pre-g2-report-update-20261029',
    'docs/poisson-g2-timing-recheck-2026-10-28.md', 'docs/poisson-g2-timing-recheck-2026-10-29.md',
    'docs/thinking-report-evidence-2026-10-29.md', 'docs/delivery-audit-thinking-r1-2026-10-29.md',
    'docs/figures/thinking-r1-report-2026-10-29', 'output/pdf/sciresearch-thinking-r1-report-20261029.pdf',
    'results/poisson-g2-timing-recheck-2026-10-28', 'results/poisson-g2-timing-recheck-2026-10-29',
    'results/thinking-r1-report-2026-10-29',
    'logs/poisson-g2-timing-recheck-2026-10-28', 'logs/poisson-g2-timing-recheck-2026-10-29',
)


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    names = set(filter(None, names))
    for name in SUPPLEMENT_PATHS:
        path = ROOT / name
        if not path.exists():
            raise ValueError('Missing declared supplement: ' + name)
        paths = [path] if path.is_file() else path.rglob('*')
        names.update(p.relative_to(ROOT).as_posix() for p in paths
                     if p.is_file() and '__pycache__' not in p.parts)
    rows = []
    for name in sorted(filter(None, names)):
        if name == EXCLUDED[0] or name.startswith(EXCLUDED[1:]):
            continue
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Expected a regular file: ' + name)
        value = path.read_bytes()
        rows.append({'path': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()})
    manifest = {'schema_version': 1, 'scope': 'Tracked deliverables, preserved experiment evidence and the 2026-11-01 second-edition-only report.',
                'supplement_paths': list(SUPPLEMENT_PATHS),
                'exclusions': list(EXCLUDED),
                'exclusion_reason': 'The manifest cannot hash itself; publication receipts are recorded after packaging.',
                'files': rows}
    (ROOT / 'delivery-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'files': len(rows), 'bytes': sum(r['bytes'] for r in rows)}))


if __name__ == '__main__':
    main()
