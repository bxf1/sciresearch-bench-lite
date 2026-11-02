"""Build a separate post-hoc ODE G1 supplement, preserving the original nine results."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
BATCH = Path('logs/ode-g1-r1-rerun-2026-10-29')
OUT = Path('results/ode-g1-r1-rerun-2026-10-29')
ARCHIVE = Path('archives/pre-ode-g1-rerun-20261029')
PDF = 'sciresearch-unified-r1-ode-rerun-report-20261029.pdf'

def read(path):
    return json.loads((ROOT / path).read_text())

def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()

def build_data():
    sources = {}
    def checked(ref):
        assert sha(ref['path']) == ref['sha256'], ref['path']
        sources[ref['path']] = ref['sha256']
        return read(ref['path'])
    def evidence(path):
        path = str(path)
        ref = {'path': path, 'sha256': sha(path)}
        checked(ref)
        return ref
    protocol_ref = evidence(BATCH / 'protocol.json')
    protocol = read(protocol_ref['path'])
    authorization = checked(protocol['authorization'])
    assert authorization['scientific_sessions'] == 1
    for ref in protocol['adapter_sources'].values():
        assert sha(ref['path']) == ref['sha256']
        sources[ref['path']] = ref['sha256']
    plan = checked(protocol['template'])
    old = checked(protocol['original_nine_results'])
    assert old['new_sessions'] == 9 and old['new_reward_one'] == 8
    old_row = next(r for r in old['rows'] if r['task'] == 'ode' and r['group'] == 'g1')
    assert old_row['final_score'] == 0 and old_row['status'] == 'research_timeout'
    for name, expected in plan['tool_config']['files'].items():
        assert sha(name) == expected
    row, = protocol['authorized_runs']
    assert row == plan['runs'][0] and (row['task'], row['group']) == ('ode', 'g1')
    assert protocol['dormant_template_run_ids'] == [r['run_id'] for r in plan['runs'][1:]]
    manifest_ref = evidence(Path('research-runs') / plan['plan_id'] / 'manifest.json')
    manifest = read(manifest_ref['path'])
    assert manifest['finalized_tasks'] == ['ode']
    assert manifest['single_session_protocol'] == protocol_ref
    assert manifest['dormant_template_run_ids'] == protocol['dormant_template_run_ids']
    assert 1 <= len(manifest['attempts']) <= 2
    assert {e['run_id'] for e in manifest['attempts']} == {row['run_id']}
    assert not any((ROOT / 'research-runs' / run_id).exists() for run_id in protocol['dormant_template_run_ids'])
    assert read(BATCH / 'state.json')['stage'] == 'results_ready_for_review'
    service = checked(evidence(BATCH / 'service-restoration.json'))
    assert service['restored'] and service['after']['health'] == 'healthy'
    archive = checked(protocol['pre_rerun_archive'])
    for name, expected in archive['files'].items():
        assert sha(ARCHIVE / name) == expected
        if name.startswith(('results/', 'output/pdf/')):
            assert sha(name) == expected, 'Original result or PDF changed'
    attempts = []
    for entry in manifest['attempts']:
        host = checked(entry['result'])
        reg = checked(entry['registry'])
        assert sha(entry['relay_events']['path']) == entry['relay_events']['sha256']
        sources[entry['relay_events']['path']] = entry['relay_events']['sha256']
        events = [json.loads(line) for line in (ROOT / entry['relay_events']['path']).read_text().splitlines()]
        requests = [e for e in events if e['event'] == 'request_accepted']
        finished = [e for e in events if e['event'] == 'request_finished']
        assert len(requests) == len(finished)
        assert host['relay_status']['limits'] == plan['runtime_policy']
        assert host['relay_status']['limits']['request_output_limit'] == 16384
        assert host['relay_status']['limits']['session_output_limit'] == 200000
        assert host['research_budget_seconds'] == 1800 and host['max_evaluations'] == 20
        assert host['native_setup_evidence']['installed_source_sha256'] == old['uniform_installed_sources']
        assert {k: v for k, v in host['trusted_source_sha256'].items() if not k.startswith('prompts/')} == old['uniform_trusted_sources']
        for name, expected in plan['tasks']['ode']['prompt_hashes'].items():
            if name in ('common.md', 'g1.md'):
                assert host['trusted_source_sha256']['prompts/ode/' + name] == expected
        assert all(0 < r['effective_max_tokens'] <= 16384 for r in requests)
        known = sum(e.get('output_tokens') or 0 for e in finished)
        charged = sum(e.get('charged_output_tokens') or 0 for e in finished)
        assert charged == host['relay_status']['charged_output_tokens']
        attempts.append({'attempt_id': entry['attempt_id'], 'parent_attempt': entry['parent_attempt'],
                         'status': host['attempt_status'], 'known_output_tokens': known,
                         'charged_output_tokens': charged,
                         'research_wall_seconds': reg['attempt_outcome']['recorded_at'] - reg['started_at'],
                         'public_evaluations': len(reg['evaluations']), 'requests': len(requests),
                         'request_outcomes': dict(Counter(e['outcome'] for e in finished)),
                         'compaction_requests': sum(e.get('request_kind') == 'native_compaction' for e in requests),
                         'one_token_requests': sum(e['effective_max_tokens'] == 1 for e in requests),
                         'responses_over_4096': sum((e.get('output_tokens') or 0) > 4096 for e in finished),
                         'max_request_limit': max(e['effective_max_tokens'] for e in requests),
                         'host_evidence': entry['result'], 'registry_evidence': entry['registry'],
                         'relay_evidence': entry['relay_events']})
    entry = manifest['attempts'][-1]
    host, reg = checked(entry['result']), checked(entry['registry'])
    assert host['attempt_status'] in ('completed', 'research_timeout')
    assert not host['cleanup_errors'] and not host['bridge_errors']
    assert host['relay_cleanup']['all_removed'] and host['worker_cleanup']['all_removed']
    assert not host['relay_status']['protocol_violation'] and not host['relay_status']['evidence_error']
    assert reg['closed'] and reg['attempt_outcome']['recorded_at'] < entry['replay_started_at']
    closure_ref = evidence(BATCH / 'research-closure.json')
    closure = read(closure_ref['path'])
    assert closure['all_authorized_sessions_closed'] and closure['dormant_sessions_launched'] == 0
    assert closure['closed_at'] <= entry['replay_started_at']
    raw = checked(entry['replay'])
    assert raw['protocol'] == protocol_ref and raw['scope'] == 'independent_single_session_supplement'
    assert raw['freeze_sha256'] == plan['freezes']['ode']['sha256']
    assert raw['registry_sha256'] == entry['registry']['sha256'] and raw['split'] == 'final-test'
    diagnostics = raw['diagnostics']
    assert diagnostics['evaluation_status'] == 'valid'
    observations_ref = evidence(BATCH / 'execution-observations.json')
    observations = read(observations_ref['path'])
    for path, expected in observations['source_sha256'].items():
        assert sha(path) == expected
        sources[path] = expected
    records = 0
    for role in ('first', 'final'):
        checkpoint = diagnostics[role]
        assert checkpoint['checkpoint_id'] == reg[role + '_id']
        if checkpoint.get('source_hash'):
            source = ROOT / Path(entry['registry']['path']).parent / 'snapshots' / checkpoint['checkpoint_id']
            tree = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.rglob('*')) if p.is_file()}
            assert hashlib.sha256(json.dumps(tree, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == checkpoint['source_hash']
        repeats = checkpoint.get('repeats', [])
        if not repeats:
            assert checkpoint['score'] == 0 and checkpoint['reward'] == 0
            continue
        assert len(repeats) == 3
        for repeat in repeats:
            assert repeat['evaluation_status'] == 'valid' and repeat['total'] == len(repeat['cases']) == 12
            for case in repeat['cases']:
                records += 1
                valid = case.get('artifact_valid') is not False and case.get('K') is not None and case['K'] <= 10 and case.get('E_roll') is not None and case.get('E_field') is not None
                clip = lambda x: max(0, min(1, x))
                score = 100 * (.5 * clip(1 - case['E_roll'] / .1) + .5 * clip(1 - case['E_field'] / .1)) if valid else 0
                passed = valid and case['E_roll'] <= .05 and case['E_field'] <= .05
                assert math.isclose(case['score'], score, abs_tol=1e-9) and case['scientific_pass'] == passed
            assert repeat['passed'] == sum(c['scientific_pass'] for c in repeat['cases'])
            assert math.isclose(repeat['score'], statistics.mean(c['score'] for c in repeat['cases']), abs_tol=1e-9)
        assert math.isclose(checkpoint['score'], statistics.mean(r['score'] for r in repeats), abs_tol=1e-9)
        assert checkpoint['reward'] == int(all(r['reward'] == 1 for r in repeats))
    return {'status': 'reviewed_terminal', 'kind': protocol['kind'], 'scientific_sessions': 1,
            'run_id': row['run_id'], 'attempt_id': entry['attempt_id'], 'attempts': attempts,
            'attempt_status': host['attempt_status'], 'first_id': reg['first_id'], 'final_id': reg['final_id'],
            'selection_reason': reg.get('selection_reason'),
            'first_score': diagnostics['first']['score'], 'final_score': diagnostics['final']['score'],
            'reward': diagnostics['final']['reward'], 'evaluation_status': diagnostics['evaluation_status'],
            'passed_per_replay': [r['passed'] for r in diagnostics['final'].get('repeats', [])],
            'raw_case_records_checked': records, 'retained_attempt': attempts[-1],
            'all_attempt_known_output_tokens': sum(a['known_output_tokens'] for a in attempts),
            'all_attempt_charged_output_tokens': sum(a['charged_output_tokens'] for a in attempts),
            'original_nine_sessions': 9, 'original_nine_reward_one': 8,
            'original_ode_g1': old_row, 'old_to_rerun_score_delta': diagnostics['final']['score'] - old_row['final_score'],
            'protocol': protocol_ref, 'score_evidence': entry['replay'], 'manifest': manifest_ref,
            'archive_files_verified': len(archive['files']), 'service_restored': True,
            'execution_observations': observations, 'execution_observations_evidence': observations_ref,
            'source_sha256': dict(sorted(sources.items()))}

def supplement(data):
    a = data['retained_attempt']
    passed = (' / '.join(str(n) for n in data['passed_per_replay']) + '（每次 12 例）') if data['passed_per_replay'] else '无候选，无重放'
    outcome = '成功' if data['reward'] == 1 else '未满足成功条件'
    scoring_note = ('最终分为三次重放的平均值，重放相同候选不增加研究样本数。'
                    if data['passed_per_replay'] else '本次未形成可重放的有效最终候选，按规则记 0 分，没有执行最终候选的隐藏重放。')
    first_id, final_id = data['first_id'] or '无', data['final_id'] or '无'
    long_call = data['execution_observations']['last_tool_call']
    return f'''## 13. ODE G1 r1 单组补跑（2026-10-29）

用户在原九组结果确认后，指定重新运行 ODE G1 r1。本节记录这一个新增独立研究会话；**原九组仍为 8/9 成功，M04 的 0 分和原始记录保留**。本次是失败结果已知后的事后补跑，不是基础设施重试，也不替换原主实验的分母。未新增 G2/G3 或 r2/r3 实验。

| 指标 | 原九组中的 ODE G1 r1 | 本次单组补跑 |
|---|---:|---:|
| 最终分数 | 0.000 | {data['final_score']:.3f} |
| reward | 0 | {data['reward']} |
| 首次候选分数 | 0.000（无候选） | {data['first_score']:.3f} |
| 研究结束状态 | research_timeout | {data['attempt_status']} |
| 公开评估次数 | 0 | {a['public_evaluations']} |
| 保留 attempt 研究分钟 | 30.02 | {a['research_wall_seconds']/60:.2f} |
| 保留 attempt 已知输出 token | 38,899 | {a['known_output_tokens']:,} |
| 最终候选三次隐藏重放通过数 | 无候选，无重放 | {passed} |

本次结局为**{outcome}**。首次/最终登记 ID 为 `{first_id}` / `{final_id}`；{scoring_note}原批次与补跑均完整保留，不能以补跑结果宣称原九组首次全部成功。

**这次仍未提交的过程证据：** Agent 在研究第 {long_call['started_after_seconds']/60:.2f} 分钟发起 `python3 lab_pipe1.py 10 2`，对自行生成的 10 个合成系统做候选搜索与非线性拟合，未为该 bash 调用设置独立 timeout。从发起到全局预算关闭间隔 {long_call['unreturned_interval_seconds']/60:.2f} 分钟，占研究墙钟约 {100*long_call['unreturned_interval_seconds']/long_call['research_wall_seconds']:.1f}%；原生轨迹没有该调用的返回记录。在此之前也没有登记任何公开评估。记录支持“内部实验占用剩余预算、未先登记候选”的解释；18 次模型请求均成功，未出现压缩或单 token 请求，不能把此次失败归为旧 4,096 截断。具体调用与时间戳见[补跑执行观察](../logs/ode-g1-r1-rerun-2026-10-29/execution-observations.json)。

配置核验确认：共享执行器和 Pi 安装源码、提示词、模型策略、数值镜像、数据与评分规则均与原九组一致；每会话仍为 30 分钟、20 次公开评估、200,000 输出 token，单请求上限 16,384，保留原生上下文压缩。研究 Agent 使用全新会话和工作区，没有收到上次候选、隐藏反馈或内部长测试诊断。

本次共 {len(data['attempts'])} 个 attempt，累计已知输出 {data['all_attempt_known_output_tokens']:,} token，charged 额度 {data['all_attempt_charged_output_tokens']:,}。保留 attempt 发出 {a['requests']} 个请求，{a['responses_over_4096']} 个响应输出超过 4,096 token；正常压缩请求 {a['compaction_requests']} 次，单 token 请求 {a['one_token_requests']} 次。{failure_text(data)}数据库已恢复到 healthy。

冻结执行器只接受完整三组的计划结构，因此另存了一个执行模板，并在启动前的单组协议中**仅授权第一个 ODE G1 条目**；模板中的 G2/G3 均未启动，也不计为实验。单组适配器验证唯一授权会话关闭后，调用未改动的 `guard_replay` / `score_checkpoints` 执行相同评分流程（有效候选重放三次），并永久关闭模板中的 ODE 研究入口。协议、适配器源码和评分均绑定哈希，原九组的研究关闭屏障与结果不受影响。

本次追加样本是在观察到失败后选出的，且重复使用既有隐藏集，只能说明这次新会话及其具体候选的表现；不能用于无偏估计一次运行成功率，也不能证明 G1 的稳定表现或指导方式的因果效应。

证据：[单组冻结协议](../logs/ode-g1-r1-rerun-2026-10-29/protocol.json)、[研究关闭记录](../logs/ode-g1-r1-rerun-2026-10-29/research-closure.json)、[本次结果与哈希](../results/ode-g1-r1-rerun-2026-10-29/reviewed-results.json)、[独立评分](../{data['score_evidence']['path']})、[服务恢复](../logs/ode-g1-r1-rerun-2026-10-29/service-restoration.json)、[补跑前报告快照](../archives/pre-ode-g1-rerun-20261029/docs/submission-report-2026-10-24.md)、[补跑前 PDF](../output/pdf/sciresearch-unified-r1-report-20261029.pdf)。
'''

def failure_text(data):
    failures = data['attempts'][:-1]
    if not failures:
        return '未发生关联基础设施重试。'
    return '基础设施失败均保留：' + '；'.join(f"`{a['attempt_id']}`，{a['status']}，已知输出 {a['known_output_tokens']:,} token，研究 {a['research_wall_seconds']/60:.2f} 分钟" for a in failures) + '。'

def write_reports(data, html=False):
    (ROOT / OUT).mkdir(parents=True, exist_ok=True)
    (ROOT / OUT / 'reviewed-results.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    main = (ROOT / ARCHIVE / 'docs/submission-report-2026-10-24.md').read_text()
    main = main.replace('九组 r1 统一重测 ·', '九组 r1 统一重测及 ODE G1 单组补跑 ·', 1)
    main = main.replace('../output/pdf/sciresearch-unified-r1-report-20261029.pdf', '../output/pdf/' + PDF, 1)
    main = main.replace('本版按用户要求，只展示', '本版主实验按用户要求，展示', 1)
    main = main.replace('本次 **8/9 正式成功**', '原九组主实验 **8/9 正式成功**', 1)
    notice = f"**后续单组补跑：ODE G1 r1 得分 {data['final_score']:.3f}，reward={data['reward']}。** 这是用户在确认原失败后要求的新独立会话；原九组 8/9 成功率与 0 分记录保留，第 13 节单列补跑对照。\n\n"
    main = main.replace('## 摘要与阅读说明\n\n', '## 摘要与阅读说明\n\n' + notice, 1)
    main = main.replace('### 4.2 本次只运行 r1', '### 4.2 原九组主实验只运行 r1', 1)
    main = main.replace('报告没有根据隐藏分数挑选重试或候选。', '原九组主实验没有根据隐藏分数挑选重试或候选；随后用户指定的单组事后补跑见第 13 节。', 1)
    main = main.replace('有效科学结果不因分数低而重试。', '本九组批次内，有效科学结果不因分数低而进行基础设施重试；第 13 节是用户另行要求的新科学会话。', 1)
    main = main.replace('本版实验范围严格为', '本版主实验范围为', 1)
    main = main.replace('### 7.1 本次结果', '### 7.1 原九组结果', 1)
    main = main.replace('### 9.1 本次观察', '### 9.1 原九组观察', 1)
    main = main.replace('也不为取得更高分追加研究。', '该批次未据此追加研究；用户后来指定的独立补跑另列第 13 节。', 1)
    main = main.replace('## 12. 结论', '## 12. 九组主实验结论', 1)
    main = main.replace('python3 tools/build_unified_r1_report.py', 'python3 tools/build_ode_g1_rerun_report.py')
    main = main.replace('python3 tools/audit_unified_r1_report.py\n', 'python3 tools/audit_unified_r1_report.py\npython3 tools/audit_ode_g1_rerun_report.py\n')
    main = main.rstrip() + '\n\n' + supplement(data)
    (ROOT / 'docs/submission-report-2026-10-24.md').write_text(main.rstrip() + '\n')
    readme = (ROOT / ARCHIVE / 'README.md').read_text()
    readme = readme.replace('output/pdf/sciresearch-unified-r1-report-20261029.pdf', 'output/pdf/' + PDF, 1)
    readme = readme.replace('九组 r1 统一重测）：', '九组 r1 统一重测及 ODE G1 单组补跑）：', 1)
    readme = readme.replace('本次仅运行 **Heat、ODE、Poisson', '九组主实验运行 **Heat、ODE、Poisson', 1)
    readme = readme.replace('查看专项审计。', '查看九组专项审计，运行 `python3 tools/audit_ode_g1_rerun_report.py` 核验后续单组补跑。', 1)
    update = f"\n**ODE G1 r1 后续单组补跑：{data['final_score']:.3f} 分，reward={data['reward']}。** 原九组仍记 8/9 成功，ODE G1 原 0 分保留；这一个事后追加会话的结果、用量及局限见[报告第 13 节](docs/submission-report-2026-10-24.md#13-ode-g1-r1-单组补跑2026-10-29)与[独立结果](results/ode-g1-r1-rerun-2026-10-29/reviewed-results.json)。\n"
    readme = readme.replace('## 建议阅读顺序', update + '\n## 建议阅读顺序', 1)
    (ROOT / 'README.md').write_text(readme.rstrip() + '\n')
    repro = (ROOT / ARCHIVE / 'docs/reproduction.md').read_text()
    repro = repro.replace('当前报告只展示 Heat、ODE、Poisson', '原九组主报告展示 Heat、ODE、Poisson', 1)
    repro = repro.replace('只整理已关闭的记录并生成当前九组报告', '只整理已关闭的记录并生成补跑前九组报告', 1)
    repro += f'''
## ODE G1 r1 单组补跑报告

原九组结果固定保留；单组补跑由 `logs/ode-g1-r1-rerun-2026-10-29/protocol.json` 限定唯一科学会话，执行模板中的 G2/G3 不启动。不要再次运行已有 `launch.py` / `controller.py`；新实验必须新建授权和冻结记录。补跑结果是事后追加样本，不替换原九组 8/9。

重建包含补跑的当前报告（只读取关闭后的证据，不调用模型或执行候选）：

```bash
.report-venv/bin/python tools/build_ode_g1_rerun_report.py --html
REPORT_PDF_NAME={PDF} node tools/render_final_report.cjs
python3 tools/audit_ode_g1_rerun_report.py
python3 tools/audit_unified_r1_report.py
python3 tools/build_delivery_manifest.py
python3 tools/verify_delivery.py
```

本生成器从[补跑前归档](../archives/pre-ode-g1-rerun-20261029/manifest.json)恢复九组正文，再追加单组对照；不改写原九组结果 JSON 或图表。PDF 另存为 `output/pdf/{PDF}`，原九组 PDF 保留。旧九组生成命令会恢复补跑前正文，因此当前版本应使用本节命令。
'''
    (ROOT / 'docs/reproduction.md').write_text(repro.rstrip() + '\n')
    (ROOT / 'docs/ode-g1-r1-rerun-2026-10-29.md').write_text('# ODE G1 r1 单组补跑证据\n\n' + supplement(data).split('\n', 1)[1].lstrip())
    if html:
        from build_final_report import html_report
        html_report(local_evidence=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', action='store_true')
    args = parser.parse_args()
    result = build_data()
    write_reports(result, args.html)
    print(json.dumps({k: result[k] for k in ('status', 'scientific_sessions', 'final_score', 'reward', 'attempt_status', 'raw_case_records_checked')}, ensure_ascii=False))
