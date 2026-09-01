#!/bin/bash
set -e
export PATH="/opt/homebrew/bin:$PATH"
export PATH="/Users/adriandanao/.nvm/versions/node/v22.20.0/bin/:$PATH"
cd "$(dirname "$0")/.."

echo "=== Building combined site ==="
python3 filter.py combined
QUARTZ_SHARE_UI=1 npx quartz build
./scripts/fix-html-attachments.sh

echo "=== Deploying to NUC ==="
rsync -avz --delete public/ nuc:/var/www/org-notes/

echo "=== Done ==="
