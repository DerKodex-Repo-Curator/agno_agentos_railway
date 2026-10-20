"""Run the framework eval CLI in a disposable process and Postgres database."""

import asyncio
import os
import re
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import create_engine, make_url, text

ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATTERN = r"railway_eval_[0-9a-f]{32}"


def source_copy(destination: Path) -> None:
    """Only application sources, never secrets, eval answers or local artifacts."""
    folders = ("app", "agents", "teams", "db", "scripts", ".agents")
    files = ("README.md", "AGENTS.md", "Dockerfile", "compose.yaml", "railway.json", "pyproject.toml", "example.env")
    for name in files:
        shutil.copyfile(ROOT / name, destination / name)
    for folder in folders:
        for path in (ROOT / folder).rglob("*"):
            if path.is_symlink() or not path.is_file() or path.suffix not in {".py", ".md", ".yaml", ".sh"}:
                continue
            if any(part.startswith("__") for part in path.relative_to(ROOT / folder).parts[:-1]):
                continue
            target = destination / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


@contextmanager
def isolated_environment():  # type: ignore[no-untyped-def]
    from db.url import db_url

    database = "railway_eval_" + uuid4().hex
    token = uuid4().hex
    admin = create_engine(db_url, isolation_level="AUTOCOMMIT")
    owned = create_engine(make_url(db_url).set(database=database))
    created = False
    with TemporaryDirectory(prefix="railway-eval-source-") as directory:
        source_copy(Path(directory))
        try:
            with admin.connect() as conn:
                conn.execute(text(f'CREATE DATABASE "{database}"'))
                created = True
            with owned.begin() as conn:
                conn.execute(text("CREATE TABLE public.railway_eval_owner (token text NOT NULL)"))
                conn.execute(text("INSERT INTO public.railway_eval_owner VALUES (:token)"), {"token": token})
            env = dict(os.environ)
            env.update(
                DB_DATABASE=database,
                RAILWAY_EVAL_DATABASE=database,
                RAILWAY_EVAL_TOKEN=token,
                RUNTIME_ENV="dev",
                SANDBOX_ENABLED="false",
                SANDBOX_RUNTIME_ARN="",
                SLACK_BOT_TOKEN="",
                SLACK_SIGNING_SECRET="",
                MCP_CONNECT_SECRET="",
                PYTHONPATH=str(ROOT),
            )
            yield env, directory
        finally:
            try:
                if created:
                    # Fail closed if ownership cannot be proved. Never sweep shared tables.
                    with owned.connect() as conn:
                        owner = conn.scalar(text("SELECT token FROM public.railway_eval_owner"))
                    if owner != token:
                        raise RuntimeError("Refusing to drop an eval database with a different owner")
                    owned.dispose()
                    with admin.connect() as conn:
                        conn.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            finally:
                owned.dispose()
                admin.dispose()


def require_isolation() -> None:
    """Fail closed before importing components or exposing the case collection."""
    database = os.getenv("RAILWAY_EVAL_DATABASE", "")
    if not re.fullmatch(DATABASE_PATTERN, database) or os.getenv("DB_DATABASE") != database:
        raise RuntimeError("Run cases through python -m evals; an isolated database is required")
    from db.url import db_url

    if make_url(db_url).database != database:
        raise RuntimeError("Eval database configuration was imported before isolation")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            owner = conn.scalar(text("SELECT token FROM public.railway_eval_owner"))
            if not owner or owner != os.getenv("RAILWAY_EVAL_TOKEN"):
                raise RuntimeError("Eval database ownership check failed")
    finally:
        engine.dispose()


async def run_isolated(arguments: list[str], *, capture: bool = False, timeout: int = 3600) -> tuple[int, str]:
    """Run the CLI worker; cancellation kills the child before database cleanup."""
    if os.getenv("RAILWAY_EVAL_DATABASE"):
        raise RuntimeError("Nested eval suites are not supported inside an eval worker")
    with isolated_environment() as (env, directory):
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "evals.worker",
                *arguments,
                cwd=directory,
                env=env,
                stdout=asyncio.subprocess.PIPE if capture else None,
                stderr=asyncio.subprocess.STDOUT if capture else None,
            )
        )
        try:
            process = await asyncio.shield(spawning)
        except BaseException:
            # Cancellation can arrive after fork but before the process handle is returned.
            process = await spawning
            await stop_worker(process)
            raise
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return process.returncode or 0, (output or b"").decode(errors="replace")
        finally:
            await stop_worker(process)


async def stop_worker(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await process.wait()
