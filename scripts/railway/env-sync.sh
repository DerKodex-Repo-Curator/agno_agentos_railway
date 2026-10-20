#!/bin/bash

############################################################################
#
#    Agno Railway Environment Sync
#
#    Usage:
#      ./scripts/railway/env-sync.sh             # syncs .env.production
#      ./scripts/railway/env-sync.sh .env        # syncs .env instead
#      ./scripts/railway/env-sync.sh --no-deploy # push variables, don't redeploy
#
#    Validates the whole file before pushing variables to the Railway agent-os
#    service. Accepts optional export prefixes, quoted multiline values and
#    unquoted PEM blocks. Values are read literally, never executed as shell.
#
#    Variables are pushed with --skip-deploys and one redeploy is triggered
#    at the end, so a twenty-variable file costs one build instead of twenty.
#    A railway CLI without that flag falls back to its own deploy-per-variable.
#    With --no-deploy, that older CLI is rejected before uploading anything.
#
#    Optional environment:
#      ALLOW_UNAUTHENTICATED_DEPLOY  set to 1 to let RUNTIME_ENV=dev through,
#                                    which serves the public domain with auth off
#
############################################################################

set -e

# Colors
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
RED='\033[31m'
NC='\033[0m'

ENV_FILE=""
REDEPLOY=1
for arg in "$@"; do
    case "$arg" in
        --no-deploy) REDEPLOY="" ;;
        -*)
            echo "Unknown option: $arg"
            echo "Usage: $0 [path/to/env] [--no-deploy] (default file: .env.production)"
            exit 1
            ;;
        *) ENV_FILE="$arg" ;;
    esac
done
ENV_FILE="${ENV_FILE:-.env.production}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "File not found: $ENV_FILE"
    echo "Usage: $0 [path/to/env] [--no-deploy] (default: .env.production)"
    exit 1
fi

# Parse everything before making remote changes. Keep the validated values in
# memory so an edit during sync cannot replace them with unchecked input.
ENV_KEYS=()
ENV_VALUES=()
current_key=""
current_value=""
quote=""
line_number=0
value_line=0

invalid_env() {
    # Name the line, not its contents: malformed input may contain a secret.
    echo -e "${RED}${BOLD}Invalid env file${NC}: ${ENV_FILE}:${1}: ${2}" >&2
    exit 1
}

while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    line="${line%$'\r'}"
    if [[ -z "$current_key" ]]; then
        [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
        if [[ ! "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]]; then
            invalid_env "$line_number" "expected KEY=value or export KEY=value"
        fi
        current_key="${BASH_REMATCH[2]}"
        current_value="${BASH_REMATCH[3]}"
        value_line="$line_number"
        current_value="${current_value#"${current_value%%[![:space:]]*}"}"
        quote=""
        if [[ "$current_value" == \"* || "$current_value" == \'* ]]; then
            quote="${current_value:0:1}"
            current_value="${current_value:1}"
        fi
    else
        current_value="${current_value}
${line}"
    fi

    if [[ -n "$quote" ]]; then
        # Stop at the first unescaped closing quote. A quote in an inline
        # comment belongs to the comment, never to the value.
        closing_quote="^(([^${quote}\\\\]|\\\\.)*)${quote}(.*)$"
        [[ "$current_value" =~ $closing_quote ]] || continue
        current_value="${BASH_REMATCH[1]}"
        trailing="${BASH_REMATCH[3]}"
        if [[ ! "$trailing" =~ ^[[:space:]]*(#.*)?$ ]]; then
            invalid_env "$value_line" "unexpected text after closing quote"
        fi
        quote=""
        if [[ "$current_value" == *"-----BEGIN"* && "$current_value" != *"-----END"* ]]; then
            invalid_env "$value_line" "PEM block is missing its END marker"
        fi
    else
        # An unquoted PEM may span lines. Other unquoted values end at an
        # inline comment introduced by whitespace, as in example.env.
        [[ "$current_value" == \#* ]] && current_value=""
        if [[ "$current_value" == *"-----BEGIN"* && "$current_value" != *"-----END"* ]]; then
            continue
        fi
        current_value="${current_value%%[[:space:]]#*}"
        current_value="${current_value%"${current_value##*[![:space:]]}"}"
    fi

    ENV_KEYS+=("$current_key")
    ENV_VALUES+=("$current_value")
    current_key=""
    current_value=""
done < "$ENV_FILE"

if [[ -n "$current_key" ]]; then
    invalid_env "$value_line" "unterminated quoted value or PEM block"
fi

if ! command -v railway &> /dev/null; then
    echo "Railway CLI not found. Install: https://docs.railway.com/cli#installing-the-cli"
    exit 1
fi

if ! railway status &> /dev/null; then
    echo "Not linked to a Railway project. Run ./scripts/railway/up.sh first."
    exit 1
fi

# Probed once from --help so an older railway binary degrades to one deploy per
# variable instead of dying on an unknown argument.
VAR_SET_FLAGS=()
railway variables --help 2>&1 | grep -q -- '--skip-deploys' && VAR_SET_FLAGS=(--skip-deploys)
if [[ -z "$REDEPLOY" && ${#VAR_SET_FLAGS[@]} -eq 0 ]]; then
    echo -e "${RED}${BOLD}Cannot honor --no-deploy.${NC} This Railway CLI does not support --skip-deploys." >&2
    echo "Upgrade the Railway CLI before retrying. No variables were uploaded." >&2
    exit 1
fi

echo ""
echo -e "${ORANGE}▸${NC} ${BOLD}Syncing env vars${NC}"
echo ""
echo -e "${DIM}> ${ENV_FILE} -> Railway service agent-os${NC}"
echo ""

count=0
skipped=0
failed=0
for ((index = 0; index < ${#ENV_KEYS[@]}; index++)); do
    current_key="${ENV_KEYS[index]}"
    current_value="${ENV_VALUES[index]}"

    # app/main.py passes `authorization=runtime_env != "dev"`, so this one value
    # turns production auth off for a service on a public domain. It reaches env
    # files honestly — compose sets it for local work, and `cp .env
    # .env.production` carries it over — which makes syncing it the quiet way a
    # gated deploy becomes an open one. Leave it out unless asked twice.
    if [[ "$current_key" == "RUNTIME_ENV" && "$current_value" == "dev" ]] \
        && [[ "$ALLOW_UNAUTHENTICATED_DEPLOY" != "1" ]]; then
        echo -e "${RED}${BOLD}  Not syncing RUNTIME_ENV=dev${NC} — it would serve the public domain with auth off."
        echo -e "${DIM}    Remove it from ${ENV_FILE} (it defaults to prd), or re-run with${NC}"
        echo -e "${DIM}    ALLOW_UNAUTHENTICATED_DEPLOY=1 if an open platform is what you want.${NC}"
        echo -e "${DIM}    Note this only declines to push it — a service already set to dev stays dev.${NC}"
        skipped=$((skipped + 1))
        continue
    fi

    echo -e "${DIM}  Setting ${current_key}${NC}"
    # stdout is dropped so a value the CLI echoes back never reaches the terminal
    # or a captured log; stderr is captured rather than discarded, because the
    # old `2>/dev/null` turned a rejected push into a blank line in a run that
    # otherwise looked complete. Errors are scrubbed of the value before display.
    err=""
    status=0
    # Keep the CLI from consuming caller input or waiting for a prompt.
    err="$(railway variables --set "${current_key}=${current_value}" --service agent-os \
        "${VAR_SET_FLAGS[@]}" 2>&1 > /dev/null < /dev/null)" || status=$?
    if [[ "$status" != 0 ]]; then
        echo -e "${RED}    Failed${NC} (railway exited ${status})."
        [[ -n "$err" ]] && echo -e "${DIM}    ${err//${current_value}/<value hidden>}${NC}"
        failed=$((failed + 1))
    else
        count=$((count + 1))
    fi

done

echo ""
if [[ "$failed" -gt 0 ]]; then
    echo -e "${RED}${BOLD}Synced ${count} variable(s), ${failed} failed.${NC}"
    echo -e "${DIM}The service now holds a partial set — fix the errors above and re-run before deploying.${NC}"
    echo ""
    exit 1
fi

SKIPPED_NOTE=""
[[ "$skipped" -gt 0 ]] && SKIPPED_NOTE=" Left ${skipped} out (see above)."
echo -e "Synced ${count} variable(s) to Railway.${SKIPPED_NOTE}"

# One build for the whole file instead of one per variable.
if [[ ${#VAR_SET_FLAGS[@]} -eq 0 ]]; then
    # No --skip-deploys on this CLI, so every value already triggered its own
    # deploy on the way in. A redeploy here would only add one more build.
    echo -e "${DIM}Railway redeployed as each value landed — this CLI has no --skip-deploys.${NC}"
elif [[ -n "$REDEPLOY" && "$count" -gt 0 ]]; then
    echo -e "${DIM}Redeploying agent-os so the new values take effect...${NC}"
    if ! railway redeploy --service agent-os --yes; then
        echo -e "${RED}${BOLD}Redeploy failed.${NC} Variables were synced, but deployment was not confirmed."
        echo -e "${DIM}Retry with ./scripts/railway/redeploy.sh once the values look right.${NC}"
        exit 1
    fi
else
    echo -e "${DIM}No redeploy triggered — run ./scripts/railway/redeploy.sh to pick the values up.${NC}"
fi
echo -e "${BOLD}Done.${NC}"
echo ""
