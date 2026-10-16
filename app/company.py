"""Company declarations and the release analyst for this deployment."""

from os import getenv
from pathlib import Path

import agno
from agno.agent import Agent
from agno.company import Product, Routine, Source
from agno.tools.company import CompanyTools

from app.settings import default_model
from db import get_postgres_db

INTAKE_INSTRUCTIONS = (
    f"This deployment runs agno {agno.__version__}; read the releases Source; for each newer release propose "
    "one Project named for the version and one Task per change that affects this application, citing the release "
    "note as evidence. Read the git Source to understand this application. Use intake_company_source with the "
    "observed evidence hashes to deduplicate Tasks. If there is no newer release, record a quiet check; do not "
    "invent work."
)

company_analyst = Agent(
    id="company-analyst",
    name="Company Analyst",
    model=default_model(),
    db=get_postgres_db(),
    tools=[CompanyTools(get_postgres_db())],
    instructions="You maintain This AgentOS. Read Company Sources, propose evidence-backed work, and never accept it.",
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
)

summary_destination = getenv("SLACK_SUMMARY_CHANNEL")
slack_summary = bool(getenv("SLACK_BOT_TOKEN") and getenv("SLACK_SIGNING_SECRET") and summary_destination)
products = [
    Product(
        id="this-agentos",
        name="This AgentOS",
        purpose="keep this deployment current with Agno releases",
        metadata={"summary": {"interface": "slack", "destination": summary_destination}} if slack_summary else {},
        sources=[
            Source(type="website", reference="https://github.com/agno-agi/agno/releases"),
            Source(type="git", reference=str(Path(__file__).resolve().parents[1])),
        ],
        routines=[
            Routine(
                name="Release intake",
                template="intake",
                executor_type="agent",
                executor_id="company-analyst",
                cron_expr="0 9 * * *",
                instructions=INTAKE_INSTRUCTIONS,
            ),
            Routine(
                name="Daily refresh",
                template="refresh",
                executor_type="agent",
                executor_id="company-analyst",
                cron_expr="0 10 * * *",
            ),
            Routine(
                name="Weekly summary",
                template="summary" if slack_summary else None,
                executor_type="agent",
                executor_id="company-analyst",
                cron_expr="0 11 * * 1",
                instructions=None
                if slack_summary
                else (
                    "Read this Product's attention queue, Projects, Tasks and failed Routines. "
                    "Write a concise weekly summary to the Product status page using update_company_status. "
                    "No delivery destination is configured; do not claim external delivery."
                ),
            ),
        ]
        if getenv("ENABLE_MAINTENANCE", "").lower() == "true"
        else [],
    ),
]
