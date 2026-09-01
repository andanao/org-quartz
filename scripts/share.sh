#!/bin/bash
# Export a built note as a standalone file for someone outside the network.
#
#   ./scripts/share.sh "Acme kickoff"        -> share/acme-kickoff.html
#   ./scripts/share.sh acme-kickoff --pdf    -> ... and share/acme-kickoff.pdf
#
# Reads from public/, so build first if the note has changed.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$(dirname "$SCRIPT_DIR")"

exec npx tsx scripts/share.ts "$@"
