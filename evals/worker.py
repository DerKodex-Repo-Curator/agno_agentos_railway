"""Private worker. No server lifespan, scheduler, queue worker or production writes."""

import asyncio
import os
import sys
from pathlib import Path

from evals.isolation import require_isolation


async def main() -> int:
    require_isolation()
    for i, argument in enumerate(sys.argv):
        path = None
        if argument == "--json-output" and i + 1 < len(sys.argv):
            path = sys.argv[i + 1]
        elif argument.startswith("--json-output="):
            path = argument.split("=", 1)[1]
        if path:
            evidence = Path(path).with_suffix(".evidence.jsonl")
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("")
            os.environ["RAILWAY_EVAL_EVIDENCE"] = str(evidence)

    from agno.company import CompanyManager
    from agno.company.bootstrap import arehydrate_product
    from agno.eval import acli
    from agno.os.utils import collect_mcp_tools_from_registry, collect_mcp_tools_from_team

    from app.company import products
    from app.main import agent_os
    from app.registry import registry
    from db import get_postgres_db
    from evals.cases import CASES

    db = get_postgres_db()
    db._create_all_tables()
    for product in products:
        for source in product.sources:
            if source.type == "git":
                source.reference = str(Path.cwd())
        await arehydrate_product(db, product, registry)
    # Company lazily creates its default wiki pages on first read. Initialize
    # those fixtures before snapshots; later edits remain visible to the scorer.
    company = CompanyManager(db)
    company.get_wiki()
    for product in products:
        company.get_wiki(product.id)
    manager_team = agent_os.manager
    assert manager_team is not None
    mcp_tools: list = []
    collect_mcp_tools_from_registry(registry, mcp_tools)
    collect_mcp_tools_from_team(manager_team, mcp_tools)
    assert agent_os.db is db
    return await acli(CASES, db=db, mcp_tools=mcp_tools)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
