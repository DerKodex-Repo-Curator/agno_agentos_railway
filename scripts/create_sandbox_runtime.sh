#!/usr/bin/env bash
# Uses an existing ECR image and IAM role. Creates/updates one runtime per deployment.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${SANDBOX_IMAGE:?Set SANDBOX_IMAGE to the pushed ECR image URI}"
export AWS_PROFILE="${AWS_PROFILE:-agno-staging-agentcore}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export SANDBOX_RUNTIME_NAME="${SANDBOX_RUNTIME_NAME:-agno_company_engineer}"
export SANDBOX_EXECUTION_ROLE="${SANDBOX_EXECUTION_ROLE:-arn:aws:iam::175651002206:role/agno-agentcore-runtime-staging}"
exec uv run --no-project --with-requirements requirements.txt python - <<'PY'
import os
import re
import time
import boto3

name = os.environ["SANDBOX_RUNTIME_NAME"]
if not re.fullmatch(r"agno_[A-Za-z0-9_]+", name):
    raise SystemExit("SANDBOX_RUNTIME_NAME must start with agno_ and contain only letters, digits and underscores")
control = boto3.Session(region_name=os.environ["AWS_REGION"]).client("bedrock-agentcore-control")
config = dict(
    agentRuntimeArtifact={"containerConfiguration": {"containerUri": os.environ["SANDBOX_IMAGE"]}},
    roleArn=os.environ["SANDBOX_EXECUTION_ROLE"],
    networkConfiguration={"networkMode": "PUBLIC"},
    lifecycleConfiguration={"idleRuntimeSessionTimeout": 900, "maxLifetime": 3600},
)
existing = []
request = {}
while True:
    page = control.list_agent_runtimes(**request)
    existing.extend(r for r in page["agentRuntimes"] if r["agentRuntimeName"] == name)
    if not page.get("nextToken"):
        break
    request = {"nextToken": page["nextToken"]}
if existing:
    runtime_id = existing[0]["agentRuntimeId"]
    control.update_agent_runtime(agentRuntimeId=runtime_id, **config)
else:
    runtime_id = control.create_agent_runtime(agentRuntimeName=name, **config)["agentRuntimeId"]
for _ in range(120):
    runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
    if runtime["status"] == "READY":
        print(runtime["agentRuntimeArn"])
        break
    if runtime["status"] not in ("CREATING", "UPDATING"):
        raise SystemExit(f"Runtime is {runtime['status']}: {runtime.get('failureReason')}")
    time.sleep(5)
else:
    raise SystemExit(f"Timed out waiting for {runtime_id}; inspect it before retrying")
PY
