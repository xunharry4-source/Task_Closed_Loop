#!/usr/bin/env sh
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
set -eu
cd "$(dirname "$0")"

echo "Test Resource:"
echo "  config/test_resources.yml"
echo "Test Capability:"
echo "  config/test_capabilities.yml"
echo

TEST_CONFIG_ENABLED=true python3 start.py
