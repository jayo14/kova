#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== Running Kova Production Launch Smoke Test Suite ==="

export ENVIRONMENT=development
export LOG_FORMAT=json
export SENTRY_DSN=""

cd "${ROOT_DIR}"
backend/.venv/bin/pytest backend/tests/smoke/ -v --tb=short

echo "=== All production launch smoke tests passed successfully! ==="
