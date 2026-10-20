"""Claude and Codex agents for tasks in the provided workspace."""

from pathlib import Path

from agno.agents.base import BaseExternalAgent
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent

from app.sandbox import REPOSITORY, sandbox_provider
from db import get_postgres_db

INSTRUCTIONS = """\
Complete the user's task using the available tools and workspace.
Read applicable workspace instructions and relevant context before acting.
Keep questions and reviews read-only unless changes are requested.
Make focused changes, preserve existing work, and keep credentials private.
Ask only when missing information materially changes the outcome.
Publish, send messages, deploy or change running services only when authorized.
Verify your work with relevant checks. Report results and limitations concisely;
never claim an action or check succeeded without evidence.
"""

db = get_postgres_db()
sandbox = sandbox_provider()
repository = REPOSITORY if sandbox is not None else None
cwd = str(Path(__file__).resolve().parents[1]) if sandbox is None else None

claude_engineer = ClaudeAgent(
    id="claude-engineer",
    name="Claude Engineer",
    model="claude-opus-5-5",
    db=db,
    cwd=cwd,
    sandbox=sandbox,
    repository=repository,
    system_prompt=INSTRUCTIONS,
    permission_mode="acceptEdits",
)
codex_engineer = CodexAgent(
    id="codex-engineer",
    name="Codex Engineer",
    model="gpt-6.1-sol",
    db=db,
    cwd=cwd,
    sandbox=sandbox,
    repository=repository,
    instructions=INSTRUCTIONS,
    sandbox_mode="workspace-write",
)
engineers: list[BaseExternalAgent] = [claude_engineer, codex_engineer]
