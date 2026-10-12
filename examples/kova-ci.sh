#!/usr/bin/env bash
# Kova Continuous Validation CI Runner script
set -euo pipefail

# Configuration
KOVA_API_URL="${KOVA_API_URL:-https://api.kova.dev}"
KOVA_API_TOKEN="${KOVA_API_TOKEN:?KOVA_API_TOKEN is required}"
KOVA_PROJECT_ID="${KOVA_PROJECT_ID:?KOVA_PROJECT_ID is required}"
TARGET_BASE_URL="${TARGET_BASE_URL:-}"
VALIDATION_SCOPE="${VALIDATION_SCOPE:-targeted}"

# Git context
COMMIT_SHA="${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo '')}"
BRANCH_NAME="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')}"
CHANGED_FILES="$(git diff --name-only HEAD~1 HEAD 2>/dev/null | tr '\n' ',' | sed 's/,$//' || echo '')"

echo "=========================================================="
echo " Running Kova Continuous Validation ($VALIDATION_SCOPE)"
echo " Project: $KOVA_PROJECT_ID"
echo " Commit:  $COMMIT_SHA"
echo " Files:   $CHANGED_FILES"
echo "=========================================================="

python3 scripts/kova_ci.py \
  --project-id "$KOVA_PROJECT_ID" \
  --api-token "$KOVA_API_TOKEN" \
  --api-url "$KOVA_API_URL" \
  --commit-sha "$COMMIT_SHA" \
  --branch "$BRANCH_NAME" \
  --scope "$VALIDATION_SCOPE" \
  ${TARGET_BASE_URL:+--base-url "$TARGET_BASE_URL"} \
  ${CHANGED_FILES:+--changed-files "$CHANGED_FILES"}

EXIT_CODE=$?
echo "Kova validation finished with exit code $EXIT_CODE"
exit $EXIT_CODE
