#!/bin/bash
# Check formatting and lint without modifying files.
set -e
cd "$(dirname "$0")/.."

echo "Checking import order (isort)..."
uv run isort --check-only --diff .

echo "Checking formatting (black)..."
uv run black --check --diff .

echo "Linting (flake8)..."
uv run flake8 .
