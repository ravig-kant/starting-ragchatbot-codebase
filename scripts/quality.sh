#!/bin/bash
# Run all quality checks: formatting, linting, and tests.
set -e
cd "$(dirname "$0")/.."

./scripts/lint.sh

echo "Running tests (pytest)..."
(cd backend && uv run pytest -q)

echo "All quality checks passed."
