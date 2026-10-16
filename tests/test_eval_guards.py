"""Adversarial checks: plausible answers and fired tools must not fool the suite."""

import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from evals.scorers import (
    Behavior,
    Memory,
    health,
    onboarding,
    published,
    read_file,
    recalled_fact,
    source_read,
    successful,
)


def tool(name, result, args=None, error=False):
    return NS(tool_name=name, result=json.dumps(result), tool_args=args or {}, tool_call_error=error)


def run(*tools, content="Success", members=None):
    return NS(tools=list(tools), member_responses=members, content=content)


class ScorerTests(unittest.IsolatedAsyncioTestCase):
    def test_recall_accepts_typography_but_not_negated_memory(self):
        self.assertTrue(recalled_fact("You lead the Quillhawk–Meridian rollout."))
        self.assertTrue(recalled_fact("Quillhawk-Meridian."))
        self.assertFalse(recalled_fact("I cannot confirm you lead Quillhawk-Meridian."))
        self.assertFalse(recalled_fact("You lead an unknown rollout."))

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

    def test_health_prose_and_wrong_workflow_cannot_pass(self):
        db = MagicMock()
        for response in (
            run(content="Database PASS"),
            run(
                tool(
                    "run_workflow",
                    {"workflow_id": "run-evals", "status": "completed", "run_id": "x", "content": "Database Runtime"},
                )
            ),
        ):
            with self.assertRaises(AssertionError):
                health(response, db)
        db.get_run.return_value = None
        with self.assertRaises(AssertionError):
            health(
                run(
                    tool(
                        "run_workflow",
                        {
                            "workflow_id": "deployment-check",
                            "status": "completed",
                            "run_id": "x",
                            "content": "Database Runtime",
                        },
                    )
                ),
                db,
            )

    def test_failed_and_unrelated_source_reads_cannot_pass(self):
        db = MagicMock()
        db.db_engine.connect.return_value.__enter__.return_value.execute.return_value.mappings.return_value = [
            {"id": "releases", "product_id": "this-agentos", "reference": "https://github.com/agno-agi/agno/releases"}
        ]
        url = "https://github.com/agno-agi/agno/releases"
        good = {"source_id": "releases", "link": url, "content": "Latest v3.1.5", "content_hash": "abc"}
        cases = [
            tool("read_company_source", {"data": [{"path": url}]}, {"source_id": "releases"}),
            tool("read_company_source", good, {"source_id": "wrong", "path": url}),
            tool("read_company_source", {"ok": False}, {"source_id": "releases", "path": url}),
            tool("read_company_source", {**good, "content": ""}, {"source_id": "releases", "path": url}),
        ]
        for candidate in cases:
            with self.assertRaises(AssertionError):
                source_read(run(candidate, content=f"v3.1.5 {url}"), db)
        source_read(
            run(tool("read_company_source", good, {"source_id": "releases", "path": url}), content=f"v3.1.5 {url}"), db
        )
        with self.assertRaises(AssertionError):
            source_read(
                run(tool("read_company_source", good, {"source_id": "releases", "path": url}), content=f"v9.9.9 {url}"),
                db,
            )

    def test_draft_and_wrong_published_pointer_fail(self):
        db = MagicMock()
        row = {"component_id": "a", "current_version": 1}
        db.list_components.return_value = ([row], 1)
        config = {"stage": "draft", "version": 1, "config": {"name": "Test", "model": "default"}}
        db.get_config.return_value = config
        response = run(tool("create_agent", {"component_id": "a"}), content="Created and published")
        with self.assertRaises(AssertionError):
            published("Test")(response, db)
        config["stage"] = "published"
        published("Test")(response, db)
        row["current_version"] = 2
        with self.assertRaises(AssertionError):
            published("Test")(response, db)

    def test_missing_search_tools_and_replacement_rename_fail(self):
        db = MagicMock()
        db.list_components.return_value = ([{"component_id": "a", "current_version": 2}], 1)
        db.get_config.return_value = {
            "stage": "published",
            "version": 2,
            "config": {"name": "After", "model": "default"},
        }
        response = run(tool("create_agent", {"component_id": "a"}))
        with self.assertRaises(AssertionError):
            published("After", tools_required=True)(response, db)
        response.tools.append(tool("edit_agent", {"component_id": "replacement"}, {"agent_id": "replacement"}))
        with self.assertRaises(AssertionError):
            published("After", renamed_from="Before")(response, db)

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

    def test_rename_preserves_configuration_and_published_history(self):
        db = MagicMock()
        db.list_components.return_value = ([{"component_id": "original", "current_version": 2}], 1)
        first = {
            "stage": "published",
            "version": 1,
            "config": {"name": "Before", "model": "default", "instructions": "Summarize"},
        }
        final = {
            "stage": "published",
            "version": 2,
            "config": {"name": "After", "model": "default", "instructions": "Summarize"},
        }
        response = run(
            tool("create_agent", {"data": {"id": "original"}}),
            tool("edit_agent", {"data": {"id": "original"}}, {"agent_id": "original"}),
        )
        db.get_config.side_effect = [final, first]
        published("After", renamed_from="Before")(response, db)
        final["config"] = {"name": "After", "model": "default", "instructions": "Do something else"}
        db.get_config.side_effect = [final, first]
        with self.assertRaises(AssertionError):
            published("After", renamed_from="Before")(response, db)

    def test_read_file_must_match_and_succeed(self):
        for candidate in (
            tool("read_file", "content", {"path": "tmp/answers.md"}),
            tool("read_file", "Error: missing", {"path": "README.md"}),
        ):
            with self.assertRaises(AssertionError):
                read_file("README.md")(run(candidate), None)

    async def test_memory_acknowledgement_without_persistence_fails(self):
        db = MagicMock()
        db.get_learnings.return_value = []
        team = NS(user_id="isolated")
        score = await Memory(db, team).ascore(run(content="I will remember Quillhawk-Meridian"))
        self.assertFalse(score.passed)

    async def test_memory_requires_fresh_session_recall(self):
        db = MagicMock()
        db.get_learnings.return_value = [{"fact": "Quillhawk-Meridian"}]
        seen = []

        async def recall(prompt, session_id):
            seen.append((prompt, session_id))
            return NS(content="I do not know")

        score = await Memory(db, NS(user_id="isolated", arun=recall)).ascore(run())
        self.assertFalse(score.passed)
        self.assertNotIn("Quillhawk-Meridian", seen[0][0])
        self.assertTrue(seen[0][1])


if __name__ == "__main__":
    unittest.main()
