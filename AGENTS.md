# AgentOS Railway template

This repository is a thin application wrapper over Agno. `CLAUDE.md` links here.
OS Manager (`os-manager-internal`) is the one built-in platform agent, served as a
team. Agno owns its members, source read tools, Studio tools, and Company Product
Manager. Configure it through `OSManager` in `app/main.py`; never duplicate those
members in this template. Its `root="."` is this application's read-only source.

## Layout

- `app/main.py`: AgentOS assembly, shared sync database, OS Manager, Company,
  durable queue, MCP `agno` tool, conditional Slack and MCP OAuth.
- `app/config.yaml`: component descriptions and quick prompts; additional
  declarative `company.products` may also be configured here.
- `app/company.py`: This AgentOS Product, release Sources, three opt-in Routines, and
  the `company-analyst` application agent holding CompanyTools.
- `app/registry.py`: reviewed Studio palette. New runtime capabilities enter here.
- `app/knowledge.py`: operator `shared-knowledge` and product `product-knowledge`.
- `app/learning.py`: shared per-user learning, using the default model and DB.
- `app/settings.py`: default model factory; change the model in one place.
- `app/schedules.py`: daily deployment check and disabled-by-default eval schedule.
- `app/tools.py`, `app/functions.py`: tool factories and deterministic workflow steps.
- `app/notes.py`, `app/offload.py`: shared notebook and seven-day result store.
- `agents/`: user agents and optional `engineer_sandbox.py` provider/executor wiring.
- `teams/`: user teams; register them in `app/main.py` and the manifest.
- `db/`: cached synchronous PostgresDb and pgvector knowledge helpers. OS, Company,
  queue and executors MUST use the same `get_postgres_db()` instance. Knowledge
  content adapters have distinct IDs. Do not introduce a second adapter with the OS ID.
- `evals/`: cases, behavioral scorers, owned-database isolation, and Agno eval runner entrypoint.
- `workflows/`: deterministic deployment check and opt-in model-backed run-evals.
- `sandbox/`: engineering image and a build helper with a minimal build context.
- `scripts/`: setup, validation, host development, sandbox build/runtime and Railway deploy.
- `.agents/skills/`: coding-agent workflows; `.claude/skills` links here.
- `compose.yaml`: Postgres, Redis coordination and optional containerized dev API.
- `Dockerfile`, `railway.json`: production image and single-replica Railway deployment.

## Development

The first-run path is `.agents/skills/setup-platform/SKILL.md`. Copy `example.env`
to `.env` only if absent, then set `OPENAI_API_KEY`. Standard development uses
`docker compose up -d --build`. Sandbox development uses:

```sh
docker compose up -d agentos-db agentos-redis
./scripts/build_sandbox_image.sh local
# Stop this checkout's API container before serving the same port on the host.
docker compose stop agentos-api
SANDBOX_REPOSITORY=https://github.com/your-org/your-repo SANDBOX_ENABLED=true ./scripts/dev.sh
```

Dev disables JWT; production defaults to `prd` and requires JWT verification.
Do not put `RUNTIME_ENV=dev` in an environment file that syncs to production.
Keep configuration in `app/*.py` and `app/config.yaml`, settings in environment
variables, Compose for dev and `railway.json` for production. See `README.md` and
`example.env` for all environment settings and sandbox credentials.

Use `./scripts/venv_setup.sh`, activate `.venv`, then `./scripts/format.sh` and
`./scripts/validate.sh`. Regenerate `requirements.txt` with
`./scripts/generate_requirements.sh` after dependency changes. Agno is temporarily
pinned to an immutable main commit; update the application and sandbox pin together
until a released version includes the required Company and sandbox APIs.

## Adding capabilities

Use `/create-agent` for a new agent, `/extend-agent` for a specific change,
`/improve-agent` for autonomous probes, `/create-evals` for coverage,
`/eval-and-improve` for failures, `/review-and-improve` for drift, and
`/deploy-platform` for production. Copy the `Agent` shape in `app/company.py`:
module-level instructions, stable id, `default_model()`, shared DB, explicit tools,
history and datetime. End-user product agents read `product_knowledge`, never the
operator base; add `shared_learning` when they should remember their users.

Company is on by default. Products contain Projects and Routines; Tasks belong to
Projects. Declare all metadata with the Product: PATCH replaces metadata wholesale.
Engineering agents are optional and selected by environment; direct runs and Company
Task acceptance are separate verification gates. Never bypass a framework rejection
of a sandboxed Task executor while waiting for the Company executor integration.

## Evals and verification

Run cases only through `python -m evals`, which creates an owned disposable database
and a separate worker process. Never run shared-database snapshot/diff deletion.
Use deterministic scorers for tool results and persisted state; read-only cases
assert no business-state changes or mutation attempts. Preserve the database ownership
guards and keep external side effects contained.
Use `python -m evals --tag smoke` or `--tag release`; both spend model calls.
Deployment-check is deterministic. Record integration commands and responses in
`tmp/VERIFY.md`; distinguish actual model/container runs from static checks.
