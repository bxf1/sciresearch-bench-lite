"""Independently verify the single-rerun result, raw ODE scores and report scope."""
from collections import Counter
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
def read(path):
    return json.loads((ROOT / path).read_text())
def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()

def audit():
    result = read('results/ode-g1-r1-rerun-2026-10-29/reviewed-results.json')
    for name, expected in result['source_sha256'].items():
        assert sha(name) == expected, name
    assert result['scientific_sessions'] == 1 and result['kind'] == 'post_hoc_single_session_rerun'
    protocol = read(result['protocol']['path'])
    plan = read(protocol['template']['path'])
    assert sha(protocol['template']['path']) == protocol['template']['sha256']
    for path, expected in plan['tool_config']['files'].items():
        assert sha(path) == expected, path
    for ref in protocol['adapter_sources'].values():
        assert sha(ref['path']) == ref['sha256']
    prompt = (ROOT / 'prompts/ode/common.md').read_bytes() + b'\n\n' + (ROOT / 'prompts/ode/g1.md').read_bytes()
    assert hashlib.sha256(prompt).hexdigest() == plan['tasks']['ode']['combined_prompt_hashes']['g1']
    row, = protocol['authorized_runs']
    assert row == plan['runs'][0] and row['group'] == 'g1' and row['task'] == 'ode'
    manifest = read(result['manifest']['path'])
    assert manifest['finalized_tasks'] == ['ode']
    assert manifest['single_session_protocol'] == result['protocol']
    assert {e['run_id'] for e in manifest['attempts']} == {row['run_id']}
    assert len(manifest['attempts']) == len(result['attempts']) <= 2
    for identity in protocol['dormant_template_run_ids']:
        assert not (ROOT / 'research-runs' / identity).exists()
    old = read(protocol['original_nine_results']['path'])
    assert sha(protocol['original_nine_results']['path']) == protocol['original_nine_results']['sha256']
    assert old['new_sessions'] == 9 and old['new_reward_one'] == 8
    old_row = next(r for r in old['rows'] if r['task'] == 'ode' and r['group'] == 'g1')
    assert result['original_ode_g1'] == old_row and old_row['final_score'] == 0 and old_row['final_id'] is None
    native = old['uniform_installed_sources']
    for index, (entry, saved) in enumerate(zip(manifest['attempts'], result['attempts'])):
        host, registry = read(entry['result']['path']), read(entry['registry']['path'])
        assert datetime.datetime.fromisoformat(protocol['frozen_at']).timestamp() < registry['started_at']
        assert saved['attempt_id'] == entry['attempt_id'] and saved['status'] == host['attempt_status']
        if index < len(manifest['attempts']) - 1:
            assert host['attempt_status'] in ('api_failed', 'infrastructure_failed', 'cancelled')
            assert manifest['attempts'][index + 1]['parent_attempt'] == entry['attempt_id']
        assert host['native_setup_evidence']['installed_source_sha256'] == native
        assert {k: v for k, v in host['trusted_source_sha256'].items() if not k.startswith('prompts/')} == old['uniform_trusted_sources']
        assert host['relay_status']['limits'] == plan['runtime_policy']
        assert plan['model']['request_output_limit'] == 16384 and plan['model']['output_token_limit'] == 200000
        events = [json.loads(line) for line in (ROOT / entry['relay_events']['path']).read_text().splitlines()]
        requests = [e for e in events if e['event'] == 'request_accepted']
        ends = [e for e in events if e['event'] == 'request_finished']
        assert saved['requests'] == len(requests) == len(ends)
        assert saved['known_output_tokens'] == sum(e.get('output_tokens') or 0 for e in ends)
        assert saved['charged_output_tokens'] == sum(e.get('charged_output_tokens') or 0 for e in ends)
        assert saved['request_outcomes'] == dict(Counter(e['outcome'] for e in ends))
        assert saved['compaction_requests'] == sum(e.get('request_kind') == 'native_compaction' for e in requests)
        assert saved['one_token_requests'] == sum(e['effective_max_tokens'] == 1 for e in requests)
        assert saved['responses_over_4096'] == sum((e.get('output_tokens') or 0) > 4096 for e in ends)
        assert saved['max_request_limit'] == max(e['effective_max_tokens'] for e in requests) == 16384
        assert saved['public_evaluations'] == len(registry['evaluations'])
        assert math.isclose(saved['research_wall_seconds'], registry['attempt_outcome']['recorded_at'] - registry['started_at'])
    retained = manifest['attempts'][-1]
    registry = read(retained['registry']['path'])
    assert registry['closed'] and registry['attempt_outcome']['recorded_at'] < retained['replay_started_at']
    raw = read(result['score_evidence']['path'])
    assert raw['registry_sha256'] == retained['registry']['sha256']
    assert raw['freeze_sha256'] == plan['freezes']['ode']['sha256']
    assert raw['protocol'] == result['protocol'] and raw['split'] == 'final-test'
    diagnostics = raw['diagnostics']
    assert diagnostics['evaluation_status'] == 'valid'
    records, unique_sources = 0, set()
    for role in ('first', 'final'):
        checkpoint = diagnostics[role]
        assert result[role + '_score'] == checkpoint['score']
        assert result[role + '_id'] == registry[role + '_id'] == checkpoint['checkpoint_id']
        if checkpoint.get('source_hash'):
            source = ROOT / Path(retained['registry']['path']).parent / 'snapshots' / checkpoint['checkpoint_id']
            files = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.rglob('*')) if p.is_file()}
            assert hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == checkpoint['source_hash']
            unique_sources.add(checkpoint['source_hash'])
        repeats = checkpoint.get('repeats', [])
        if not repeats:
            assert checkpoint['score'] == checkpoint['reward'] == 0
            continue
        assert len(repeats) == 3
        for rep in repeats:
            assert rep['evaluation_status'] == 'valid' and len(rep['cases']) == rep['total'] == 12
            scores, passes = [], []
            for c in rep['cases']:
                records += 1
                valid = c.get('artifact_valid') is not False and c.get('K') is not None and c['K'] <= 10 and c.get('E_roll') is not None and c.get('E_field') is not None
                score = 50 * (min(1, max(0, 1 - 10 * c['E_roll'])) + min(1, max(0, 1 - 10 * c['E_field']))) if valid else 0
                passed = valid and max(c['E_roll'], c['E_field']) <= .05
                assert math.isclose(c['score'], score, abs_tol=1e-9) and c['scientific_pass'] == passed
                scores.append(score)
                passes.append(passed)
            assert rep['passed'] == sum(passes) and rep['reward'] == int(all(passes))
            assert math.isclose(rep['score'], statistics.mean(scores), abs_tol=1e-9)
        assert math.isclose(checkpoint['score'], statistics.mean(r['score'] for r in repeats), abs_tol=1e-9)
        assert checkpoint['reward'] == int(all(r['reward'] for r in repeats))
    assert result['reward'] == diagnostics['final']['reward']
    assert result['raw_case_records_checked'] == records
    assert result['passed_per_replay'] == [r['passed'] for r in diagnostics['final'].get('repeats', [])]
    assert result['all_attempt_known_output_tokens'] == sum(a['known_output_tokens'] for a in result['attempts'])
    assert result['all_attempt_charged_output_tokens'] == sum(a['charged_output_tokens'] for a in result['attempts'])
    observations = result['execution_observations']
    for path, expected in observations['source_sha256'].items():
        assert sha(path) == expected
    call = observations['last_tool_call']
    trace_path = next(p for p in observations['source_sha256'] if '/sessions/' in p)
    trace = [json.loads(line) for line in (ROOT / trace_path).read_text().splitlines()]
    event = trace[-1]
    actual = next(c for c in event['message']['content'] if c.get('type') == 'toolCall')
    assert actual['id'] == call['tool_call_id'] and event['timestamp'] == call['started_at']
    assert 'timeout' not in actual['arguments'] and not call['explicit_timeout_present']
    assert hashlib.sha256(actual['arguments']['command'].encode()).hexdigest() == call['command_sha256']
    assert actual['arguments']['command'].endswith(call['command_suffix'])
    assert not any(e.get('message', {}).get('toolCallId') == actual['id'] for e in trace)
    started = datetime.datetime.fromisoformat(call['started_at'].replace('Z', '+00:00')).timestamp()
    assert call['unreturned_interval_seconds'] == registry['attempt_outcome']['recorded_at'] - started
    assert call['started_after_seconds'] == started - registry['started_at']
    archive = read(protocol['pre_rerun_archive']['path'])
    for name, expected in archive['files'].items():
        assert sha(Path('archives/pre-ode-g1-rerun-20261029') / name) == expected
        if name.startswith(('results/', 'output/pdf/')):
            assert sha(name) == expected
    service = read('logs/ode-g1-r1-rerun-2026-10-29/service-restoration.json')
    assert service['restored'] and service['after']['health'] == 'healthy'
    report = (ROOT / 'docs/submission-report-2026-10-24.md').read_text()
    assert len(re.findall(r'\| M\d\d \|', report)) == 9
    assert '## 13. ODE G1 r1 单组补跑' in report
    assert f"| 最终分数 | 0.000 | {result['final_score']:.3f} |" in report
    assert any(label + '仍为 8/9 成功，M04 的 0 分和原始记录保留' in report
               for label in ('原九组', '第二版正式九组'))
    links = 0
    for name in ('README.md', 'docs/submission-report-2026-10-24.md', 'docs/reproduction.md', 'docs/ode-g1-r1-rerun-2026-10-29.md'):
        path = ROOT / name
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('http:', 'https:', '#', 'mailto:')):
                continue
            assert (path.parent / target.split('#')[0]).exists(), (name, target)
            links += 1
    return {'status': 'passed', 'additional_scientific_sessions': 1, 'attempts': len(result['attempts']),
            'final_score': result['final_score'], 'reward': result['reward'], 'raw_case_records_checked': records,
            'unique_selected_candidate_sources': len(unique_sources), 'original_nine_successes': '8/9',
            'old_zero_preserved': True, 'same_executor_and_limits': True,
            'dormant_sessions_launched': 0, 'archived_files_checked': len(archive['files']),
            'service_restored': True, 'local_links_checked': links}

if __name__ == '__main__':
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
