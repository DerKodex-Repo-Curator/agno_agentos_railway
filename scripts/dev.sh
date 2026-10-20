#!/usr/bin/env bash

############################################################################
#
#    Agno Local Development Server
#
#    Runs the API on the host so DockerSandbox can use the host Docker daemon.
#
#    Usage:
#      ./scripts/dev.sh
#      SANDBOX_ENABLED=true ./scripts/dev.sh
#
#    Prerequisites:
#      - uv installed and .env configured
#      - PostgreSQL running: docker compose up -d agentos-db
#      - Stop the container API first: docker compose stop agentos-api
#
#    Development disables JWT and binds the API to 127.0.0.1.
#
############################################################################

set -euo pipefail
cd "$(dirname "$0")/.."

# Colors
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${ORANGE}▸${NC} ${BOLD}Starting local AgentOS${NC}"
echo -e "${DIM}Mode: dev (JWT disabled); hot reload enabled${NC}"
echo -e "${DIM}Press Ctrl+C to stop.${NC}"
echo ""

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
os.environ.setdefault("AGENTOS_URL", f"http://127.0.0.1:{port}")
os.execvp("uvicorn", [
    "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port, "--reload",
    *[arg for folder in ("agents", "app", "db", "evals", "teams")
      for arg in ("--reload-dir", folder)],
])
PY
