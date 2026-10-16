"""Scheduled reports must expose failed checks, not a different check's success."""

import importlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv

from evals.isolation import ROOT


class WorkflowReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_judge_is_not_hidden_by_successful_state_scorer(self):
        load_dotenv(ROOT / ".env")
        workflow = importlib.import_module("workflows.run_evals")

        async def completed_run(arguments, **kwargs):
            Path(arguments[arguments.index("--json-output") + 1]).write_text(
                json.dumps(
                    {
                        "summary": {"passed": 0, "total": 1, "status": "FAIL"},
                        "cases": [
                            {
                                "name": "roster",
                                "passed": False,
                                "score_passed": True,
                                "score_reason": "State checks passed",
                                "judge_passed": False,
                                "judge_reason": "Required component missing from answer",
                            }
                        ],
                    }
                )
            )
            return 1, ""

        with patch.object(workflow, "run_isolated", completed_run):
            report = await workflow.run_evals_step(None)
        self.assertFalse(report.success)
        self.assertIn("Required component missing from answer", report.content)
        self.assertNotIn("State checks passed", report.content)
