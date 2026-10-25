"""Detach one authorized controller and inhibit system sleep for its lifetime."""
import os
from pathlib import Path
import subprocess
import sys
import time

from runner.common import file_hash, write_json
from runner.study import frozen_plan

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PLAN = ROOT / 'freezes/research-run-plan-thinking-max-2026-10-25.json'
plan, reference = frozen_plan(ROOT, PLAN)
assert not (OUT / 'process.json').exists(), 'Preserve the existing launch record; investigate before any recovery.'
assert os.environ.get('ANTHROPIC_AUTH_TOKEN'), 'Provider credential unavailable'
env = os.environ.copy()
env['PYTHONPATH'] = str(ROOT)
env['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
controller = OUT / 'controller.py'
with (OUT / 'controller.stdout.log').open('xb') as stream:
    proc = subprocess.Popen(['/usr/bin/caffeinate', '-dimsu', sys.executable, str(controller)], cwd=ROOT,
                            env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                            start_new_session=True, close_fds=True)
write_json(OUT / 'process.json', {'pid': proc.pid, 'started_at': time.time(), 'detached': True,
    'controller': controller.relative_to(ROOT).as_posix(), 'controller_sha256': file_hash(controller),
    'plan': reference, 'plan_id': plan['plan_id'], 'sessions': 15, 'output_token_limit': 200000,
    'thinking': {'type': 'enabled'}, 'output_config': {'effort': 'max'}, 'sleep_inhibited_while_running': True,
    'after_research': 'Full 15-session closure barrier, independent baseline/candidate scoring, retained invalid windows, report.'})
print(f'Launched detached controller supervisor PID {proc.pid}, plan {plan["plan_id"]}')
