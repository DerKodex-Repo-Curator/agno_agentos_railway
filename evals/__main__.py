"""python -m evals [--tag smoke|release|live] [--name CASE] [--json-output FILE]."""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from evals.isolation import ROOT, run_isolated


def main() -> int:
    load_dotenv(ROOT / ".env")
    arguments = sys.argv[1:]
    # The worker reads sources from a temporary directory; output belongs to the caller.
    for i, argument in enumerate(arguments):
        if argument == "--json-output" and i + 1 < len(arguments):
            arguments[i + 1] = str(Path(arguments[i + 1]).resolve())
        elif argument.startswith("--json-output="):
            arguments[i] = "--json-output=" + str(Path(argument.split("=", 1)[1]).resolve())
    return asyncio.run(run_isolated(arguments))[0]


if __name__ == "__main__":
    sys.exit(main())
