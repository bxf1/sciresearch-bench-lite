#!/bin/sh
set -eu
cd /Users/baixiongfei/Documents/Projects/build_bench/benchmark/build/clean-replay-local-001/source
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 /Users/baixiongfei/Documents/Projects/build_bench/benchmark/.venv/bin/python -I -m pytest -q
