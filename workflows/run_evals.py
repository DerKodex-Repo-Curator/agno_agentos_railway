"""Run the isolated eval CLI; persist only its report in the application workflow."""

import json
from os import getenv
from pathlib import Path
from tempfile import TemporaryDirectory

from agno.workflow import Step, StepInput, StepOutput, Workflow

from db import get_postgres_db
from evals.isolation import run_isolated


async def run_evals_step(_step_input: StepInput) -> StepOutput:
    with TemporaryDirectory(prefix="railway-eval-report-") as directory:
        path = Path(directory) / "result.json"
        try:
            code, output = await run_isolated(
                ["--tag", getenv("EVALS_TAG", "smoke"), "--json-output", str(path)],
                capture=True,
                timeout=int(getenv("EVALS_SUITE_TIMEOUT_SECONDS", "3600")),
            )
        except TimeoutError:
            return StepOutput(
                content="Evals timed out; the worker was stopped and its isolated database removed.", success=False
            )
        if not path.exists():
            return StepOutput(
                content=f"Evals failed (exit {code}); no complete report.\n{output[-4000:]}", success=False
            )
        payload = json.loads(path.read_text())
        summary = payload["summary"]
        lines = [f"Evals: {summary['passed']}/{summary['total']} passed ({summary['status']})."]
        for case in payload["cases"]:
            lines.append(f"- {case['name']}: {'PASS' if case['passed'] else 'FAIL'}")
            if not case["passed"]:
                reasons = [case.get("error")]
                if case.get("score_passed") is False:
                    reasons.append(case.get("score_reason"))
                if case.get("judge_passed") is False:
                    reasons.append(case.get("judge_reason"))
                if case.get("reliability_passed") is False:
                    reasons.append("Required tool-call checks failed.")
                lines.extend(str(reason) for reason in reasons if reason)
        return StepOutput(content="\n".join(lines), success=code == 0 and summary["status"] == "PASS")


run_evals = Workflow(
    id="run-evals",
    name="Run Evals",
    db=get_postgres_db(),
    steps=[Step(name="run-evals", executor=run_evals_step)],
)
