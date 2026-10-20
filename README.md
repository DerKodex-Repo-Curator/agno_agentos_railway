# AgentOS

A small application on top of [Agno](https://github.com/agno-agi/agno): OS Manager,
Company, PostgreSQL storage, MCP, optional Slack, and coding agents with optional sandboxes.
Agno owns the manager's members, Studio, authorization, durable execution and sandbox lifecycle.

## Run locally

Requires Docker and an OpenAI API key. Copy the environment file only if absent:

```sh
[ -f .env ] || cp example.env .env
# Set OPENAI_API_KEY in .env.
docker compose up -d --build
curl -fsS http://localhost:8000/health
./scripts/mcp_check.sh
```

The MCP check initializes the connection and verifies the required tools without a model
call. Supply a prompt to also test OS Manager (spends model calls):

```sh
./scripts/mcp_check.sh --prompt "Without using tools, introduce yourself briefly."
```

Connect [AgentOS](https://os.agno.com) to `http://localhost:8000` and select OS Manager.
Its HTTP route is `/teams/os-manager-internal/runs`; its MCP tool is `agno` at `/mcp`.
The eight built-in MCP tools remain available alongside `agno`.
Set both Slack credentials to enable the Slack interface.

Local development disables JWT; production requires verification. Never copy
`RUNTIME_ENV=dev` into an environment file that will sync to production.
This template runs one API replica with a PostgreSQL durable queue and no Redis.

## Company

The **AgentOS** Product in [app/company.py](app/company.py) represents this deployment:
useful agents, reliable execution and continuous improvement. Its Sources are Agno
release notes and the application source. Agno's Product Manager handles planning,
evidence-backed proposals and status updates through OS Manager.

Ask OS Manager to review relevant releases and recommend the next improvement.
No maintenance Routines ship by default: the pinned framework cannot use its internal
Product Manager or OS Manager as a Routine executor. Scheduled maintenance requires
a supported executor; do not register internal manager members to bypass this restriction.

Declarations seed new records without overwriting saved edits. Before upgrading an
existing deployment, update the Product's saved name/purpose and disable or retarget
saved schedules using the removed `company-analyst`, including Release intake,
Daily refresh, Weekly summary and Weekly review. Inspect saved Studio references too.
The Product ID remains `this-agentos`. Removing declarations does not delete saved
Routines or historical work. `ENABLE_MAINTENANCE` is no longer used.

Declare additional Products in `app/company.py` or under `company.products` in
`app/config.yaml`. On the current dependency pin, Product metadata PATCH replaces
the dictionary; include all metadata when editing it.

## Engineers

[agents/engineers.py](agents/engineers.py) declares two independent coding agents:

| Agent | Harness | Default model |
| --- | --- | --- |
| Claude Engineer (`claude-engineer`) | Claude Code | `claude-opus-5-5` |
| Codex Engineer (`codex-engineer`) | Codex | `gpt-6.1-sol` |

Models are defined directly in `agents/engineers.py`; edit their `model` arguments to change them.
Both agents are always registered. Without a sandbox, their harnesses run on the
AgentOS server in the absolute project root (`/app` in the API container). With a sandbox
configured, they run in its repository checkout. Invalid sandbox configuration fails
at startup rather than falling back to the server. Claude on AgentCore uses
Bedrock; set Claude's `model` argument to an inference profile supported by that account. An
Engineering team is deferred until framework support and delegation have been tested.

For local Docker sandboxes, run the API on the host so it can reach the Docker daemon:

```sh
docker compose up -d agentos-db
./scripts/venv_setup.sh
docker build --target sandbox --load -t agno-sandbox:local .
docker image inspect agno-sandbox:local --format '{{.Id}}'
docker compose stop agentos-api
RUNTIME_ENV=dev DB_HOST=127.0.0.1 DB_PORT=5432 SANDBOX_ENABLED=true \
  AGENTOS_URL=http://127.0.0.1:8000 \
  uv run --no-project --env-file .env --with-requirements requirements.txt \
  uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload \
  --reload-dir agents --reload-dir app --reload-dir db --reload-dir evals
# From another terminal:
MCP_CHECK_HOST=1 ./scripts/mcp_check.sh
```

Repository configuration, provider selection and checkpoints live in
[app/sandbox.py](app/sandbox.py). Edit `REPOSITORY` for your fork; it defaults to this
template's GitHub repository on `main`. Development checkpoints use the absolute project
`tmp/checkpoints` directory. Server-hosted or local Claude needs `ANTHROPIC_API_KEY`; Codex uses
`OPENAI_API_KEY`. Private repository cloning can use `GITHUB_READ_TOKEN`, which enters
the sandbox. Publication credentials are not configured by this template.

**Current limitation:** the pinned framework requires Redis for sandboxed HTTP runs.
This template deliberately has no Redis, so sandboxed engineer HTTP runs are blocked
until Agno supports the single-replica PostgreSQL-only path. Engineers running on the
AgentOS server do not use that sandbox route.
The API, OS Manager, Company planning and ordinary durable queue remain available.
Direct Python harness execution is a separate path and is not verified by API startup.

Production uses AgentCore, an ARM64 runtime image, and a persistent checkpoint volume.
The API does not need a Docker daemon. Build an ARM64 image with:

```sh
# Set SANDBOX_IMAGE to your ECR URI with an immutable tag.
docker build --target sandbox --platform linux/arm64 --load -t "${SANDBOX_IMAGE}" .
docker image inspect "${SANDBOX_IMAGE}" --format '{{.Id}}'
```

Push the image to ECR and provision the AgentCore runtime and its execution role through
your AWS tooling. Set `SANDBOX_RUNTIME_ARN` to that runtime's ARN and mount a persistent volume at `/data`;
checkpoints use `/data/checkpoints`. Startup rejects AgentCore without that mount.
Keep one API replica. Direct engineer runs and Company Task
acceptance/completion are separate verification gates. The template's current immutable
pin predates the complete Company sandbox integration; do not bypass framework rejections
or infer Company readiness from a direct-agent test.

## Build agents

Use `/create-agent` to add an agent, `/extend-agent` for a specific change, and
`/create-evals` plus `/eval-and-improve` for behavioral coverage and hardening.
OS Manager and Studio can also compose components from [app/registry.py](app/registry.py).
The palette contains web access, lightweight file generation, a calculator, models,
learning, knowledge, and shared notes. New runtime capabilities enter this explicit registry.

Import `shared_knowledge`, `shared_learning`, and `shared_notes` from `app.registry`.
Operator documents use shared knowledge; learning stores per-user profiles and memories.
Attach `shared_notes.tools()` for a PostgreSQL notebook. Its default tools can read, write,
append, replace, list, search and move notes. User scoping follows AgentOS user isolation.
Keep personal profiles in learning and Company knowledge in Company wiki.
Create a separate knowledge base when adding an end-user product agent; none ships by default.
Existing product-knowledge data is preserved, but saved Studio components referencing it need
their knowledge declaration restored or their configuration updated before deployment.
Register code agents and teams in `app/main.py` and add their
prompts to `app/config.yaml`. No example workflows or startup schedules ship by default;
Company uses the framework scheduler.

## Verify and develop

```sh
./scripts/venv_setup.sh
source .venv/bin/activate
./scripts/format.sh
./scripts/validate.sh
python -m evals --tag smoke --json-output tmp/evals.json
```

Model evals use the application's `.env`, database and workspace and spend model calls.
The CLI defaults to development mode unless `RUNTIME_ENV` is explicitly configured.
Sessions and eval results persist in the configured database for the AgentOS UI.
The CLI does not start the API server or scheduler.

The three cases in [evals/cases.py](evals/cases.py) check onboarding, diagnostics and
the application's learning configuration. They use Agno's built-in answer criteria
and expected tool-call checks. Add application cases here; generic manager and Company
behavior belongs in Agno's coverage. `--json-output` saves Agno's report (answers,
tool names and verdicts). Use `--name <case>` to select one case or `--list`
to inspect the suite without model calls.

Dependencies flow from `pyproject.toml` through `scripts/generate_requirements.sh` to
committed `requirements.txt`. Docker, CI and host setup use those requirements. There
is no `uv.lock`; use `uv run --no-project` when invoking uv outside the activated venv.
After changing dependencies, regenerate requirements and rebuild.

The root [Dockerfile](Dockerfile) has two targets sharing the same pinned dependencies:
`agentos` serves the API and is the default for Railway and Compose; `sandbox` starts the
execution runtime and does not copy application code. Build the API locally with
`docker build --target agentos --load -t agentos:local .`. Both builds use the root
`.dockerignore` to exclude local credentials, caches and working data.

## Deploy on Railway

Install and authenticate the Railway CLI. Use `/deploy-platform` for the guided path,
or prepare `.env.production` from `example.env`, set its keys, then run:

```sh
./scripts/railway/up.sh
```

The script provisions the API and pgvector database, sets the public URL, and guides
the JWT verification-key step. Configure JWT verification before serving production
traffic. Use a persistent volume for AgentCore checkpoints when that sandbox is enabled.

```sh
./scripts/railway/redeploy.sh   # changed code
./scripts/railway/env-sync.sh   # changed production settings
railway logs --service agent-os
./scripts/railway/down.sh      # deletes the project, database and all its data
```

For browser MCP clients, connect to `https://<domain>/mcp` using OAuth and the configured
`MCP_CONNECT_SECRET`. Coding clients can use `uvx agno connect --url https://<domain>`.
For the authenticated MCP probe, provide an existing JWT or PAT as `MCP_CHECK_TOKEN`;
the check does not mint accounts. Render remains a separate deployment follow-up.

When upgrading an existing deployment, disable its old `deployment-check` and
`run-evals` schedules before removing those endpoints. Inspect saved Studio components
for references to removed functions/toolkits. Migrate references deliberately; do not delete historical state.

## Configuration

See [example.env](example.env) for copyable settings. No real credentials belong in Git.

| Setting | Purpose / default |
| --- | --- |
| `OPENAI_API_KEY` | Application model, embeddings and Codex authentication. |
| `RUNTIME_ENV` | `prd`; Compose/host development set `dev`. |
| `JWT_VERIFICATION_KEY` / `JWT_JWKS_FILE` | Production JWT verification; choose one. |
| `AGENTOS_URL` | Scheduler/OAuth origin; default `http://127.0.0.1:8000`. |
| `MCP_CONNECT_SECRET` | Optional OAuth connect secret, at least 16 characters. Agno generates the signing key and persists it in PostgreSQL across redeploys. |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_DATABASE` | Defaults: `localhost`, `5432`, `ai`, `ai`, `ai`. |
| `DB_DRIVER` | `postgresql+psycopg`. |
| `PARALLEL_API_KEY` | Optional authenticated web access; otherwise keyless MCP. |
| `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` | Both enable the Slack interface. |
| `PORT`, `AGNO_DEBUG`, `WAIT_FOR_DB` | Host port (`8000`), debug output, container database wait. |
| `SANDBOX_ENABLED` | `false`; enable Docker engineering in development. |
| `SANDBOX_IMAGE` | `agno-sandbox:local` for dev; pushed ECR URI for runtime provisioning. |
| `SANDBOX_RUNTIME_ARN` | Runs engineers in production AgentCore instead of on the AgentOS server. |
| `ANTHROPIC_API_KEY`, `GITHUB_READ_TOKEN` | Local Claude and optional private repository read access. |
| `AWS_REGION`, `AWS_PROFILE` | AgentCore host credentials/region; region defaults to `us-east-1`. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | Alternative host AWS credentials. |
| `MCP_CHECK_HOST`, `MCP_CHECK_TOKEN` | Run the probe on the host; optional existing bearer token. |
