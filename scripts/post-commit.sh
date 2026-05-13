#!/bin/bash
# Git post-commit hook - rebuilds the Quartz site after commits

ORG_QUARTZ="${ORG_QUARTZ:-$HOME/git/org-quartz}"

if [ ! -d "$ORG_QUARTZ" ]; then
    echo "org-quartz not found at $ORG_QUARTZ, skipping rebuild"
    exit 0
fi

# Run build in background to not block the commit
(
    cd "$ORG_QUARTZ"
    ./scripts/build.sh combined > /tmp/org-quartz-build.log 2>&1
) &

echo "Quartz rebuild triggered in background"
