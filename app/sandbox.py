"""Optional Docker and AgentCore sandboxes."""

from os import getenv
from pathlib import Path

from agno.sandbox import Repository, Sandbox
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox

REPOSITORY = Repository("https://github.com/agno-agi/agentos-railway.git", branch="main")
LOCAL_CHECKPOINTS = Path(__file__).resolve().parents[1] / "tmp" / "checkpoints"
PRODUCTION_VOLUME = Path("/data")


def sandbox_provider() -> Sandbox | None:
    runtime = getenv("RUNTIME_ENV", "prd")
    enabled = getenv("SANDBOX_ENABLED", "false").lower()
    runtime_arn = getenv("SANDBOX_RUNTIME_ARN", "")
    if runtime not in {"dev", "prd"}:
        raise ValueError("RUNTIME_ENV must be dev or prd")
    if enabled not in {"true", "false"}:
        raise ValueError("SANDBOX_ENABLED must be true or false")
    if runtime == "dev" and runtime_arn:
        raise ValueError("SANDBOX_RUNTIME_ARN requires RUNTIME_ENV=prd")
    if runtime == "prd" and enabled == "true":
        raise ValueError("SANDBOX_ENABLED is for development; use SANDBOX_RUNTIME_ARN in production")
    if runtime == "dev" and enabled == "true":
        return DockerSandbox(
            image=getenv("SANDBOX_IMAGE") or "agno-sandbox:local",
            network="isolated",
            workspace_mb=2048,
            checkpoints=FileCheckpointStore(LOCAL_CHECKPOINTS),
            env={"GITHUB_READ_TOKEN": token} if (token := getenv("GITHUB_READ_TOKEN")) else None,
        )
    if runtime_arn:
        from agno.sandbox.agentcore import AgentCoreSandbox

        if not PRODUCTION_VOLUME.is_mount():
            raise ValueError(f"Mount a persistent volume at {PRODUCTION_VOLUME} before enabling AgentCore")
        env = {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": getenv("AWS_REGION", "us-east-1")}
        if token := getenv("GITHUB_READ_TOKEN"):
            env["GITHUB_READ_TOKEN"] = token
        return AgentCoreSandbox(
            runtime_arn=runtime_arn,
            env=env,
            checkpoints=FileCheckpointStore(PRODUCTION_VOLUME / "checkpoints"),
        )
    return None
