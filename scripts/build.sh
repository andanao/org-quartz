#!/bin/bash
set -e

MODE="${1:-personal}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Filtering and exporting org files (mode: $MODE) ==="
python3 filter.py "$MODE"

echo "=== Building Quartz ==="
# Include the share controls. Only builds that run through here get them; the
# GitHub Pages workflow calls `npx quartz build` directly, so the public site
# ships neither the markup nor the script. Reveal them with ?share=1.
QUARTZ_SHARE_UI=1 npx quartz build

echo "=== Done ==="
echo "Output in: $PROJECT_DIR/public/"
