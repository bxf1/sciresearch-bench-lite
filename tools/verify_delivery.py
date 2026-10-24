"""Audit a fresh clone without model calls, Docker, private data, or third-party packages."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--author-archive', type=Path, help='Optionally verify the separately downloaded author-data archive.')
    args = parser.parse_args()
    manifest = read(ROOT / 'delivery-manifest.json')
    for row in manifest['files']:
        path = (ROOT / row['path']).resolve()
        assert path.is_relative_to(ROOT) and path.is_file(), row['path']
        assert digest(path) == row['sha256'], 'Hash mismatch: ' + row['path']
    data = rows(ROOT / 'data/case-index.csv')
    assert len(data) == 90 and len({r['case_id'] for r in data}) == 90
    for task in ('heat', 'ode', 'poisson'):
        for split, count in (('public-dev', 6), ('author-calibration', 12), ('final-test', 12)):
            group = [r for r in data if r['task'] == task and r['split'] == split]
            assert len(group) == count and all(r['qc_passed'] == 'True' for r in group)
            assert all(sum(r['level'] == str(level) for r in group) == count // 3 for level in range(3))
        public = read(ROOT / f'tasks/{task}/environment/public-dev/manifest.json')
        assert {r['id'] for r in public['cases']} == {r['case_id'] for r in data if r['task'] == task and r['split'] == 'public-dev'}
    dataset = read(ROOT / 'data/file-manifest.json')
    expected = {r['path']: r for r in dataset['files']}
    for row in data:
        if not row['public_repo_path']:
            continue
        path = ROOT / row['public_repo_path']
        for file in path.iterdir():
            ref = expected[row['archive_input_path'] + '/' + file.name]
            assert file.is_file() and digest(file) == ref['sha256'], str(file)
    checkpoints = rows(ROOT / 'results/formal-study-003/checkpoints.csv')
    final = [r for r in checkpoints if r['checkpoint_role'] == 'final']
    assert len(final) == 15 and sum(r['evaluation_status'] == 'valid' for r in final) == 14
    assert sum(r['reward'] == '1' for r in final) == 6
    assert len(rows(ROOT / 'results/formal-study-003/baselines.csv')) == 11
    evidence = read(ROOT / 'results/delivery-analysis/evidence-excerpts.json')
    for row in evidence:
        assert digest(ROOT / row['source']) == row['source_sha256']
    archive_verified = False
    if args.author_archive:
        assert digest(args.author_archive) == dataset['archive_sha256'], 'Author archive checksum mismatch'
        with tarfile.open(args.author_archive) as tar:
            members = tar.getmembers()
            assert len(members) == len(expected) and {m.name for m in members} == set(expected)
            for member in members:
                assert member.isfile()
                value = tar.extractfile(member).read(); ref = expected[member.name]
                assert len(value) == ref['bytes'] and hashlib.sha256(value).hexdigest() == ref['sha256'], member.name
        archive_verified = True
    print(json.dumps({'status': 'passed', 'verified_files': len(manifest['files']), 'indexed_instances': 90,
                      'public_instances_in_clone': 18, 'author_baseline_methods': 11, 'formal_sessions': 15,
                      'valid_scores': 14, 'reward_one': 6, 'author_archive_verified': archive_verified,
                      'new_model_calls': 0, 'new_candidate_executions': 0,
                      'scope': 'Delivery consistency and integrity audit; not a new scientific replay.'}, indent=2))


if __name__ == '__main__':
    main()
