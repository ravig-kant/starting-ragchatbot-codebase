#!/bin/bash
# Auto-format all Python code (sort imports, then apply black).
set -e
cd "$(dirname "$0")/.."

echo "Sorting imports with isort..."
uv run isort .

echo "Formatting with black..."
uv run black .
