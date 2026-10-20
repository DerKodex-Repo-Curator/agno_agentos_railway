#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
failed=0
ruff format --check . || failed=1
ruff check . || failed=1
mypy . --config-file pyproject.toml || failed=1
exit "$failed"
