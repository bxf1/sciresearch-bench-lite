"""Run the linked frozen recovery plan without a research wall-time limit."""
import asyncio
from pathlib import Path
from runner import supplemental
supplemental.PLAN=Path.cwd()/'freezes/supplemental-500k-2026-10-24-recovery-001.json'
asyncio.run(supplemental.run_all())
