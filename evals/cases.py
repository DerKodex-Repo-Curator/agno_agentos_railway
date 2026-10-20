"""Application behaviors, executed only in the owned-database worker."""

from copy import copy

from agno.eval import Case

from evals.isolation import require_isolation

require_isolation()

from app.main import agent_os  # noqa: E402
from app.settings import default_model  # noqa: E402
from db import get_postgres_db  # noqa: E402
from evals.hooks import record_evidence  # noqa: E402
from evals.scorers import Behavior, Proposal, focused_explanation, onboarding, searched  # noqa: E402

_db = get_postgres_db()
_onboarding = Behavior(_db, onboarding)
_health = Behavior(_db, searched("run_diagnostics"))
_learning = Behavior(_db, focused_explanation())
_configured_learning = Behavior(_db, focused_explanation(configured=True))
assert agent_os.product_manager is not None
_product_manager = copy(agent_os.product_manager)
_product_manager.user_id = "eval-product-manager"
_proposal = Proposal(_db, user_id=_product_manager.user_id)

CASES = (
    Case(
        name="manager_explains_learning",
        team=agent_os.manager,
        input="How does learning work?",
        tags=("manager", "release"),
        timeout_seconds=180,
        criteria="Explain Agno learning as persistent information stored outside model weights and reused in "
        "later interactions. Distinguish it from model training or fine-tuning. Answer the question directly, "
        "without inventing what this particular application has configured or claiming unobserved execution.",
        judge_model=default_model(),
        scorer=_learning,
        setup=_learning.setup,
        teardown=record_evidence,
    ),
    Case(
        name="manager_explains_configured_learning",
        team=agent_os.manager,
        input="What learning is actually configured in this app, and does it retrain the model?",
        tags=("manager", "release"),
        timeout_seconds=180,
        criteria="Accurately describe app/registry.py: shared_learning is a LearningMachine backed by the "
        "shared PostgreSQL database, with user profiles and user memories in AGENTIC mode. Explain that "
        "this persists information outside model weights and does not retrain the model. Ground the "
        "configuration claims in app/registry.py; a local file citation is sufficient. Do not claim "
        "a successful live learning test or invent additional enabled learning stores.",
        judge_model=default_model(),
        scorer=_configured_learning,
        setup=_configured_learning.setup,
        teardown=record_evidence,
    ),
    Case(
        name="manager_explains_application",
        team=agent_os.manager,
        input="Read README.md. Explain how to start this application, talk to OS Manager and add an agent. "
        "Do not create or change anything.",
        tags=("smoke", "release"),
        timeout_seconds=180,
        scorer=_onboarding,
        setup=_onboarding.setup,
        teardown=record_evidence,
    ),
    Case(
        name="manager_checks_health",
        team=agent_os.manager,
        input="Run diagnostics and report this AgentOS's health. Do not change any state or run other components.",
        tags=("smoke", "release"),
        timeout_seconds=180,
        scorer=_health,
        setup=_health.setup,
        teardown=record_evidence,
    ),
    Case(
        name="product_manager_proposes_evidence_backed_task",
        agent=_product_manager,
        input="For Product eval-release, read Source eval-release-source, path release.md. "
        "Propose exactly one Project and one Task for its change, using intake_company_source with the observed "
        "link and content hash. Do not accept or execute the Task, or change other Products.",
        tags=("smoke", "release"),
        timeout_seconds=180,
        scorer=_proposal,
        setup=_proposal.setup,
        teardown=record_evidence,
    ),
)
