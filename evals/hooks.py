"""Read-only state snapshots; database ownership and cleanup live in isolation.py.

No shared-database snapshot/diff deletion is supported. Cases must run in the
private worker, and the parent drops only the database it created after exit.
"""

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text


def business_state(db: Any) -> dict[str, list[str]]:
    """Fail closed on DB errors; include all durable state except run bookkeeping."""
    excluded = {
        db.session_table_name,
        db.runs_table_name,
        db.eval_table_name,
        db.metrics_table_name,
        db.trace_table_name,
        db.span_table_name,
        db.versions_table_name,
        db.tool_results_table_name,
        db.compactions_table_name,
        db.transcripts_table_name,
        "eval_owner",
    }
    result = {}
    quote = db.db_engine.dialect.identifier_preparer.quote
    with db.db_engine.connect() as conn:
        inspector = inspect(conn)
        for schema in inspector.get_schema_names():
            if schema.startswith("pg_") or schema == "information_schema":
                continue
            for table in inspector.get_table_names(schema=schema):
                if (schema == db.db_schema and table in excluded) or table == "railway_eval_owner":
                    continue
                rows = conn.execute(text(f"SELECT * FROM {quote(schema)}.{quote(table)}")).mappings()
                values = [
                    dict(row)
                    for row in rows
                    if not (
                        schema == "fs"
                        and table == "agno_fs"
                        and str(row.get("namespace", "")).startswith("tool-results/")
                    )
                ]
                if values:
                    result[f"{schema}.{table}"] = sorted(json.dumps(row, sort_keys=True, default=str) for row in values)
    return result


def record_evidence(context: Any, result: Any) -> None:
    """Keep the full run next to an explicit JSON report before ephemeral data is dropped."""
    from db import get_postgres_db

    save_run(result.name, result.response, result.error, db=get_postgres_db())


def save_run(name: str, response: Any, error: str | None = None, *, db: Any = None) -> None:
    if destination := os.getenv("RAILWAY_EVAL_EVIDENCE"):
        evidence = {"case": name, "error": error, "response": response.to_dict() if response else None}
        if response is not None and db is not None:
            from evals.scorers import payload, tool_calls

            try:
                evidence["resolved_tools"] = [
                    {"name": tool.tool_name, "arguments": tool.tool_args, "result": payload(tool, db)}
                    for tool in tool_calls(response, db)
                ]
            except Exception as exc:
                # Keep the raw failed run even if its child evidence cannot be read.
                evidence["tool_evidence_error"] = str(exc)
        with Path(destination).open("a") as stream:
            stream.write(json.dumps(evidence, default=str) + "\n")
