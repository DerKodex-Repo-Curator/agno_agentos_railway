#!/usr/bin/env bash
# Run the API on the host so DockerSandbox can use the host Docker daemon.
set -euo pipefail
cd "$(dirname "$0")/.."
export RUNTIME_ENV=dev
export DB_HOST="${DB_HOST:-127.0.0.1}"
export DB_PORT="${DB_PORT:-5432}"
# Parse dotenv as data, then resolve ports and URLs in the same environment as
# the API. Shell values take precedence; credentials never pass through stdout.
exec uv run --no-project --env-file .env --with-requirements requirements.txt python - <<'PY'
import os

from db.url import db_url

port = os.environ.get("PORT", "8000")
os.environ["DATABASE_URL"] = db_url
os.environ.setdefault("REDIS_URL", f"redis://127.0.0.1:{os.environ.get('REDIS_PORT', '6380')}/0")
os.environ.setdefault("AGENTOS_URL", f"http://127.0.0.1:{port}")
os.execvp("uvicorn", [
    "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port, "--reload",
    *[arg for folder in ("agents", "app", "db", "evals", "teams", "workflows")
      for arg in ("--reload-dir", folder)],
])
PY
