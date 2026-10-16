"""Postgres checks run with EVAL_TEST_POSTGRES=true; all writes use owned databases."""

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from evals.isolation import ROOT, isolated_environment, require_isolation, run_isolated, source_copy
from evals.scorers import Behavior, searched


class IsolationGuards(unittest.TestCase):
    def test_shared_database_is_rejected(self):
        with patch.dict(os.environ, {"DB_DATABASE": "ai", "RAILWAY_EVAL_DATABASE": "ai"}):
            with self.assertRaises(RuntimeError):
                require_isolation()

    def test_source_copy_excludes_answers_secrets_and_symlinks(self):
        with tempfile.TemporaryDirectory() as destination:
            source_copy(Path(destination))
            files = {str(p.relative_to(destination)) for p in Path(destination).rglob("*") if p.is_file()}
            self.assertIn("app/main.py", files)
            self.assertIn("README.md", files)
            self.assertFalse(any(p.startswith(("evals/", "tests/", "tmp/", ".git/")) for p in files))
            self.assertNotIn(".env", files)
            self.assertFalse(any(p.is_symlink() for p in Path(destination).rglob("*")))


@unittest.skipUnless(os.getenv("EVAL_TEST_POSTGRES") == "true", "requires local Postgres with CREATEDB")
class PostgresIsolation(unittest.IsolatedAsyncioTestCase):
    engine: Engine

    @classmethod
    def setUpClass(cls):
        load_dotenv(ROOT / ".env")
        from db.url import db_url

        cls.engine = create_engine(db_url)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def databases(self):
        with self.engine.connect() as conn:
            return set(
                conn.execute(text("SELECT datname FROM pg_database WHERE datname LIKE 'railway_eval_%'")).scalars()
            )

    def test_two_owners_never_sweep_each_other(self):
        with isolated_environment() as (first, _):
            owned = create_engine(self.engine.url.set(database=first["DB_DATABASE"]))
            try:
                with owned.begin() as conn:
                    conn.execute(text("CREATE TABLE public.sentinel (value text)"))
                    conn.execute(text("INSERT INTO public.sentinel VALUES ('keep me')"))
                with isolated_environment() as (second, directory):
                    self.assertNotEqual(first["DB_DATABASE"], second["DB_DATABASE"])
                    rejected = subprocess.run(
                        [sys.executable, "-m", "evals.worker", "--list"],
                        cwd=directory,
                        env={**second, "RAILWAY_EVAL_TOKEN": "wrong"},
                        capture_output=True,
                    )
                    self.assertNotEqual(rejected.returncode, 0)
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            """
from evals.isolation import require_isolation
require_isolation()
from app.main import agent_os, manager_team
from app.company import products
from app.knowledge import shared_knowledge, product_knowledge
from app.registry import registry
from app.notes import notes
from db import get_postgres_db
import os
assert agent_os.db is get_postgres_db()
assert agent_os.company.db is agent_os.db
assert agent_os.queue.db is agent_os.db
for kb in (shared_knowledge, product_knowledge):
    assert kb.contents_db.db_engine.url.database == os.environ['DB_DATABASE']
    assert kb.vector_db.db_engine.url.database == os.environ['DB_DATABASE']
assert notes.backend.db_engine.url.database == os.environ['DB_DATABASE']
assert not any(a.id in ('codex-engineer', 'claude-engineer') for a in agent_os.agents)
assert not agent_os.interfaces
assert not products[0].routines
assert not any(type(t).__name__ in ('OpenAITools', 'SlackTools') for t in registry.tools)
assert not any(type(t).__name__ == 'KnowledgeManagementTools' for t in manager_team.tools)
""",
                        ],
                        cwd=directory,
                        env=second,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn(second["DB_DATABASE"], self.databases())
                with owned.connect() as conn:
                    self.assertEqual(conn.scalar(text("SELECT value FROM public.sentinel")), "keep me")
            finally:
                owned.dispose()
        self.assertNotIn(first["DB_DATABASE"], self.databases())

    async def test_failed_worker_cleans_only_its_database(self):
        before = self.databases()
        code, _ = await run_isolated(["--name", "not-a-case"], capture=True)
        self.assertEqual(code, 2)
        self.assertEqual(self.databases(), before)

    def test_optional_capabilities_require_explicit_flags(self):
        # CompanyTools initializes tables, so even configuration checks use an owned DB.
        with isolated_environment() as (env, directory):
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    """
import importlib
import os
from app import company
from app.tools import get_media_tools, get_slack_tools
os.environ.update(OPENAI_API_KEY='test-key-no-requests', SLACK_BOT_TOKEN='test-token-no-requests')
for enabled in ('', 'false', 'true'):
    os.environ.update(ENABLE_MAINTENANCE=enabled, ENABLE_MEDIA_TOOLS=enabled, ENABLE_SLACK_TOOLS=enabled)
    configured = importlib.reload(company)
    assert len(configured.products[0].routines) == (3 if enabled == 'true' else 0)
    assert bool(get_media_tools()) == (enabled == 'true')
    assert bool(get_slack_tools()) == (enabled == 'true')
""",
                ],
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    async def test_readonly_gate_detects_real_company_and_notebook_writes(self):
        from agno.company import CompanyManager
        from agno.db.postgres import PostgresDb
        from agno.fs import FileSystem

        with isolated_environment() as (env, _):
            owned = create_engine(self.engine.url.set(database=env["DB_DATABASE"]))
            try:
                db = PostgresDb(db_engine=owned)
                db.create_product({"id": "sentinel", "name": "Sentinel", "created_at": 1})
                company = CompanyManager(db)
                company.get_wiki()
                company.get_wiki("sentinel")
                scorer = Behavior(db, lambda run, db: None)
                scorer.setup()
                company.read_wiki(None, "status.md")
                company.read_wiki("sentinel", "status.md")
                response = SimpleNamespace(tools=[], member_responses=[], content="I did not change anything")
                self.assertTrue((await scorer.ascore(response)).passed)
                company.write_wiki(
                    product_id="sentinel", path="status.md", content="unexpected update", expected_version=1
                )
                self.assertFalse((await scorer.ascore(response)).passed)
                scorer.setup()
                db.create_project(
                    {
                        "id": "unexpected",
                        "product_id": "sentinel",
                        "name": "Unexpected",
                        "status": "proposed",
                        "created_at": 1,
                    }
                )
                self.assertFalse((await scorer.ascore(response)).passed)
                scorer.setup()
                FileSystem(db, namespace="shared-notes").write("unexpected.txt", "unexpected note")
                self.assertFalse((await scorer.ascore(response)).passed)
            finally:
                owned.dispose()

    async def test_timeout_and_cancellation_remove_database_after_child_exit(self):
        before = self.databases()
        with self.assertRaises(TimeoutError):
            await run_isolated(["--list"], capture=True, timeout=0)
        self.assertEqual(self.databases(), before)
        task = asyncio.create_task(run_isolated(["--list"], capture=True))
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.databases(), before)

    async def test_dispatched_source_evidence_comes_from_a_persisted_run(self):
        from agno.db.postgres import PostgresDb
        from agno.models.response import ToolExecution
        from agno.run import RunStatus
        from agno.run.agent import RunOutput
        from agno.session import AgentSession

        with isolated_environment() as (env, _):
            owned = create_engine(self.engine.url.set(database=env["DB_DATABASE"]))
            try:
                db = PostgresDb(db_engine=owned)
                db.upsert_session(
                    AgentSession(session_id="child-session", agent_id="company-analyst", created_at=1, updated_at=1)
                )
                db.upsert_run(
                    RunOutput(
                        run_id="child",
                        agent_id="company-analyst",
                        status=RunStatus.completed,
                        tools=[ToolExecution(tool_name="read_company_source", result="page content")],
                    ),
                    session_id="child-session",
                )
                response = RunOutput(
                    tools=[
                        ToolExecution(
                            tool_name="run_agent",
                            tool_args={"agent_id": "company-analyst"},
                            result='{"run_id":"child"}',
                        )
                    ]
                )
                scorer = Behavior(db, searched("read_company_source"), allow_agent="company-analyst")
                scorer.setup()
                score = await scorer.ascore(response)
                self.assertTrue(score.passed, score.reason)
            finally:
                owned.dispose()


if __name__ == "__main__":
    unittest.main()
