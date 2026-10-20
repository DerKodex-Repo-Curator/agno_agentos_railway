"""Configuration gates: no sandbox execution or model calls."""

import os
import subprocess
import sys
import unittest


class EngineerConfiguration(unittest.TestCase):
    def check_config(self, settings, code, success=True):
        env = {
            **os.environ,
            "RUNTIME_ENV": "dev",
            "SANDBOX_ENABLED": "false",
            "SANDBOX_RUNTIME_ARN": "",
            **settings,
        }
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_without_sandbox_engineers_use_server_workspace(self):
        for runtime in ("dev", "prd"):
            with self.subTest(runtime=runtime):
                self.check_config(
                    {"RUNTIME_ENV": runtime},
                    """
import os
import sys
import tempfile
from pathlib import Path

project_root = Path.cwd().resolve()
sys.path.insert(0, str(project_root))
# Import from another working directory to verify the workspace is anchored to the source.
os.chdir(tempfile.gettempdir())
from agents.engineers import engineers
from db import get_postgres_db
assert [a.id for a in engineers] == ['claude-engineer', 'codex-engineer']
assert all(a.db is get_postgres_db() for a in engineers)
assert all(a.sandbox is None and a.repository is None and a.cwd == str(project_root) for a in engineers)
assert engineers[0].permission_mode == 'acceptEdits'
assert engineers[1].sandbox_mode == 'workspace-write'
""",
                )

    def test_enabled_engineers_share_database_provider_and_repository(self):
        self.check_config(
            {"SANDBOX_ENABLED": "true"},
            """
from agents.engineers import engineers
from db import get_postgres_db
assert [a.id for a in engineers] == ['claude-engineer', 'codex-engineer']
assert [a.model for a in engineers] == ['claude-opus-5-5', 'gpt-6.1-sol']
assert all(a.db is get_postgres_db() for a in engineers)
assert engineers[0].sandbox is engineers[1].sandbox
assert engineers[0].repository is engineers[1].repository
assert engineers[0].repository.url == 'https://github.com/agno-agi/agentos-railway.git'
assert engineers[0].repository.branch == 'main'
assert engineers[0].sandbox.network == 'isolated'
assert all(a.cwd is None for a in engineers)
""",
        )

    def test_repository_and_checkpoints_ignore_legacy_environment_and_cwd(self):
        self.check_config(
            {
                "SANDBOX_ENABLED": "true",
                "SANDBOX_REPOSITORY": "https://github.com/example/ignored",
                "SANDBOX_BRANCH": "ignored",
                "SANDBOX_CHECKPOINTS": "/ignored/checkpoints",
            },
            """
import os
import sys
import tempfile
from pathlib import Path

root = Path.cwd().resolve()
sys.path.insert(0, str(root))
os.chdir(tempfile.gettempdir())
from app.sandbox import LOCAL_CHECKPOINTS, repository, sandbox
assert repository.url == 'https://github.com/agno-agi/agentos-railway.git'
assert repository.branch == 'main'
assert LOCAL_CHECKPOINTS == root / 'tmp' / 'checkpoints'
assert sandbox.checkpoints.root == LOCAL_CHECKPOINTS
""",
        )

    def test_production_requires_persistent_checkpoint_configuration(self):
        result = self.check_config(
            {"RUNTIME_ENV": "prd", "SANDBOX_RUNTIME_ARN": "test-runtime"},
            "from unittest.mock import patch\n"
            "with patch('pathlib.Path.is_mount', return_value=False):\n"
            "    import agents.engineers",
            success=False,
        )
        self.assertIn("Mount a persistent volume at /data", result.stderr)

    def test_production_uses_declared_checkpoint_volume(self):
        self.check_config(
            {"RUNTIME_ENV": "prd", "SANDBOX_RUNTIME_ARN": "test-runtime"},
            """
from pathlib import Path
from unittest.mock import patch

with (
    patch("pathlib.Path.is_mount", return_value=True),
    patch("agno.sandbox.checkpoint.FileCheckpointStore") as checkpoints,
    patch("agno.sandbox.agentcore.AgentCoreSandbox") as provider,
):
    from app.sandbox import repository, sandbox
checkpoints.assert_called_once_with(Path("/data/checkpoints"))
assert provider.call_args.kwargs["checkpoints"] is checkpoints.return_value
assert provider.call_args.kwargs["runtime_arn"] == "test-runtime"
assert sandbox is provider.return_value
assert repository is not None
""",
        )

    def test_models_are_defined_in_code_despite_legacy_environment(self):
        for enabled in ("false", "true"):
            with self.subTest(sandbox=enabled):
                self.check_config(
                    {
                        "SANDBOX_ENABLED": enabled,
                        "CLAUDE_MODEL": "claude-fable-5-1",
                        "CODEX_MODEL": "gpt-6-astra",
                    },
                    "from agents.engineers import engineers; "
                    "assert [a.model for a in engineers] == ['claude-opus-5-5', 'gpt-6.1-sol']",
                )


if __name__ == "__main__":
    unittest.main()
