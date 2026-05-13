#!/bin/bash
set -e

MODE="${1:-personal}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Filtering and exporting org files (mode: $MODE) ==="
python3 filter.py "$MODE"

echo "=== Building Quartz ==="
npx quartz build

echo "=== Done ==="
echo "Output in: $PROJECT_DIR/public/"
