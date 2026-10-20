---
name: create-evals
description: Author eval coverage for an agent in this AgentOS — map what the agent promises, mine real sessions and eval history from Postgres for scenarios, propose capabilities worth testing, then write, run, and audit Case entries in evals/cases.py. Use when the user wants evals created, coverage added, or an agent's behavior pinned down as tests. To repair a failing suite, use eval-and-improve instead.
---

# Create Evals

> _Coding-agent workflow: run as `/create-evals` or by describing the task._

Turn what an agent promises into `Case` entries in [`evals/cases.py`](../../../evals/cases.py). The template's cases cover the reference components only; a user-built agent is invisible to the suite until this skill writes one. Failing suite → [`eval-and-improve`](../eval-and-improve/SKILL.md); agent needs hardening → [`eval-and-improve`](../eval-and-improve/SKILL.md).

Preconditions: Postgres on 5432, venv active (`source .venv/bin/activate`; `./scripts/venv_setup.sh` if missing), `.env` populated.

**Be self-driving:** the repo and the database answer most questions. Ask the user only what they alone know — which jobs matter and which failures would hurt. One pick per exchange, recommendation first.

## 1. Pick the agent

The user's choice, or the least-covered component — almost always one of theirs. Source components have a file under `agents/` or `teams/`. Studio-built components have none: `Agent.load("<id>", db=get_postgres_db(), registry=registry, published_only=True)` (or `Team.load`) rehydrates the published config at import time; it returns `None` for an archived or unpublished component, and a `Case` with neither field set raises — guard the load or the whole suite fails at import. Workflows cannot be case targets.

## 2. Map what it promises

Read the file (or the published config: `get_postgres_db().get_config(component_id="<id>")["config"]`). Every "always", "never", "use X for Y" is a case. Note the tools for reliability assertions.

Run every case through `python -m evals`, which uses the application's `.env`,
database and workspace. Sessions and results persist. Do not mutate existing user
components as fixtures; mutating cases need explicitly owned fixtures.
Use Agno's built-in `criteria` and `expected_tool_calls`. Keep generic Agno behavior
in framework coverage; do not add custom scorers, isolation or cleanup machinery
to the starter by default.

## 3. Mine the platform

```python
from db import get_postgres_db
db = get_postgres_db()
sessions, _ = db.get_sessions(component_id="<agent-id>", limit=20, deserialize=False)
asks = [run["input"]["input_content"] for s in sessions for run in (s.get("runs") or []) if run.get("input")]
evals, _ = db.get_eval_runs(limit=20, deserialize=False)
```

Real asks make the best inputs. A recorded answer is a scenario, never a golden answer — the rubric states the timeless shape of a correct answer (a version or date enters as "a current X with a source", never as the value). No sessions is fine: derive from `INSTRUCTIONS`.

## 4. Propose what to test

2–3 capabilities, each with a one-line scenario and what a pass proves; lead with the one closest to the core job or hit most in sessions. Skip what the suite already covers. One exchange.

## 5. Write the case

Inside `CASES` after the marker `# --- Your cases — authored by /create-evals ---` (add it if missing). Names must be unique across the file.

```python
Case(
    name="<agent>_<capability>",
    agent=<the_agent>,   # a Team goes in team= — nothing catches a team in agent=; it runs, misfiled
    input="<scenario>",
    tags=("<smoke|release|live>",),  # model calls; choose smoke, release or live deliberately
    timeout_seconds=90,
    criteria="<specific, falsifiable>",
    expected_tool_calls=("<tool>",),
)
```

Pair answer criteria with `expected_tool_calls` when a tool is required.
Tool-call checks verify invocation, not successful payloads or persisted state;
inspect those when auditing a run rather than claiming the built-in check proves them.

Use unique fixture names and isolated users. External mutations (messages, files,
third-party APIs) require their own containment or must stay outside the suite.

## 6. Run and audit

```bash
python -m evals --name <case>
```

Run through `python -m evals`; results persist in the application's database for the UI. Read both sides of the verdict: the response and tools fired, and `judge_reason` (`--json-output`). Run at least twice (three times for judgment words like "compact"); a flipping verdict needs investigation. If the agent, not the case, is wrong, say so — that's [`eval-and-improve`](../eval-and-improve/SKILL.md).

Loop to Step 4 or finish.

## 7. Hand over

New cases by name and tag, `git diff evals/cases.py`, suggested commit `eval(<agent>): …`. `smoke` cases run on demand through `python -m evals`; failures go to [`/eval-and-improve`](../eval-and-improve/SKILL.md).
