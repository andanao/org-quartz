#!/bin/bash
set -e

NUC_HOST="${NUC_HOST:-nuc.local}"
NUC_PATH="${NUC_PATH:-/var/www/org-notes}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Building combined site ==="
./scripts/build.sh combined

echo "=== Deploying to ${NUC_HOST}:${NUC_PATH} ==="
rsync -avz --delete public/ "${NUC_HOST}:${NUC_PATH}/"

echo "=== Done ==="
