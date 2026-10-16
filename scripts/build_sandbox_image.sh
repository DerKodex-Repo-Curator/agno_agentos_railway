#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-local}" in
  local)
    python3 sandbox/build_image.py --tag agno-sandbox:local
    ;;
  push)
    : "${SANDBOX_IMAGE:?Set SANDBOX_IMAGE to the ECR image URI (include an immutable tag)}"
    region="${AWS_REGION:-us-east-1}"
    aws --region "$region" ecr get-login-password |
      docker login --username AWS --password-stdin "${SANDBOX_IMAGE%%/*}"
    python3 sandbox/build_image.py --platform linux/arm64 --tag "$SANDBOX_IMAGE"
    docker push "$SANDBOX_IMAGE"
    ;;
  *) echo "Usage: $0 local|push" >&2; exit 2 ;;
esac
