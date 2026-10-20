#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'Install uv: https://docs.astral.sh/uv/'; exit 1; }
if [[ ! -x .venv/bin/python ]]; then uv venv .venv --python 3.14; fi
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python -c requirements.txt -e '.[dev]'
echo 'Activate with: source .venv/bin/activate'
