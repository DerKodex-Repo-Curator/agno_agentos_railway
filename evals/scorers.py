"""Behavioral gates over actual tool payloads and durable state, before database cleanup."""

import json
import re
from collections.abc import Callable, Iterator
from copy import deepcopy
from typing import Any

from agno.offload import ResultStore
from agno.run.agent import RunOutput
from agno.scorer.base import Score

from evals.hooks import business_state


def tool_calls(run: Any, db: Any = None, seen: set[str] | None = None) -> Iterator[Any]:
    seen = set() if seen is None else seen
    yield from run.tools or []
    for member in getattr(run, "member_responses", None) or []:
        yield from tool_calls(member, db, seen)
    # Standalone application-agent dispatch is not a team member response. Follow
    # its persisted run so a plausible child answer cannot replace tool evidence.
    for tool in run.tools or []:
        if db is None or tool.tool_name != "run_agent" or not successful(tool, db):
            continue
        result = payload(tool, db)
        require(isinstance(result, dict) and result.get("run_id"), "Dispatched agent lacks a run ID")
        if result["run_id"] in seen:
            continue
        seen.add(result["run_id"])
        stored = db.get_run(result["run_id"], deserialize=False)
        data = (stored or {}).get("run_data", {})
        require(
            data.get("agent_id") == (tool.tool_args or {}).get("agent_id")
            and str(data.get("status", "")).lower() == "completed",
            "Dispatched agent run is missing, incomplete or belongs to another agent",
        )
        yield from tool_calls(RunOutput.from_dict(deepcopy(data)), db, seen)


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
    return [tool for tool in tool_calls(run, db) if tool.tool_name == name and successful(tool, db)]


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
    def __init__(
        self,
        db: Any,
        check: Callable[[Any, Any], None],
        *,
        allow_agent: str | None = None,
    ):
        self.db, self.check = db, check
        self.allow_agent = allow_agent
        self.before: dict[str, list[str]] | None = None

    def setup(self) -> None:
        self.before = business_state(self.db)

    async def ascore(self, run: Any, expected: Any = None) -> Score:
        try:
            require(self.before is not None, "Missing pre-run snapshot")
            forbidden = [
                t.tool_name
                for t in tool_calls(run, self.db)
                if t.tool_name.startswith(MUTATIONS)
                or (
                    t.tool_name.startswith("run_")
                    and t.tool_name != "run_diagnostics"
                    and not (
                        self.allow_agent
                        and t.tool_name == "run_agent"
                        and (t.tool_args or {}).get("agent_id") == self.allow_agent
                    )
                )
            ]
            require(not forbidden, f"Read-only request attempted mutations/dispatch: {forbidden}")
            after = business_state(self.db)
            changed = [
                key for key in set(self.before or {}) | set(after) if (self.before or {}).get(key) != after.get(key)
            ]
            require(not changed, f"Read-only request changed durable state: {changed}")
            self.check(run, self.db)
            return Score(1, True, "Tool evidence and durable-state checks passed")
        except AssertionError as exc:
            return Score(0, False, str(exc))


def read_file(path: str) -> Callable[[Any, Any], None]:
    def check(run: Any, db: Any) -> None:
        matches = [t for t in calls(run, "read_file", db) if (t.tool_args or {}).get("path", "").lstrip("./") == path]
        require(matches, f"No successful read of {path}")

    return check


def focused_explanation(*, configured: bool = False) -> Callable[[Any, Any], None]:
    """Bound conceptual lookups, including delegated work; accuracy is judged by the Case."""

    def check(run: Any, db: Any) -> None:
        tools = list(tool_calls(run, db))
        allowed = {
            "delegate_task_to_member",
            "search_knowledge_base",
            "read_file",
            "list_files",
            "search_content",
            "search_docs",
            "read_result",
        }
        require(len(tools) <= 4, "Explanation exceeded four calls including delegates")
        require(all(t.tool_name in allowed for t in tools), "Explanation expanded beyond focused lookups")
        require(all(successful(t, db) for t in tools), "Explanation contains failed lookups")
        require(20 <= len(str(run.content).split()) <= 200, "Explanation must be 20–200 words")
        if configured:
            read_file("app/registry.py")(run, db)

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


def searched(name: str, term: str | None = None) -> Callable[[Any, Any], None]:
    def check(run: Any, db: Any) -> None:
        matches = calls(run, name, db)
        if term:
            matches = [t for t in matches if term in json.dumps(t.tool_args)]
        require(matches, f"No successful {name} lookup" + (f" for {term}" if term else ""))

    return check


class Proposal:
    """Controlled local Source; verify the persisted proposal, evidence and no execution."""

    def __init__(self, db: Any, *, user_id: str | None = None):
        self.db = db
        self.user_id = user_id
        self.before: dict[str, list[str]] = {}

    def setup(self) -> None:
        from pathlib import Path
        from time import time

        from agno.company import CompanyManager

        fixture = Path.cwd() / "release-fixture"
        fixture.mkdir(exist_ok=True)
        (fixture / "release.md").write_text(
            "# Fixture release 9.9.9\nReplace RETIRED_TIMEOUT with REQUEST_TIMEOUT in application configuration.\n"
        )
        self.db.create_product(
            {"id": "eval-release", "name": "Fixture release", "user_id": self.user_id, "created_at": int(time())}
        )
        self.db.create_source(
            {
                "id": "eval-release-source",
                "product_id": "eval-release",
                "user_id": self.user_id,
                "type": "markdown",
                "reference": str(fixture),
                "created_at": int(time()),
            }
        )
        CompanyManager(self.db).get_wiki("eval-release")
        self.before = business_state(self.db)

    async def ascore(self, run: Any, expected: Any = None) -> Score:
        try:
            reads = [
                payload(t, self.db)
                for t in calls(run, "read_company_source", self.db)
                if (t.tool_args or {}).get("source_id") == "eval-release-source"
            ]
            reads = [r for r in reads if isinstance(r, dict) and r.get("content") and r.get("content_hash")]
            require(reads, "No successful fixture content read")
            require(calls(run, "intake_company_source", self.db), "No successful evidence-backed intake")
            projects, _ = self.db.get_projects(product_id="eval-release")
            tasks, _ = self.db.get_tasks(product_id="eval-release")
            require(len(projects) == len(tasks) == 1, "Expected one Project and one Task")
            project, task = projects[0], tasks[0]
            require(project["status"] == "proposed", "Project was accepted")
            require(task["status"] == "backlog" and not task.get("transitions"), "Task left Backlog")
            require(task["project_id"] == project["id"] and not task.get("accepted_by"), "Wrong or accepted Task")
            evidence = task.get("evidence") or []
            require(
                any(
                    e.get("source_id") == "eval-release-source"
                    and e.get("run_id") == run.run_id
                    and any(
                        e.get("link") == r.get("link") and e.get("content_hash") == r["content_hash"] for r in reads
                    )
                    for e in evidence
                ),
                "Stored evidence does not match the observed Source",
            )
            require("REQUEST_TIMEOUT" in str(task.get("brief")), "Proposal misses the fixture change")
            allowed = {"propose_company_project", "intake_company_source"}
            require(
                not any(
                    t.tool_name.startswith((*MUTATIONS, "run_")) and t.tool_name not in allowed
                    for t in tool_calls(run, self.db)
                ),
                "Unexpected mutation or dispatch attempt",
            )
            after = business_state(self.db)
            # Only the two fixture proposals may change; preserve all other business state.
            for table in (self.db.projects_table_name, self.db.tasks_table_name):
                key = f"{self.db.db_schema}.{table}"
                after[key] = [row for row in after.get(key, []) if json.loads(row).get("product_id") != "eval-release"]
                if not after[key]:
                    after.pop(key)
            require(after == self.before, "Proposal changed unrelated business state")
            return Score(1, True, "One unaccepted proposal with persisted Source evidence")
        except AssertionError as exc:
            return Score(0, False, str(exc))
