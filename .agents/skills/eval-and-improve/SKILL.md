---
name: eval-and-improve
description: Run the eval suite (python -m evals), diagnose every failure, fix what's in scope, and loop until all cases pass. Use when evals are failing — or when the user wants to run, diagnose, or repair the eval suite. To author new coverage, use create-evals instead.
---

# Eval and Improve

> _Coding-agent workflow: run as `/eval-and-improve` or by describing the task._

Run the suite, diagnose every failure, fix what's in scope, stop when green. Cases live in [`evals/cases.py`](../../../evals/cases.py) (`agno.eval.Case`), the state snapshots in [`evals/hooks.py`](../../../evals/hooks.py) and ownership guards in [`evals/isolation.py`](../../../evals/isolation.py), the entrypoint in [`evals/__main__.py`](../../../evals/__main__.py). Each case uses an LLM judge (`criteria`), a tool-call assertion (`expected_tool_calls`), and/or a deterministic `scorer`.

## 0. Preconditions

- Postgres on 5432 (`nc -z localhost 5432`; else `docker compose up -d agentos-db`).
- Venv active (`source .venv/bin/activate`; `./scripts/venv_setup.sh` if missing). No server needed — cases import the components directly.
- `.env` has `OPENAI_API_KEY` (and `PARALLEL_API_KEY` if you use one — it pins Agno's expected web tool name at import). Worktrees don't inherit `.env`.

## 1. Run

```bash
python -m evals --tag smoke            # fast template checks
python -m evals --tag release          # broader pre-release checks
python -m evals --tag live             # current web/source checks
python -m evals --name <case>          # one case
python -m evals --tag smoke --list     # what a selector picks, without running
python -m evals --json-output out.json # machine-readable (carries judge_reason)
python -m evals -v                     # stream the runs
```

Exit 0 = all passed. Every CLI run creates a separate process and an owned,
disposable PostgreSQL database. Do not import cases into the served process or run
shared-database cleanup sweeps. The DB role needs CREATEDB privileges.
Use `--json-output` to retain results; the isolated eval history is removed with its
database. Inspect errors rather
than assuming stderr noise is harmless.

## 2. Diagnose

| Symptom | Likely cause | Fix |
|---|---|---|
| Judge: right answer, missing X | Instructions don't push for X | `agents/<slug>.py` — tighten the rule |
| Judge: fabricated | Should have said it didn't know | Add a "say so plainly" rule |
| Reliability: missing tool | Routing rule weak, or the case too narrow | Strengthen the rule, or broaden `expected_tool_calls` |
| Reliability: additional tool with `allow_additional_tool_calls=False` | Agent fanned out | Tighten instructions or allow it |
| Agno web tool name mismatch (`parallel_search` ↔ `web_search`) | `PARALLEL_API_KEY` differs between `.env` and shell | Sync and re-run |
| Flips PASS/FAIL across runs, no change | Judge variance | Re-run 2–3×; still flipping → make `criteria` more falsifiable |
| Fails in the suite, passes alone | Transient flake / 429 | Re-run alone, then the suite; persistent 429s → back off |
| Many fail at once | Broad regression (model, MCP down, tool removed) | Find the root cause; no prompt edits |
| `run paused awaiting user input` | Hit a HITL gate (Builder archive/delete) — never graded | Keep the case input on the ungated side |

**Never weaken a case to make it green.** Edit a case only when the assertion was wrong. Read both sides — the response and `judge_reason` — before deciding which. When you do edit one, make sure the green is earned: the tool fired, and the rubric can't be met by a shortcut.

## 3. Scope

In: `agents/<slug>.py` / `app/main.py` (instructions, tools, model); `evals/cases.py` when an assertion was wrong; a one-line `app/main.py` flip if a case needs it. Out (flag, don't do): removing cases, editing `db/` or `app/` to pass, editing agno. Fast iteration on agent quality is [`eval-and-improve`](../eval-and-improve/SKILL.md); a user-driven change is [`extend-agent`](../extend-agent/SKILL.md).

## 4. Re-run and stop

`python -m evals --name <case>` after each fix; then `python -m evals --tag release`. Stop when it exits 0 **and** prints the `Eval Summary` — an aborted run is inconclusive.

## 5. Add a case (if needed)

When a diagnosis reveals a missing assertion, add it to `evals/cases.py`; coverage work belongs to [`create-evals`](../create-evals/SKILL.md).

```python
Case(
    name="<short_id>",
    agent=<the_agent>,           # a Team goes in team= — exactly one of the two
    input="<prompt>",
    tags=("release",),           # smoke = fast core checks; live = depends on today's web
    criteria="<rubric>",
    expected_tool_calls=("<tool_name>",),
    scorer=<behavioral_scorer>,  # verify successful payloads and durable state, not just tool names
    setup=<behavioral_scorer>.setup,
)
```

Only a completed run is graded; a paused, cancelled, or errored run fails. Assert
persisted state before database cleanup. Negative/read-only cases must reject both
mutation attempts and durable changes. Keep external effects contained: database
isolation does not isolate arbitrary third-party APIs. Do not add template prompt
policy to compensate for a framework defect; report that boundary explicitly.

## 6. Derive new probes when hardening an agent

Read its instructions and sample recent sessions read-only. Treat observed answers as
scenarios, never golden answers; remove private content from fixtures. Derive golden-path,
edge, refusal and adversarial cases for the stated behavior. Run probes only through
`python -m evals` with isolated fixtures. For tool use, inspect successful payloads,
persisted state and child-run evidence. Change one instruction/tool decision at a time;
re-run failed cases plus relevant regressions. Keep a useful probe as a permanent case
through `/create-evals`. Report environment failures separately from behavioral failures.
