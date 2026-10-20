# AgentOS Railway template

This is a thin application over Agno. `CLAUDE.md` links here. Agno owns OS Manager
(`os-manager-internal`), its members, source tools, Studio and Company Product Manager.
Configure `OSManager(root=".")` in `app/main.py`; never duplicate those components.

## Layout

- `app/main.py`: one AgentOS, shared database, manager, Company and durable queue.
- `app/interfaces.py`: MCP OAuth, `agno` plus built-in MCP tools, optional Slack.
- `app/company.py`: AgentOS Product and Sources; Agno owns Product Manager.
- `app/config.yaml`: component descriptions/prompts and optional additional Products.
- `app/registry.py`: Studio palette, web tools, shared knowledge, per-user learning and shared notes.
- `app/settings.py`: model factories.
- `app/sandbox.py`: optional Docker/AgentCore provider and repository configuration.
- `agents/engineers.py`: Claude and Codex engineers, with stable existing IDs and optional sandboxes.
- `teams/`: place user-defined teams here; no Engineering team ships yet.
- `db/`: cached synchronous OS database and distinct knowledge content adapters.
- `evals/`: application cases, behavioral scorers and disposable-database isolation.
- `sandbox/`: engineering runtime image and minimal-context builder.
- `scripts/`: local setup, validation, image builds and Railway deployment.
- `.agents/skills/`: coding-agent workflows; `.claude/skills` links here.
- `compose.yaml`: PostgreSQL and optional development API. No Redis.
- `Dockerfile`, `railway.json`: production image and single-replica Railway deployment.

## Development

Use `/setup-platform` for first run. Copy `example.env` to `.env` only if absent,
set `OPENAI_API_KEY`, then `docker compose up -d --build`. For Docker engineering,
follow the host API commands in the README's Engineers section. Build sandbox images
directly with `sandbox/build_image.py`; provision AgentCore with your AWS tooling.

Development disables JWT. Production defaults to `prd` and requires verification.
Never sync `RUNTIME_ENV=dev` to production. Keep application policy in `app/`, settings
in environment variables, local services in Compose and production in `railway.json`.

Use `./scripts/venv_setup.sh`, activate `.venv`, then `./scripts/format.sh` and
`./scripts/validate.sh`. `pyproject.toml` declares dependencies; regenerate the pinned
`requirements.txt` with `./scripts/generate_requirements.sh`. Do not add a competing
`uv.lock`. Use `uv run --no-project` outside the activated environment. Keep application
and sandbox Agno pins aligned until a release provides the required APIs.

## Capabilities and ownership

Use `/create-agent`, `/extend-agent`, `/create-evals`, `/eval-and-improve`, and
`/deploy-platform` for their respective tasks. Use the Agent shape in `/create-agent`:
stable ID, explicit instructions/tools, `default_model()`, shared DB, history and datetime.
Import shared resources from `app.registry`. Add `shared_learning` when agents should
remember users, and attach `shared_notes.tools()` for a PostgreSQL notebook. Its default
tools allow reading, writing, appending, replacing, listing, searching and moving notes;
user scoping follows AgentOS user isolation. Keep personal profiles in learning and
Company knowledge in Company wiki. Product agents need
a separate knowledge base declared on demand, never operator documents or shared notes.
New Studio capabilities enter the registry.

OS, Company, queue, agents and teams MUST reuse `get_postgres_db()` with no arguments.
Knowledge content adapters have distinct IDs; never introduce a second adapter with the OS ID.
Company Products contain Projects and Routines; Tasks belong to Projects. On the current
pin, PATCH replaces Product metadata wholesale. No maintenance Routines ship by default;
the pinned framework cannot use its internal managers as Routine executors.

Both engineers are registered and run in the absolute project root on the AgentOS server when
no sandbox is configured. Repository URL, branch and checkpoint paths are defined in
`app/sandbox.py`; edit them there for a fork. Development checkpoints use the absolute
project `tmp/checkpoints` directory; production requires a persistent mount at `/data`.
A configured sandbox owns its repository checkout; invalid
configuration must fail rather than silently fall back to the server.
The Engineering team is deferred. The pinned framework requires
Redis for sandbox HTTP runs, so that execution path is unavailable in this Redis-free
template. Document the limitation; never bypass the framework check. Use explicit models
and keep provider configuration separate from declarations. Direct execution, team delegation and Company acceptance are separate
verification gates. Never bypass a framework rejection or put a compatibility adapter in
the template. No application-owned queue, sandbox lifecycle or Company state machine.

## Verification

Run `python -m unittest discover -s tests -v`; add `EVAL_TEST_POSTGRES=true` for database
checks. Run model cases only through `python -m evals`, which creates an owned disposable
database and a separate worker. Never use shared-database snapshot/diff deletion. Preserve
ownership and cancellation guards. Read-only cases reject mutation attempts and business-state
changes; mutation cases check persisted evidence. External effects need contained fixtures.

`python -m evals --tag smoke` spends model calls. `scripts/mcp_check.sh` defaults to an
initialize/list-tools probe; --prompt spends model calls. Record verification in
`tmp/VERIFY.md`, separating static, deterministic, model, container and hosted results.
Before upgrading an existing deployment, inspect saved schedules and Studio references to
removed components. Do not delete historical sessions, notes or Company records.
