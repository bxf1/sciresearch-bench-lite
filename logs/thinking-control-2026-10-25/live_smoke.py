"""Verify native thinking/tool continuation and compaction on synthetic input only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from runner import relay_transport
from runner.common import read_json, write_json

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = read_json(ROOT / 'freezes/research-run-plan-formal-003.json')
POLICY = read_json(ROOT / OLD['tool_config']['runtime_enforcement']['path'])
NUMERIC = read_json(ROOT / OLD['freezes']['heat']['path'])['image_id']
RIMAGE = OLD['research_images']['heat']['image_id']


def invoke(admission, script, mode, output):
    env = os.environ.copy()
    env['BENCH_RELAY_KEY'] = admission['token']
    command = ['docker', 'run', '--rm', '--name', 'sciresearch-thinking-probe-' + uuid.uuid4().hex[:12],
               '--network', admission['network_name'], '--cpus', '1', '--memory', '1g', '--memory-swap', '1g',
               '--pids-limit', '128', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--read-only', '--user', '1000:1000', '--tmpfs', '/tmp:rw,nosuid,nodev,size=33554432',
               '--env', 'BENCH_RELAY_KEY',
               '--mount', f'type=bind,src={ROOT / "build/pi-policy-cache-local-001/nvm"},dst=/home/researcher/.nvm,readonly',
               '--mount', f'type=bind,src={script},dst=/probe/run.mjs,readonly',
               RIMAGE, '/home/researcher/.nvm/versions/node/v22.23.4/bin/node', '/probe/run.mjs', admission['base_url'], mode]
    proc = subprocess.run(command, env=env, capture_output=True, text=True, timeout=420)
    def safe(text):
        for secret in (admission['token'], os.environ.get('ANTHROPIC_AUTH_TOKEN', '')):
            if secret:
                text = text.replace(secret, '[REDACTED]')
        return text
    output.with_suffix('.stdout.txt').write_text(safe(proc.stdout))
    output.with_suffix('.stderr.txt').write_text(safe(proc.stderr))
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert proc.returncode == 0 and result['status'] in ('passed', 'success'), result
    return result


def main():
    result = {'formal': False, 'scope': 'Synthetic tool round-trip and native initial/update summaries; no benchmark scores.', 'cases': []}
    for kind in ('roundtrip', 'compaction'):
        out = OUT / ('live-' + kind)
        out.mkdir(exist_ok=False)
        expected = {} if kind == 'roundtrip' else {
            'expected_system_sha256': POLICY['wire_system_sha256'],
            'expected_tools_sha256': POLICY['wire_tools_sha256'],
            'expected_compaction_system_sha256': POLICY['native_compaction']['wire_system_sha256']}
        admission = relay_transport.start_relay(ROOT / 'build' / ('relay-thinking-probe-' + uuid.uuid4().hex[:12]),
            image=NUMERIC, session_seconds=600, session_output_limit=200000, max_requests=3125,
            thinking_effort='max', **expected)
        record = {'kind': kind, 'cases': [], 'status': 'starting'}
        try:
            if kind == 'roundtrip':
                record['cases'].append(invoke(admission, OUT / 'native_roundtrip.mjs', '', out / 'roundtrip'))
            else:
                script = (ROOT / 'logs/formal-execution-local-002/native_summary.mjs').read_text()
                script = script.replace("const token = 'offline-relay-session-token-not-a-credential';", 'const token = process.env.BENCH_RELAY_KEY;')
                script = script.replace('Synthetic offline conversation for summarizer wiring only.',
                                        'Synthetic conversation: user requests OK; assistant responds OK. No scientific data.')
                target = out / 'native_summary.mjs'
                target.write_text(script)
                for mode in ('initial', 'update'):
                    record['cases'].append(invoke(admission, target, mode, out / mode))
            status = relay_transport.read_status(admission)
            assert status['successful_requests'] >= 2 and status['failed_requests'] == 0
            assert not status['protocol_violation'] and status['limits']['thinking'] == {'type': 'enabled'}
            assert status['limits']['output_config'] == {'effort': 'max'} and status['limits']['temperature'] is None
            record.update(status='passed', relay_status=status)
        finally:
            record['cleanup'] = relay_transport.cleanup_relay(admission)
            shutil.copytree(Path(admission['output_root']) / 'evidence', out / 'relay-evidence')
            write_json(out / 'result.json', record)
        assert record['cleanup']['all_removed']
        result['cases'].append({'kind': kind, 'status': record['status'], 'relay_status': record['relay_status']})
        print(json.dumps({'kind': kind, 'status': record['status'], 'requests': record['relay_status']['successful_requests'],
                          'output_tokens': record['relay_status']['charged_output_tokens']}), flush=True)
    result['status'] = 'passed'
    write_json(OUT / 'live-smoke-result.json', result)


if __name__ == '__main__':
    main()
