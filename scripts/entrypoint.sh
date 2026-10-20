#!/usr/bin/env bash
set -euo pipefail
if [[ "${WAIT_FOR_DB:-}" == true || "${WAIT_FOR_DB:-}" == True ]]; then
    dockerize -wait "tcp://${DB_HOST}:${DB_PORT}" -timeout 300s
fi
exec "$@"
