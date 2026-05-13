#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "=== Building combined site ==="
python3 filter.py combined
npx quartz build

echo "=== Deploying to NUC ==="
rsync -avz --delete public/ nuc:/var/www/org-notes/

echo "=== Done ==="
