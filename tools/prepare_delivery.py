"""Rebuild delivery tables and evidence excerpts from existing experiments only."""
import csv
import difflib
import hashlib
import json
import statistics
import tarfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / 'results/formal-study-003'
DATA = ROOT / 'authoring/data/v0.3-local'
OUT = ROOT / 'results/delivery-analysis'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def csv_read(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def csv_write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def inventory():
    cases, splits = [], []
    for task in ('heat', 'ode', 'poisson'):
        for split, expected in (('public-dev', 6), ('author-calibration', 12), ('final-test', 12)):
            manifest_path = DATA / 'inputs' / task / split / 'manifest.json'
            manifest = read(manifest_path)
            assert len(manifest['cases']) == expected
            counts = defaultdict(int)
            for case in manifest['cases']:
                qc_path = DATA / 'private' / task / split / case['path'] / 'qc.json'
                qc = read(qc_path); assert qc['passed'] is True
                counts[case['level']] += 1
                inputs = DATA / 'inputs' / task / split / case['path']
                files = sorted(p for p in inputs.iterdir() if p.is_file())
                cases.append({'task': task, 'split': split, 'level': case['level'], 'case_id': case['id'],
                              'input_files': len(files), 'input_bytes': sum(p.stat().st_size for p in files),
                              'qc_passed': True, 'qc_sha256': sha(qc_path),
                              'input_manifest_sha256': sha(manifest_path),
                              'public_repo_path': f"tasks/{task}/environment/public-dev/{case['path']}" if split == 'public-dev' else '',
                              'archive_input_path': f"author-data-v0.3/inputs/{task}/{split}/{case['path']}",
                              'archive_qc_path': f"author-data-v0.3/private/{task}/{split}/{case['path']}/qc.json"})
            assert set(counts) == {0, 1, 2} and all(n == expected // 3 for n in counts.values())
            splits.append({'task': task, 'split': split, 'instances': expected, 'levels': dict(counts), 'qc_passed': expected})
    csv_write(ROOT / 'data/case-index.csv', cases)
    write(ROOT / 'data/split-summary.json', {'instances': len(cases), 'source': 'mathematically generated synthetic data', 'splits': splits})
    archive = ROOT / 'logs/submission-delivery-2026-10-24/author-data-v0.3.tar.gz'
    members = []
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            assert member.isfile()
            data = tar.extractfile(member).read()
            local = DATA / Path(member.name).relative_to('author-data-v0.3')
            assert data == local.read_bytes()
            members.append({'path': member.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    write(ROOT / 'data/file-manifest.json', {'archive': archive.name, 'archive_bytes': archive.stat().st_size,
                                          'archive_sha256': sha(archive), 'files': members})


def analyze():
    checkpoints = csv_read(FORMAL / 'checkpoints.csv')
    by_run = defaultdict(dict)
    for row in checkpoints:
        by_run[row['run_id']][row['checkpoint_role']] = row
    rows = []
    for run_id, pair in by_run.items():
        first, final = pair['first'], pair['final']
        comparable = all(x['evaluation_status'] == 'valid' and x['checkpoint_id'] != 'null' for x in (first, final))
        delta = float(final['score']) - float(first['score']) if comparable else None
        rows.append({'run_id': run_id, 'task': final['task'], 'group': final['group'], 'repeat': final['repeat'],
                     'first_candidate': first['checkpoint_id'], 'final_candidate': final['checkpoint_id'],
                     'first_score': first['score'], 'final_score': final['score'], 'reward': final['reward'],
                     'evaluation_status': final['evaluation_status'], 'passed': final['passed'],
                     'first_final_comparable': comparable, 'delta_score': delta,
                     'iteration': 'unavailable' if delta is None else 'improved' if delta > 1e-9 else 'declined' if delta < -1e-9 else 'unchanged'})
    assert len(rows) == 15
    csv_write(OUT / 'run-summary.csv', rows)
    baseline = csv_read(FORMAL / 'baseline-cases.csv')
    groups = defaultdict(list)
    for row in baseline:
        groups[(row['task'], row['method'], row['level'])].append(row)
    difficulties = []
    for (task, method, level), group in sorted(groups.items()):
        unique = defaultdict(list)
        for row in group:
            unique[row['case_id']].append(row)
        assert len(unique) == 4 and all(len(v) == 3 for v in unique.values())
        passed = sum(all(r['scientific_pass'] == 'true' for r in repeats) for repeats in unique.values())
        score = None if task == 'poisson' else statistics.mean(statistics.median(float(r['score']) for r in repeats) for repeats in unique.values())
        difficulties.append({'task': task, 'method': method, 'level': level, 'unique_cases': 4,
                             'clean_replays_per_case': 3, 'cases_correct_in_all_replays': passed,
                             'mean_case_score': score,
                             'scope': 'Poisson case correctness excludes the full-batch efficiency gate' if task == 'poisson' else 'Median over repeats, mean over four unique cases'})
    csv_write(OUT / 'baseline-by-difficulty.csv', difficulties)
    counts = {key: sum(r['iteration'] == key for r in rows) for key in ('improved', 'declined', 'unchanged', 'unavailable')}
    assert counts == {'improved': 2, 'declined': 1, 'unchanged': 5, 'unavailable': 7}
    write(OUT / 'analysis-summary.json', {'formal_sessions': 15, 'valid_scores': sum(r['evaluation_status'] == 'valid' for r in rows),
                                       'reward_one': sum(r['reward'] == '1' for r in rows), 'iteration': counts,
                                       'inputs': [{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)} for p in (FORMAL / 'checkpoints.csv', FORMAL / 'baseline-cases.csv')],
                                       'new_model_calls': 0, 'new_candidate_executions': 0})


def evidence():
    excerpts = []
    def add(title, relative, value, selector):
        path = ROOT / relative
        excerpts.append({'title': title, 'source': relative, 'source_sha256': sha(path), 'selector': selector, 'excerpt': value})
    run = 'research-runs/research-6615cd7900ba0750-heat-g3-r1'
    events = [json.loads(line) for line in (ROOT / run / 'host-events.jsonl').read_text().splitlines()]
    add('Heat G3 r1：研究结束及可信候选登记', run + '/host-events.jsonl',
        [{k: e[k] for k in ('kind', 'time', 'fields')} for e in events if e['kind'] in ('research_stopped', 'registry_closed')],
        'kind=research_stopped|registry_closed; select kind,time,fields')
    replay = 'research-runs/research-6615cd7900ba0750/final-replays/research-6615cd7900ba0750-heat-g3-r1-a001/result.json'
    d = read(ROOT / replay)['diagnostics']
    add('Heat G3 r1：独立隐藏重放', replay,
        {key: {k: d[key][k] for k in ('checkpoint_id', 'source_hash', 'evaluation_status', 'replay_count', 'score', 'reward')} for key in ('first', 'final')},
        'diagnostics.first/final; select checkpoint_id,source_hash,evaluation_status,replay_count,score,reward')
    for candidate in ('candidate-017', 'candidate-018'):
        path = run + f'/registry/evaluations/{candidate}/public_feedback.json'
        r = read(ROOT / path)
        add(f'Heat G3 r1：{candidate} 公开反馈示例', path,
            {**{k: r[k] for k in ('artifact_valid', 'attempt_status', 'public_check_status', 'formal_timing')},
             'cases': [r['cases'][0]]},
            'select artifact_valid,attempt_status,public_check_status,formal_timing,cases[0]; other five cases omitted')
    first = run + '/registry/snapshots/candidate-017/solve.py'
    final = run + '/registry/snapshots/candidate-018/solve.py'
    diff = ''.join(difflib.unified_diff((ROOT / first).read_text().splitlines(keepends=True),
                                       (ROOT / final).read_text().splitlines(keepends=True), fromfile=first, tofile=final, n=0))
    (OUT / 'heat-g3-source.diff').write_text(diff)
    path = 'logs/resource-acceptance-local-002/summary.json'; r = read(ROOT / path)
    add('冻结资源验收', path, {k: r[k] for k in ('status', 'formal_resources_accepted', 'resources', 'model_calls', 'final_test_scores_accessed')}, 'select listed top-level fields')
    path = 'logs/formal-execution-local-004/window-final-poisson-research-6615cd7900ba0750-poisson-g2-r1/acceptance.json'; r = read(ROOT / path)
    add('Poisson G2：无效计时原始判定', path, {k: r[k] for k in ('status', 'evaluation_status', 'violations', 'observer_errors')}, 'select listed top-level fields')
    path = 'logs/formal-execution-local-004/final-audit-001.json'; r = read(ROOT / path)
    add('全部正式研究与评分审计', path, {k: r[k] for k in ('status', 'valid_research_sessions', 'valid_final_scientific_results', 'with_first_final', 'no_valid_submission', 'physical_worker_batches', 'physical_worker_case_executions', 'unattempted_operations')}, 'select listed top-level fields')
    write(OUT / 'evidence-excerpts.json', excerpts)
    text = '# 关键日志与证据链\n\n以下片段由 `tools/prepare_delivery.py` 从既有日志按注明字段提取，数值不改写；这是字段节选，不冒充完整原始日志。原文件路径与 SHA256 可逐项核对。完整轨迹见 Release 的原始证据包。\n\n'
    for e in excerpts:
        text += f"## {e['title']}\n\n来源：[{e['source']}](../{e['source']})。SHA256：`{e['source_sha256']}`。\n\n提取规则：`{e['selector']}`。\n\n```json\n{json.dumps(e['excerpt'], ensure_ascii=False, indent=2)}\n```\n\n"
    path = ROOT / 'logs/formal-freeze-local-003/unit-tests-final.txt'
    line = next(line for line in path.read_text().splitlines() if '357 passed' in line)
    text += f'## 冻结版本测试日志\n\n[原日志](../logs/formal-freeze-local-003/unit-tests-final.txt)，SHA256：`{sha(path)}`。以下为原日志末行；不是本次整理重新运行的测试。\n\n```text\n{line}\n```\n\n'
    text += '## 失败与未提交的追溯\n\n原正式批次的 [提交与重复调用诊断](submission-diagnosis-2026-10-23.md)覆盖接口导出失败、逐字循环、仅递增文件名和不同种子模拟；[取消补跑诊断](supplemental-results-2026-10-24.md)另列提前终止的会话，不进入正式分母。完整数据索引见 [data/README](../data/README.md)。\n'
    (ROOT / 'docs/evidence.md').write_text(text)


if __name__ == '__main__':
    inventory(); analyze(); evidence()
    print('Prepared 90-case inventory, 15-session analysis, 33 baseline difficulty rows and traceable log excerpts; no experiments run.')
