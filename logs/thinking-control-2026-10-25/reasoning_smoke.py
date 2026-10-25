"""Require nonempty native thinking on a small synthetic counting problem."""
import runpy
import shutil
import uuid
from pathlib import Path

from runner import relay_transport
from runner.common import write_json

OUT = Path(__file__).resolve().parent
helper = runpy.run_path(str(OUT / 'live_smoke.py'))
root = helper['ROOT']
out = OUT / 'live-reasoning-roundtrip'
out.mkdir(exist_ok=False)
admission = relay_transport.start_relay(root / 'build' / ('relay-thinking-probe-' + uuid.uuid4().hex[:12]),
    image=helper['NUMERIC'], session_seconds=600, session_output_limit=200000, max_requests=3125, thinking_effort='max')
record = {'status': 'starting', 'formal': False, 'scientific_data_accessed': False}
try:
    record['native'] = helper['invoke'](admission, OUT / 'native_reasoning_roundtrip.mjs', '', out / 'native')
    record['relay_status'] = relay_transport.read_status(admission)
    record['status'] = 'passed'
finally:
    record['cleanup'] = relay_transport.cleanup_relay(admission)
    shutil.copytree(Path(admission['output_root']) / 'evidence', out / 'relay-evidence')
    write_json(out / 'result.json', record)
print(record['status'])
