"""Optional engineering executors: Docker in development, AgentCore in production."""

from os import getenv
from pathlib import Path

from agno.agents.base import BaseExternalAgent
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.sandbox import Repository, Sandbox
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox

from db import get_postgres_db


def sandbox_provider() -> Sandbox | None:
    runtime = getenv("RUNTIME_ENV", "prd")
    if runtime == "dev" and getenv("SANDBOX_ENABLED", "").lower() == "true":
        return DockerSandbox(
            image=getenv("SANDBOX_IMAGE") or "agno-sandbox:local",
            network="isolated",
            workspace_mb=2048,
            checkpoints=FileCheckpointStore(Path(getenv("SANDBOX_CHECKPOINTS") or "./tmp/checkpoints")),
            env={"GITHUB_READ_TOKEN": token} if (token := getenv("GITHUB_READ_TOKEN")) else None,
        )
    if runtime == "prd" and (runtime_arn := getenv("SANDBOX_RUNTIME_ARN")):
        from agno.sandbox.agentcore import AgentCoreSandbox

        checkpoint_path = getenv("SANDBOX_CHECKPOINTS")
        if not checkpoint_path:
            raise ValueError("SANDBOX_CHECKPOINTS must point to a persistent volume in production")
        env = {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": getenv("AWS_REGION", "us-east-1")}
        if token := getenv("GITHUB_READ_TOKEN"):
            env["GITHUB_READ_TOKEN"] = token
        return AgentCoreSandbox(
            runtime_arn=runtime_arn,
            env=env,
            checkpoints=FileCheckpointStore(Path(checkpoint_path)),
        )
    return None


def engineering_agents() -> list[BaseExternalAgent]:
    provider = sandbox_provider()
    if provider is None:
        return []
    repository = Repository("https://github.com/agno-agi/agno", branch="main")
    return [
        CodexAgent(
            id="codex-engineer",
            name="Codex Engineer",
            db=get_postgres_db(),
            sandbox=provider,
            repository=repository,
            sandbox_mode="workspace-write",
        ),
        ClaudeAgent(
            id="claude-engineer",
            name="Claude Engineer",
            db=get_postgres_db(),
            sandbox=provider,
            repository=repository,
            permission_mode="acceptEdits",
        ),
    ]
