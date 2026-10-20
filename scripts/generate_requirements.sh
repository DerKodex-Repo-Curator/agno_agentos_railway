#!/usr/bin/env bash
# Regenerate pins; optionally upgrade all packages or selected package names.
set -euo pipefail
cd "$(dirname "$0")/.."
flags=()
if [[ "${1:-}" == upgrade ]]; then
    flags+=(--upgrade)
elif [[ $# -gt 0 ]]; then
    for package in "$@"; do flags+=(--upgrade-package "$package"); done
fi
UV_CUSTOM_COMPILE_COMMAND='./scripts/generate_requirements.sh' \
    uv pip compile pyproject.toml "${flags[@]}" -o requirements.txt
