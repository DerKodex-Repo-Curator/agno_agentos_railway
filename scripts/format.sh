#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ruff check --select I --fix .
ruff format .
