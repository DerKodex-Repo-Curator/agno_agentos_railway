#!/usr/bin/env bash
# Initialize and check the tool surface. Passing a prompt also spends model calls.
# For authenticated endpoints provide MCP_CHECK_TOKEN (an existing JWT or PAT).
set -euo pipefail
cd "$(dirname "$0")/.."
runner=(docker compose exec -T)
if [[ -n "${MCP_CHECK_TOKEN:-}" ]]; then runner+=(-e MCP_CHECK_TOKEN); fi
runner+=(agentos-api python)
if [[ "${MCP_CHECK_HOST:-0}" == 1 ]]; then
    runner=(uv run --no-project --env-file .env --with-requirements requirements.txt python)
fi
"${runner[@]}" - "${1:-}" <<'PY'
import asyncio
import os
import sys

from httpx2 import AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED = {
    "agno", "get_agentos_config", "run_agent", "run_team", "run_workflow",
    "continue_run", "cancel_run", "get_sessions", "get_session_runs",
}

async def main():
    token = os.getenv("MCP_CHECK_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = os.getenv("AGENTOS_URL", "http://localhost:8000").rstrip("/") + "/mcp"
    async with AsyncClient(headers=headers, timeout=180) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            read, write, *_ = streams
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                if names != EXPECTED:
                    raise RuntimeError(f"MCP tool mismatch: missing={EXPECTED - names}, extra={names - EXPECTED}")
                print(f"MCP OK: {len(names)} tools; no model call unless a prompt was supplied.")
                if sys.argv[1]:
                    result = await session.call_tool("agno", {"message": sys.argv[1]})
                    if result.is_error:
                        raise RuntimeError(str(result.content))
                    for item in result.content:
                        if hasattr(item, "text"):
                            print(item.text)

asyncio.run(main())
PY
