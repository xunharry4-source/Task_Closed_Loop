#!/usr/bin/env sh
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
set -eu
cd "$(dirname "$0")"
python3 start.py
