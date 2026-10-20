"""Adversarial checks: plausible answers and fired tools must not fool the suite."""

import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from evals.scorers import (
    Behavior,
    Proposal,
    focused_explanation,
    onboarding,
    read_file,
    searched,
    successful,
)


def tool(name, result, args=None, error=False):
    return NS(tool_name=name, result=json.dumps(result), tool_args=args or {}, tool_call_error=error)


def run(*tools, content="Success", members=None):
    return NS(tools=list(tools), member_responses=members, content=content)


class ScorerTests(unittest.IsolatedAsyncioTestCase):
    def test_focused_explanation_counts_delegates_and_rejects_audits(self):
        answer = (
            "Agno learning stores useful information outside model weights and retrieves it in later interactions. "
            "It does not retrain the underlying language model."
        )
        check = focused_explanation()
        check(run(content=answer), None)
        for response in (
            run(tool("run_diagnostics", {"ok": True}), content=answer),
            run(tool("read_file", "Error: missing"), content=answer),
            run(
                tool("delegate_task_to_member", "answer"),
                members=[run(*(tool("read_file", "content") for _ in range(4)))],
                content=answer,
            ),
        ):
            with self.assertRaises(AssertionError):
                check(response, None)

    def test_configured_explanation_requires_successful_relevant_read(self):
        answer = (
            "app/registry.py configures shared_learning with agentic user profiles and user memories in PostgreSQL. "
            "It stores information outside model weights and does not retrain the model."
        )
        check = focused_explanation(configured=True)
        for candidate in (
            tool("read_file", "content", {"path": "app/settings.py"}),
            tool("read_file", "Error: missing", {"path": "app/registry.py"}),
        ):
            with self.assertRaises(AssertionError):
                check(run(candidate, content=answer), None)
        check(
            run(
                tool("delegate_task_to_member", "answer"),
                members=[run(tool("read_file", "configuration", {"path": "app/registry.py"}))],
                content=answer,
            ),
            None,
        )

    def test_error_envelopes_are_not_success(self):
        for result in ({"ok": False}, {"error": "missing"}, {"status": "FAILED"}):
            self.assertFalse(successful(tool("create_agent", result)))
        self.assertFalse(successful(tool("create_agent", {"ok": True}, error=True)))
        self.assertTrue(successful(tool("create_agent", {"ok": True})))

    async def test_readonly_rejects_attempt_even_if_no_write_landed(self):
        scorer = Behavior(None, lambda r, db: None)
        with patch("evals.scorers.business_state", return_value={}):
            scorer.setup()
            result = await scorer.ascore(run(tool("create_agent", {"ok": False}), content="I refused"))
        self.assertFalse(result.passed)

    async def test_readonly_detects_company_and_note_changes_without_tool_trace(self):
        for table in ("agno_company_projects", "agno_company_tasks", "agno_company_sources", "agno_fs"):
            scorer = Behavior(None, lambda r, db: None)
            with patch("evals.scorers.business_state", side_effect=[{}, {table: ["new row"]}]):
                scorer.setup()
                result = await scorer.ascore(run(content="Nothing changed"))
            self.assertFalse(result.passed, table)

    async def test_member_mutations_are_checked(self):
        scorer = Behavior(None, lambda r, db: None)
        with patch("evals.scorers.business_state", return_value={}):
            scorer.setup()
            result = await scorer.ascore(run(members=[run(tool("publish_component", {"ok": True}))]))
        self.assertFalse(result.passed)

    async def test_readonly_diagnostics_are_not_component_execution(self):
        for name, allowed in (("run_diagnostics", True), ("run_agent", False), ("run_workflow", False)):
            scorer = Behavior(None, lambda r, db: None)
            with patch("evals.scorers.business_state", return_value={}):
                scorer.setup()
                result = await scorer.ascore(run(tool(name, {"ok": True})))
            self.assertEqual(result.passed, allowed, name)
        scorer = Behavior(None, lambda r, db: None)
        with patch("evals.scorers.business_state", side_effect=[{}, {"fs.agno_fs": ["unexpected write"]}]):
            scorer.setup()
            result = await scorer.ascore(run(tool("run_diagnostics", {"ok": True})))
        self.assertFalse(result.passed)

    async def test_readonly_agent_dispatch_requires_persisted_child_evidence(self):
        db = MagicMock()
        response = run(tool("run_agent", {"run_id": "child"}, {"agent_id": "fixture-reader"}))
        child = {
            "run_id": "child",
            "agent_id": "fixture-reader",
            "status": "COMPLETED",
            "tools": [{"tool_name": "read_company_source", "result": "page content", "tool_args": {}}],
        }
        scorer = Behavior(db, searched("read_company_source"), allow_agent="fixture-reader")
        with patch("evals.scorers.business_state", return_value={}):
            scorer.setup()
            db.get_run.return_value = None
            self.assertFalse((await scorer.ascore(response)).passed)
            db.get_run.return_value = {"run_data": child}
            self.assertTrue((await scorer.ascore(response)).passed)
            child["agent_id"] = "different-agent"
            self.assertFalse((await scorer.ascore(response)).passed)
            child["agent_id"] = "fixture-reader"
            child["tools"] = [{"tool_name": "create_company_project", "result": "created", "tool_args": {}}]
            self.assertFalse((await scorer.ascore(response)).passed)

    async def test_proposal_requires_matching_evidence_and_no_execution(self):
        for defect in (None, "hash", "run", "accepted", "transition", "dispatch", "unrelated_write"):
            with self.subTest(defect=defect):
                evidence = {
                    "source_id": "eval-release-source",
                    "run_id": "observed-run",
                    "link": "release.md",
                    "content_hash": "observed-hash",
                }
                task = {
                    "project_id": "proposal",
                    "status": "backlog",
                    "brief": "Use REQUEST_TIMEOUT",
                    "evidence": [evidence],
                }
                response = run(
                    tool(
                        "read_company_source",
                        {"content": "Use REQUEST_TIMEOUT", "link": "release.md", "content_hash": "observed-hash"},
                        {"source_id": "eval-release-source"},
                    ),
                    tool("intake_company_source", {"task_id": "task"}),
                )
                response.run_id = "observed-run"
                db = MagicMock(db_schema="ai", projects_table_name="projects", tasks_table_name="tasks")
                db.get_projects.return_value = ([{"id": "proposal", "status": "proposed"}], 1)
                db.get_tasks.return_value = ([task], 1)
                state = {}
                if defect == "hash":
                    evidence["content_hash"] = "fabricated-hash"
                elif defect == "run":
                    evidence["run_id"] = "different-run"
                elif defect == "accepted":
                    task["accepted_by"] = "someone"
                elif defect == "transition":
                    task["transitions"] = [{"to": "running"}]
                elif defect == "dispatch":
                    response.tools.append(tool("run_agent", {"ok": False}, error=True))
                elif defect == "unrelated_write":
                    state = {"ai.products": ["unexpected change"]}
                with patch("evals.scorers.business_state", return_value=state):
                    score = await Proposal(db).ascore(response)
                self.assertEqual(score.passed, defect is None, score.reason)

    def test_onboarding_requires_grounded_actionable_paths(self):
        response = run(
            tool("read_file", "README contents", {"path": "README.md"}), content="Use Docker, chat and create agents."
        )
        with self.assertRaises(AssertionError):
            onboarding(response, None)
        response.content = (
            "Copy example.env to .env; set OPENAI_API_KEY; docker compose up --build. os.agno.com; /create-agent"
        )
        onboarding(response, None)
        response.tools = []
        with self.assertRaises(AssertionError):
            onboarding(response, None)

    def test_read_file_must_match_and_succeed(self):
        for candidate in (
            tool("read_file", "content", {"path": "tmp/answers.md"}),
            tool("read_file", "Error: missing", {"path": "README.md"}),
        ):
            with self.assertRaises(AssertionError):
                read_file("README.md")(run(candidate), None)


if __name__ == "__main__":
    unittest.main()
