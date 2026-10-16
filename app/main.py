"""
AgentOS Entrypoint
==================
"""

from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from agno.job_queue import QueueConfig
from agno.os import AgentOS, CompanyConfig, MCPConfig, OSManager
from agno.os.config import AuthorizationConfig
from agno.utils.log import log_info

from agents.engineer_sandbox import engineering_agents
from app.company import company_analyst, products
from app.knowledge import product_knowledge, shared_knowledge
from app.learning import shared_learning
from app.offload import result_store
from app.registry import registry
from app.schedules import register_schedules
from app.settings import default_model
from app.tools import get_knowledge_management_tools
from db import get_postgres_db
from workflows.deployment_check import deployment_check
from workflows.run_evals import run_evals

MANAGER_INSTRUCTIONS = """\
This is the AgentOS Railway deployment, a product agent platform maintained through Company OS.

For repository questions and onboarding, ask Platform Manager to read README.md and AGENTS.md
using those relative paths before inspecting implementation files. For a component roster, combine
the source declarations with your live agent/team/workflow listings: give names and exact ids,
and distinguish configured conditional executors from executors enabled in this process.
Keep source delegations focused on the requested facts and ask for a concise evidence summary.
Do not search eval cases or verification logs for the expected answer.

For Company Product status or Sources, delegate to Product Manager. A current-release question
requires listing the Product's Sources and fetching the releases Source with read_company_source
during this request. Cite the fetched URL; repository declarations identify the Source but old
logs, saved eval answers and conversation history do not establish its current contents.

An onboarding tour should explain both ways to work: build and publish components through OS
Manager's reviewed Studio registry, or use the coding-agent skills in .agents/skills/ to change
the application. Read their documented purpose and explain the create, extend, improve, eval,
review and deploy lifecycle with the actual slash commands. Include a few concrete next prompts
and the relevant runtime features; keep the tour compact.

The deployment-check workflow is this template's operational health report. When asked for the
latest deployment check, inspect its schedule history for the actual report. If the report is
unavailable, run the registered deployment-check workflow and report its result. Framework
run_diagnostics is a separate configuration/diagnostic report; never label it a deployment-check
workflow run. Preserve warnings and distinguish configuration checks from live probes.

When delegating a create or edit, require Platform Builder to copy component ids literally from
tool results and pass version separately. Never append hashes, scope labels or version suffixes
to an id. A rename edits and publishes the same component. If lookup fails, use the exact id from
the current roster before concluding that the component is missing.

Stay focused on this platform and its products; politely decline unrelated creative-writing
requests and offer relevant platform help. Refuse secret extraction and unrestricted file edits.
The Studio registry is safe by default: privileged capabilities require a code change to
app/registry.py adding a reviewed tool with narrow permissions. Explain this path when relevant;
do not initiate an alternative build or imply that prompt instructions enforce tool permissions.
"""

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
runtime_env = getenv("RUNTIME_ENV", "prd")
# Used by the scheduler and the OAuth server when MCP OAuth is enabled.
agentos_url = getenv("AGENTOS_URL", "http://127.0.0.1:8000")

# ---------------------------------------------------------------------------
# Interfaces
# - Agno becomes available on Slack when both env vars are set
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN = getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = getenv("SLACK_SIGNING_SECRET", "")

# ---------------------------------------------------------------------------
# MCP OAuth — enabled by setting the MCP_CONNECT_SECRET environment variable.
# Connect your favorite AI apps and coding agents to a secure /mcp using OAuth.
# ---------------------------------------------------------------------------
MCP_CONNECT_SECRET = getenv("MCP_CONNECT_SECRET", "")

mcp_auth = None
if MCP_CONNECT_SECRET:
    from agno.os import AgentOSBuiltinAuth

    mcp_auth = AgentOSBuiltinAuth(
        url=agentos_url,
        secret=MCP_CONNECT_SECRET,
        signing_key_material=getenv("AGENTOS_MCP_SIGNING_KEY"),
    )


# ---------------------------------------------------------------------------
# Lifespan — app-level startup / teardown.
#
# AgentOS handles the MCP lifecycle (connect on startup, close on shutdown)
# for agent-attached and registry tools. Keep this hook to plug in your own setup.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):  # type: ignore[no-untyped-def]
    log_info("AgentOS lifespan: startup")
    # Register schedules on startup. Idempotent and fail-soft.
    register_schedules()
    try:
        yield
    finally:
        log_info("AgentOS lifespan: shutdown")


# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    name="AgentOS",
    tracing=True,
    scheduler=True,
    scheduler_base_url=agentos_url,
    authorization=runtime_env != "dev",
    authorization_config=AuthorizationConfig(user_isolation=True),
    mcp=True,
    mcp_auth=mcp_auth,
    lifespan=lifespan,
    db=get_postgres_db(),
    knowledge=[shared_knowledge, product_knowledge],
    manager=OSManager(
        model=default_model(),
        root=".",
        knowledge=shared_knowledge,
        learning=shared_learning,
        access_docs=True,
        offload_tool_results=result_store,
        tools=[get_knowledge_management_tools()],
        instructions=MANAGER_INSTRUCTIONS,
    ),
    company=CompanyConfig(db=get_postgres_db(), products=products),
    queue=QueueConfig(durable=True, db=get_postgres_db(), redis=getenv("REDIS_URL")),
    agents=[company_analyst, *engineering_agents()],
    workflows=[deployment_check, run_evals],
    registry=registry,
    config=str(Path(__file__).parent / "config.yaml"),
)
# Bind interfaces to the framework-owned team after assembly, before get_app().
manager_team = agent_os.manager
assert manager_team is not None
agent_os.mcp = MCPConfig(
    default_tools=True,
    tools=[
        manager_team.as_tool(
            name="agno",
            title="Agno",
            description=("Talk to OS Manager for this AgentOS. Pass session_id back to continue the conversation."),
        )
    ],
)
if SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET:
    from agno.os.interfaces.slack import Slack

    agent_os.interfaces.append(
        Slack(
            team=manager_team,
            streaming=True,
            token=SLACK_BOT_TOKEN,
            signing_secret=SLACK_SIGNING_SECRET,
            resolve_user_identity=True,
            loading_text="Pulling the thread...",
        )
    )
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="app.main:app", reload=False)
