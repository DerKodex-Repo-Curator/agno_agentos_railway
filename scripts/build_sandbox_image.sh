#!/usr/bin/env bash

############################################################################
#
#    Agno Sandbox Image Builder
#
#    Usage:
#      ./scripts/build_sandbox_image.sh local
#      SANDBOX_IMAGE=<ecr-uri>:<tag> ./scripts/build_sandbox_image.sh push
#
#    Prerequisites:
#      - Python 3 and Docker running
#      - For push: AWS CLI, ECR repository and credentials with push access
#
#    Local builds use agno-sandbox:local. Push builds target linux/arm64
#    for AgentCore. AWS_REGION defaults to us-east-1; use an immutable tag.
#
############################################################################

set -euo pipefail
cd "$(dirname "$0")/.."

# Colors
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

case "${1:-local}" in
  local)
    echo ""
    echo -e "${ORANGE}▸${NC} ${BOLD}Building local sandbox image${NC}"
    echo -e "${DIM}> python3 sandbox/build_image.py --tag agno-sandbox:local${NC}"
    echo ""
    python3 sandbox/build_image.py --tag agno-sandbox:local
    ;;
  push)
    : "${SANDBOX_IMAGE:?Set SANDBOX_IMAGE to the ECR image URI (include an immutable tag)}"
    region="${AWS_REGION:-us-east-1}"
    echo ""
    echo -e "${ORANGE}▸${NC} ${BOLD}Building and pushing sandbox image${NC}"
    echo -e "${DIM}Image: ${SANDBOX_IMAGE}${NC}"
    echo -e "${DIM}Platform: linux/arm64; region: ${region}${NC}"
    echo ""
    aws --region "$region" ecr get-login-password |
      docker login --username AWS --password-stdin "${SANDBOX_IMAGE%%/*}"
    echo -e "${DIM}> python3 sandbox/build_image.py --platform linux/arm64 --tag ${SANDBOX_IMAGE}${NC}"
    python3 sandbox/build_image.py --platform linux/arm64 --tag "$SANDBOX_IMAGE"
    echo -e "${DIM}> docker push ${SANDBOX_IMAGE}${NC}"
    docker push "$SANDBOX_IMAGE"
    ;;
  *) echo "Usage: $0 local|push" >&2; exit 2 ;;
esac

echo ""
echo -e "${BOLD}Done.${NC}"
echo ""
