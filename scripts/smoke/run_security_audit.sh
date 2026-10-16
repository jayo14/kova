#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== Running Security Invariant Forensic Audit ==="
export SENTRY_DSN=""

# 1. Assert no demo endpoints exist in backend routes
echo "Checking for demo endpoints..."
if grep -rn "/api/v1/demo/" "${ROOT_DIR}/backend/app/api/routes/"; then
    echo "ERROR: Demo endpoints found in backend routes!"
    exit 1
fi
echo "✓ No demo endpoints found."

# 2. Assert no hardcoded secrets in settings default production mode
echo "Checking security invariants with pytest..."
"${ROOT_DIR}/backend/.venv/bin/pytest" "${ROOT_DIR}/backend/tests/smoke/test_security_invariants.py" -v

echo "=== Security Audit Passed! ==="
