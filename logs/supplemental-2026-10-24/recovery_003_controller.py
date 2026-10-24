"""Resume the authorized batch, then replay only after all six sessions close."""
import asyncio
import importlib.util
import time
from pathlib import Path

from runner import supplemental as sup
from runner.common import read_json, write_json

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'freezes/supplemental-500k-2026-10-24-recovery-003.json'
STATE = ROOT / 'logs/supplemental-2026-10-24/recovery-003-state.json'


def record(stage, **details):
    write_json(STATE, {'stage': stage, 'updated_at': time.time(),
                       'plan': sup.reference(PLAN), **details})


def main():
    sup.PLAN = PLAN
    plan = sup.load_plan()
    for key in ('parent_supplemental_plan', 'recovery_ledger',
                'recovery_evidence', 'api_recovery_probe', 'controller'):
        sup.checked(plan[key])
    assert sup.checked(plan['controller']) == Path(__file__).resolve()
    assert read_json(sup.checked(plan['api_recovery_probe']))['http_status'] == 200
    record('research_running', hidden_data_accessed=False)
    asyncio.run(sup.run_all())

    spec = importlib.util.spec_from_file_location(
        'supplemental_scoring', ROOT / 'logs/supplemental-2026-10-24/score_supplemental.py')
    scoring = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scoring)
    # The existing replay implementation is reused with distinct immutable outputs.
    sup.PLAN = PLAN
    scoring.OUT = ROOT / 'results/supplemental-2026-10-24-recovery-003'
    assert scoring.barrier(), 'All six research sessions must close before hidden replay'
    record('scoring_running', all_six_research_closed=True)
    scoring.main()
    summary = read_json(scoring.OUT / 'summary.json')
    incomplete = [r['run_id'] for r in summary['results']
                  if r['diagnostics']['evaluation_status'] != 'valid']
    record('finished' if not incomplete else 'finished_with_incomplete_evaluations',
           all_six_research_closed=True, summary=sup.reference(scoring.OUT / 'summary.json'),
           incomplete_evaluations=incomplete)


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        record('stopped', error_category=type(exc).__name__)
        raise
