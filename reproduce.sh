#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONPATH="$PWD"
bench_python="${BENCH_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$bench_python" ]]; then
  echo 'Set BENCH_PYTHON to a Python 3.12 interpreter with requirements installed.' >&2
  exit 2
fi
case "${1:-test}" in
  test) exec "$bench_python" -m pytest -q tests ;;
  preflight) exec "$bench_python" -m runner.preflight --output "${2:?provide a fresh JSON output path}" ;;
  generate) exec "$bench_python" -m authoring.generate --output "${2:?provide a new data directory}" ;;
  calibrate) exec "$bench_python" -m runner.calibrate --data "${2:?data directory}" --output "${3:?new output directory}" ;;
  *) echo 'Usage: reproduce.sh test | preflight OUTPUT | generate DATA | calibrate DATA OUTPUT' >&2; exit 2 ;;
esac
