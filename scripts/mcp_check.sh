#!/usr/bin/env bash

############################################################################
#
#    Agno MCP Smoke Check
#
#    Initializes the MCP endpoint and verifies the exact tool surface.
#    Passing a prompt also calls the agno tool and spends model calls.
#
#    Usage:
#      ./scripts/mcp_check.sh
#      ./scripts/mcp_check.sh "What does the platform run?"
#      MCP_CHECK_HOST=1 ./scripts/mcp_check.sh
#
#    By default the client runs inside the agentos-api container.
#    Host mode uses uv with .env and requirements.txt.
#    In the client environment, AGENTOS_URL overrides http://localhost:8000.
#    For authenticated endpoints, export MCP_CHECK_TOKEN (a JWT or PAT).
#
############################################################################

set -euo pipefail
cd "$(dirname "$0")/.."

# Colors
ORANGE='\033[38;5;208m'
RED='\033[31m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

runner=(docker compose exec -T)
if [[ -n "${MCP_CHECK_TOKEN:-}" ]]; then runner+=(-e MCP_CHECK_TOKEN); fi
runner+=(agentos-api python -u)
if [[ "${MCP_CHECK_HOST:-0}" == 1 ]]; then
    runner=(uv run --no-project --env-file .env --with-requirements requirements.txt python -u)
fi

echo ""
echo -e "${ORANGE}▸${NC} ${BOLD}MCP Check${NC}"
if [[ "${MCP_CHECK_HOST:-0}" == 1 ]]; then
    echo -e "${DIM}Client: host (uv)${NC}"
else
    echo -e "${DIM}Client: agentos-api container${NC}"
fi
if [[ -n "${1:-}" ]]; then
    echo -e "${DIM}Mode: handshake, tool surface and model response${NC}"
else
    echo -e "${DIM}Mode: handshake and tool surface (no model call)${NC}"
fi
echo ""

if "${runner[@]}" - "${1:-}" <<'PY'
import asyncio
import os
import sys
import time

from httpx2 import AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED = {
    "agno", "get_agentos_config", "run_agent", "run_team", "run_workflow",
    "continue_run", "cancel_run", "get_sessions", "get_session_runs",
}

ORANGE = "\033[38;5;208m"
DIM = "\033[2m"
NC = "\033[0m"

def step(text: str) -> None:
    print(f"{ORANGE}✓{NC} {text}", flush=True)

async def main():
    token = os.getenv("MCP_CHECK_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = os.getenv("AGENTOS_URL", "http://localhost:8000").rstrip("/") + "/mcp"
    async with AsyncClient(headers=headers, timeout=180) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            read, write, *_ = streams
            async with ClientSession(read, write) as session:
                await session.initialize()
                step("Handshake")
                names = {tool.name for tool in (await session.list_tools()).tools}
                if names != EXPECTED:
                    raise RuntimeError(
                        f"MCP tool mismatch: missing={sorted(EXPECTED - names)}, extra={sorted(names - EXPECTED)}"
                    )
                step(f"MCP OK: {len(names)} tools")
                if sys.argv[1]:
                    start = time.perf_counter()
                    result = await session.call_tool("agno", {"message": sys.argv[1]})
                    if result.is_error:
                        raise RuntimeError(str(result.content))
                    step(f"agno answered in {time.perf_counter() - start:.1f}s")
                    print(f"\n{DIM}Agent response:{NC}\n")
                    for item in result.content:
                        if hasattr(item, "text"):
                            print(item.text)

asyncio.run(main())
PY
then
    echo ""
    echo -e "${BOLD}Done.${NC}"
    echo ""
else
    echo ""
    echo -e "${RED}${BOLD}Failed.${NC}"
    if [[ "${MCP_CHECK_HOST:-0}" == 1 ]]; then
        echo -e "${DIM}Check the local API terminal and AGENTOS_URL.${NC}"
    else
        echo -e "${DIM}Check the container: docker compose logs agentos-api${NC}"
    fi
    echo -e "${DIM}For authenticated endpoints, export MCP_CHECK_TOKEN with a valid JWT or PAT.${NC}"
    echo ""
    exit 1
fi
