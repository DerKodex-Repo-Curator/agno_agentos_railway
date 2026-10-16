#!/usr/bin/env bash
# Run the API on the host so DockerSandbox can use the host Docker daemon.
set -euo pipefail
cd "$(dirname "$0")/.."
# dotenv is parsed by uv, never sourced as shell code. Shell values take precedence.
export RUNTIME_ENV=dev
export DB_HOST="${DB_HOST:-127.0.0.1}"
export DB_PORT="${DB_PORT:-5432}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:${REDIS_PORT:-6380}/0}"
export AGENTOS_URL="${AGENTOS_URL:-http://127.0.0.1:${PORT:-8000}}"
exec uv run --no-project --env-file .env --with-requirements requirements.txt uvicorn app.main:app \
  --host 127.0.0.1 --port "${PORT:-8000}" --reload \
  --reload-dir agents --reload-dir app --reload-dir db --reload-dir evals --reload-dir teams --reload-dir workflows
