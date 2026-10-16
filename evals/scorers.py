"""Behavioral gates over actual tool payloads and durable state, before database cleanup."""

import json
import re
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

from agno.offload import ResultStore
from agno.scorer.base import Score
from sqlalchemy import text

from evals.hooks import business_state, save_run


def tool_calls(run: Any) -> Iterator[Any]:
    yield from run.tools or []
    for member in getattr(run, "member_responses", None) or []:
        yield from tool_calls(member)


def payload(tool: Any, db: Any = None) -> Any:
    result = tool.result
    if isinstance(result, str):
        match = re.match(r'<result id="([^"]+)"', result)
        if match and db is not None:
            result = ResultStore(db=db).payload(match[1])
        try:
            result = json.loads(result)
        except ValueError, TypeError:
            return result
    if isinstance(result, dict) and result.get("result_id") and db is not None:
        return json.loads(ResultStore(db=db).payload(result["result_id"]))
    return result


def successful(tool: Any, db: Any = None) -> bool:
    if tool.tool_call_error or getattr(tool, "is_paused", False):
        return False
    result = payload(tool, db)
    if isinstance(result, dict):
        return not (
            result.get("ok") is False
            or result.get("error")
            or str(result.get("status", "")).lower() in {"error", "failed", "paused"}
        )
    return bool(result) and not str(result).lower().startswith(("error", "failed"))


def calls(run: Any, name: str, db: Any) -> list[Any]:
    return [tool for tool in tool_calls(run) if tool.tool_name == name and successful(tool, db)]


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# An attempted forbidden write fails even if rejected or subsequently undone.
MUTATIONS = (
    "create_",
    "edit_",
    "publish_",
    "delete_",
    "archive_",
    "restore_",
    "update_",
    "append_",
    "write_",
    "propose_",
    "accept_",
    "reject_",
    "intake_",
    "set_",
    "schedule_",
    "enable_",
    "disable_",
    "send_",
    "add_",
    "ingest_",
)


class Behavior:
    def __init__(self, db: Any, check: Callable[[Any, Any], None], *, readonly: bool = True, allow_run: bool = False):
        self.db, self.check, self.readonly, self.allow_run = db, check, readonly, allow_run
        self.before: dict[str, list[str]] | None = None

    def setup(self) -> None:
        self.before = business_state(self.db)

    async def ascore(self, run: Any, expected: Any = None) -> Score:
        try:
            require(self.before is not None, "Missing pre-run snapshot")
            if self.readonly:
                forbidden = [
                    t.tool_name
                    for t in tool_calls(run)
                    if t.tool_name.startswith(MUTATIONS)
                    or (
                        t.tool_name.startswith("run_")
                        and not (
                            self.allow_run
                            and t.tool_name == "run_workflow"
                            and (t.tool_args or {}).get("workflow_id") == "deployment-check"
                        )
                    )
                ]
                require(not forbidden, f"Read-only request attempted mutations/dispatch: {forbidden}")
                after = business_state(self.db)
                changed = [
                    key for key in set(self.before or {}) | set(after) if (self.before or {}).get(key) != after.get(key)
                ]
                require(not changed, f"Read-only request changed durable state: {changed}")
            else:
                # Studio cases may change exactly the one component they created.
                after = business_state(self.db)
                before_ids = {
                    json.loads(row)["component_id"]
                    for row in (self.before or {}).get(f"{self.db.db_schema}.{self.db.components_table_name}", [])
                }
                after_ids = {
                    json.loads(row)["component_id"]
                    for row in after.get(f"{self.db.db_schema}.{self.db.components_table_name}", [])
                }
                new_ids = after_ids - before_ids
                require(
                    len(new_ids) == 1 and before_ids <= after_ids, "Expected exactly one new component, no deletions"
                )
                target = next(iter(new_ids))
                component_tables = {
                    f"{self.db.db_schema}.{self.db.components_table_name}",
                    f"{self.db.db_schema}.{self.db.component_configs_table_name}",
                    f"{self.db.db_schema}.{self.db.component_links_table_name}",
                }

                def unrelated(state: dict[str, list[str]]) -> dict[str, list[str]]:
                    filtered = {}
                    for table, rows in state.items():
                        kept = [
                            row
                            for row in rows
                            if table not in component_tables
                            or (
                                json.loads(row).get("component_id", json.loads(row).get("parent_component_id"))
                                != target
                            )
                        ]
                        if kept:
                            filtered[table] = kept
                    return filtered

                require(
                    unrelated(self.before or {}) == unrelated(after), "Studio request changed unrelated durable state"
                )
                require(
                    not any(t.tool_name.startswith("run_") for t in tool_calls(run)),
                    "Component was run despite the no-run request",
                )
            self.check(run, self.db)
            return Score(1, True, "Tool evidence and durable-state checks passed")
        except AssertionError as exc:
            return Score(0, False, str(exc))


def source_read(run: Any, db: Any) -> None:
    url = "https://github.com/agno-agi/agno/releases"
    quote = db.db_engine.dialect.identifier_preparer.quote
    with db.db_engine.connect() as conn:
        sources = list(
            conn.execute(text(f"SELECT * FROM {quote(db.db_schema)}.{quote(db.sources_table_name)}")).mappings()
        )
    ids = {s["id"] for s in sources if s["reference"] == url and s["product_id"] == "this-agentos"}
    evidence = [
        payload(t, db)
        for t in calls(run, "read_company_source", db)
        if (t.tool_args or {}).get("source_id") in ids and (t.tool_args or {}).get("path") == url
    ]
    evidence = [
        p
        for p in evidence
        if isinstance(p, dict)
        and p.get("source_id") in ids
        and p.get("link") == url
        and p.get("content")
        and p.get("content_hash")
    ]
    require(evidence, "No successful content read of the configured release Source (an index is insufficient)")
    output = str(run.content)
    versions = re.findall(r"\bv?\d+\.\d+\.\d+\b", "\n".join(p["content"] for p in evidence))
    require(
        versions
        and re.findall(r"\bv?\d+\.\d+\.\d+\b", output)
        and re.findall(r"\bv?\d+\.\d+\.\d+\b", output)[0].removeprefix("v") == versions[0].removeprefix("v"),
        "Answer omits the first release version shown by the fetched page",
    )
    require(url in output, "Answer lacks the fetched Source citation")


def read_file(path: str) -> Callable[[Any, Any], None]:
    def check(run: Any, db: Any) -> None:
        matches = [t for t in calls(run, "read_file", db) if (t.tool_args or {}).get("path", "").lstrip("./") == path]
        require(matches, f"No successful read of {path}")

    return check


def onboarding(run: Any, db: Any) -> None:
    read_file("README.md")(run, db)
    answer = str(run.content)
    require(
        all(value in answer for value in ("docker compose up", "OPENAI_API_KEY", "example.env", ".env")),
        "Onboarding lacks documented startup commands and key configuration",
    )
    require(
        "os.agno.com" in answer or "/teams/os-manager-internal/runs" in answer,
        "Onboarding lacks a concrete OS Manager access path",
    )
    require(
        "/create-agent" in answer or ("agents/" in answer and "app/main.py" in answer),
        "Onboarding lacks a documented agent creation path",
    )


def health(run: Any, db: Any) -> None:
    results = [payload(t, db) for t in calls(run, "run_workflow", db)]
    results = [
        p
        for p in results
        if isinstance(p, dict)
        and p.get("workflow_id") == "deployment-check"
        and str(p.get("status")).lower() == "completed"
    ]
    require(results, "No completed deployment-check tool result")
    result = results[-1]
    stored = db.get_run(result["run_id"], deserialize=False)
    require(
        stored and stored.get("run_data", {}).get("workflow_id") == "deployment-check",
        "Workflow run not persisted under the returned ID",
    )
    require(str(stored["run_data"].get("status")).lower() == "completed", "Persisted workflow run did not complete")
    report = str(result.get("content", ""))
    require(report and "Database" in report and "Runtime" in report, "Workflow result lacks actual check details")
    require(
        stored["run_data"].get("content") == result["content"], "Tool report differs from persisted workflow result"
    )
    output = str(run.content).replace("**", "")
    overall = re.search(r"Overall: \*\*(PASS|WARN|FAIL)\*\*", report)
    require(
        overall and re.search(rf"(?i)overall[^\n]{{0,40}}\b{overall[1]}\b", output),
        "Answer omits or misreports the actual overall status",
    )
    for check in ("Database", "Runtime"):
        status = re.search(r"\*\*(PASS|WARN|FAIL)\*\* " + check + ":", report)
        require(
            status and re.search(rf"(?i)(?:{check}[^\n]{{0,80}}{status[1]}|{status[1]}[^\n]{{0,80}}{check})", output),
            f"Answer does not report the observed {check} status",
        )


def component_id(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    data = result.get("data", result)
    return data.get("id", data.get("component_id")) if isinstance(data, dict) else None


def published(
    name: str,
    *,
    renamed_from: str | None = None,
    tools_required: bool = False,
    model_id: str | None = None,
    instruction_patterns: tuple[str, ...] = (),
) -> Callable[[Any, Any], None]:
    def check(run: Any, db: Any) -> None:
        created = calls(run, "create_agent", db)
        require(len(created) == 1, "Expected exactly one successful create_agent")
        configs = []
        components, _ = db.list_components(limit=1000, include_deleted=True)
        for row in components:
            config = db.get_config(row["component_id"])
            if config and (config.get("config") or {}).get("name") == name:
                configs.append((row, config))
        require(len(configs) == 1, "Expected one stored component with requested name")
        row, config = configs[0]
        require(
            config.get("stage") == "published" and row.get("current_version") == config.get("version"),
            "Component is a draft or current published pointer is missing",
        )
        require(component_id(payload(created[0], db)) == row["component_id"], "Stored ID differs from creation result")
        spec = config["config"]
        instructions = json.dumps(spec.get("instructions") or "")
        require(
            all(re.search(pattern, instructions, re.IGNORECASE) for pattern in instruction_patterns),
            "Published instructions omit requested behavior",
        )
        require(spec.get("model"), "Stored component lacks a model")
        if model_id:
            require(spec["model"].get("id") == model_id, "Stored agent does not use the default model")
        if tools_required:
            require(
                any(
                    t.get("name") in {"parallel_search", "web_search"} or t.get("toolkit") == "parallel_tools"
                    for t in spec.get("tools", [])
                    if isinstance(t, dict)
                ),
                "Stored agent lacks the requested web search capability",
            )
        if renamed_from:
            require(not spec.get("tools"), "Summarizer unexpectedly has tools")
            edits = calls(run, "edit_agent", db)
            require(
                edits
                and all(
                    component_id(payload(t, db)) == row["component_id"]
                    and (t.tool_args or {}).get("agent_id") == row["component_id"]
                    for t in edits
                ),
                "Rename did not edit the original ID",
            )
            first = db.get_config(row["component_id"], version=1)
            require(first and first["config"].get("name") == renamed_from, "Original name absent from version history")
            require(first.get("stage") == "published", "Original version was never published")
            original = {key: value for key, value in first["config"].items() if key not in {"name", "metadata"}}
            renamed = {key: value for key, value in spec.items() if key not in {"name", "metadata"}}
            require(original == renamed, "Rename changed configuration beyond its name and audit metadata")
            require(not any(r.get("name") == renamed_from for r in components), "Original-name duplicate remains")

    return check


def searched(name: str, term: str | None = None) -> Callable[[Any, Any], None]:
    def check(run: Any, db: Any) -> None:
        matches = calls(run, name, db)
        if term:
            matches = [t for t in matches if term in json.dumps(t.tool_args)]
        require(matches, f"No successful {name} lookup" + (f" for {term}" if term else ""))

    return check


def roster(run: Any, db: Any) -> None:
    require(
        all(calls(run, name, db) for name in ("list_agents", "list_teams", "list_workflows"))
        or any(not (t.tool_args or {}).get("component_type") for t in calls(run, "list_components", db)),
        "Missing runtime roster lookup",
    )


class Memory(Behavior):
    def __init__(self, db: Any, team: Any):
        super().__init__(db, lambda run, db: None, readonly=False)
        self.team = team

    async def ascore(self, run: Any, expected: Any = None) -> Score:
        rows = self.db.get_learnings(user_id=self.team.user_id)
        if "Quillhawk-Meridian" not in json.dumps(rows):
            return Score(0, False, "The requested fact was not persisted for the eval user")
        # Fresh team session; the recall prompt contains neither the fact nor the original answer.
        recalled = await self.team.arun("Which rollout do I lead?", session_id=str(uuid4()))
        save_run("agno_recalls_project_fact_fresh_session", recalled)
        if not recalled_fact(str(recalled.content)):
            return Score(0, False, "Persisted fact was not recalled in a fresh session")
        return Score(1, True, "Fact persisted for the correct user and recalled in a fresh session")


def recalled_fact(content: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", content.casefold())
    uncertain = (
        "do not know",
        "don t know",
        "cannot confirm",
        "can t confirm",
        "no record",
        "not sure",
        "do not lead",
        "don t lead",
        "not lead",
    )
    return "quillhawk meridian" in normalized and not any(phrase in normalized for phrase in uncertain)
