"""Shared resources use one database and notes respect AgentOS user isolation."""

import subprocess
import sys
import unittest


class RegistryResources(unittest.TestCase):
    def test_notes_preserve_findings_and_follow_user_isolation(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
from types import SimpleNamespace
from unittest.mock import patch

from agno.agent import Agent
from agno.agent._init import apply_filesystem_user_isolation
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge

db = SqliteDb(db_url="sqlite:///:memory:")
knowledge = Knowledge(name="shared-knowledge")
with (
    patch("db.get_postgres_db", return_value=db),
    patch("db.create_knowledge", return_value=knowledge) as create_knowledge,
):
    from app.registry import registry, shared_knowledge, shared_learning, shared_notes

create_knowledge.assert_called_once_with(name="shared-knowledge", table_name="shared_knowledge")
assert registry.knowledge == [shared_knowledge]
assert registry.learning == [shared_learning]
assert shared_learning.db is db
assert shared_notes.backend.db is db
shared_notes_tools = next(tool for tool in registry.tools if getattr(tool, "fs", None) is shared_notes)
assert registry.tool_is_declared(shared_notes_tools.name)
assert "delete_file" not in shared_notes_tools.functions
agent = Agent(id="notes-test", tools=[shared_notes_tools])
apply_filesystem_user_isolation(agent, True)
alice = SimpleNamespace(user_id="alice")
bob = SimpleNamespace(user_id="bob")
shared_notes_tools.append_file("research/findings.md", "First finding", run_context=alice)
assert shared_notes_tools.read_file("research/findings.md", run_context=bob).startswith("Error:")
shared_notes_tools.append_file("research/findings.md", "Second finding", run_context=alice)
contents = shared_notes_tools.read_file("research/findings.md", run_context=alice)
assert "First finding" in contents and "Second finding" in contents
assert "First finding" in shared_notes.resolve(user_id="alice").read("research/findings.md")
assert shared_notes_tools.read_file("../outside.md", run_context=alice).startswith("Error:")
db.db_engine.dispose()
""",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
