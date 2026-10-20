#!/usr/bin/env bash

############################################################################
#
#    Agno AgentCore Sandbox Runtime
#
#    Creates or updates one runtime per deployment, then waits for READY.
#
#    Usage:
#      export SANDBOX_IMAGE=<pushed-ecr-uri>:<tag>
#      export SANDBOX_RUNTIME_NAME=<unique-deployment-name>
#      export SANDBOX_EXECUTION_ROLE=<iam-role-arn>
#      ./scripts/create_sandbox_runtime.sh
#
#    Prerequisites:
#      - uv installed, AWS credentials and an existing runtime IAM role
#      - ARM64 image pushed with ./scripts/build_sandbox_image.sh push
#
#    AWS_REGION defaults to us-east-1. Progress goes to stderr; stdout
#    contains the ready runtime ARN for use as SANDBOX_RUNTIME_ARN.
#
############################################################################

set -euo pipefail
cd "$(dirname "$0")/.."
: "${SANDBOX_IMAGE:?Set SANDBOX_IMAGE to the pushed ECR image URI}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
: "${SANDBOX_RUNTIME_NAME:?Set a unique SANDBOX_RUNTIME_NAME for this deployment}"
export SANDBOX_RUNTIME_NAME
: "${SANDBOX_EXECUTION_ROLE:?Set SANDBOX_EXECUTION_ROLE to your runtime IAM role ARN}"
export SANDBOX_EXECUTION_ROLE

# Keep stdout usable by callers capturing the runtime ARN.
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

echo "" >&2
echo -e "${ORANGE}▸${NC} ${BOLD}Configuring AgentCore sandbox runtime${NC}" >&2
echo -e "${DIM}Runtime: ${SANDBOX_RUNTIME_NAME}; region: ${AWS_REGION}${NC}" >&2
echo -e "${DIM}Waiting up to 10 minutes for READY...${NC}" >&2
echo "" >&2

exec uv run --no-project --with-requirements requirements.txt python - <<'PY'
import os
import re
import sys
import time
import boto3

name = os.environ["SANDBOX_RUNTIME_NAME"]
if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", name):
    raise SystemExit("SANDBOX_RUNTIME_NAME must start with a letter, contain only letters, digits and underscores, and be at most 48 characters")
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
        print("Done. Runtime ready; set SANDBOX_RUNTIME_ARN to the ARN below.", file=sys.stderr)
        print(runtime["agentRuntimeArn"])
        break
    if runtime["status"] not in ("CREATING", "UPDATING"):
        raise SystemExit(f"Runtime is {runtime['status']}: {runtime.get('failureReason')}")
    time.sleep(5)
else:
    raise SystemExit(f"Timed out waiting for {runtime_id}; inspect it before retrying")
PY
