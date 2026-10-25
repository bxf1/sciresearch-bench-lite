"""Exercise the repaired relay with native thinking/tool continuation only."""
from pathlib import Path
import runpy
import shutil
import uuid

from runner import relay_transport
from runner.common import file_hash, read_json, write_json

OUT = Path(__file__).resolve().parent
BATCH = OUT.parent
ROOT = BATCH.parents[1]
helper = runpy.run_path(str(BATCH / 'live_smoke.py'))
out = OUT / 'live-probe'
out.mkdir(exist_ok=False)
admission = relay_transport.start_relay(ROOT / 'build' / ('relay-usage-repair-probe-' + uuid.uuid4().hex[:12]),
    image=helper['NUMERIC'], session_seconds=600, session_output_limit=200000,
    max_requests=3125, thinking_effort='max')
record = {'status': 'starting', 'formal': False, 'scientific_data_accessed': False,
          'scope': 'Synthetic native thinking/tool transport; excluded from research and scores.'}
try:
    startup = read_json(Path(admission['output_root']) / 'startup.json')
    assert startup['relay_source_sha256'] == file_hash(ROOT / 'runner/model_relay.py')
    record['relay_source_sha256'] = startup['relay_source_sha256']
    record['native'] = helper['invoke'](admission, BATCH / 'native_reasoning_roundtrip.mjs', '', out / 'native')
    status = relay_transport.read_status(admission)
    assert status['successful_requests'] >= 2 and status['failed_requests'] == 0
    assert not status['protocol_violation']
    assert status['limits']['thinking'] == {'type': 'enabled'}
    assert status['limits']['output_config'] == {'effort': 'max'}
    assert status['limits']['request_output_limit'] == 4096
    record.update(status='passed', relay_status=status)
finally:
    record['cleanup'] = relay_transport.cleanup_relay(admission)
    shutil.copytree(Path(admission['output_root']) / 'evidence', out / 'relay-evidence')
    write_json(out / 'result.json', record)
assert record['cleanup']['all_removed']
print({'status': record['status'], 'requests': status['successful_requests'],
       'output_tokens': status['charged_output_tokens']}, flush=True)
