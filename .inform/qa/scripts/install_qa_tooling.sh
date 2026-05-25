#!/usr/bin/env bash
# install_qa_tooling.sh — copy this .inform/qa/ tree into a client repo.
#
# Usage:
#   .inform/qa/scripts/install_qa_tooling.sh <path-to-client-repo>
#
# Effect:
#   rsync -a --delete-after .inform/qa/ <client>/.inform/qa/
#
# The destination's own .inform/ (if it exists for something other than QA) is
# left untouched — only the qa/ subtree is replaced. We use --delete-after so
# files removed upstream also disappear in the client.

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <path-to-client-repo>" >&2
  exit 2
fi

DEST="$1"
if [ ! -d "$DEST" ]; then
  echo "error: $DEST is not a directory" >&2
  exit 2
fi
if [ ! -d "$DEST/.git" ]; then
  echo "error: $DEST does not look like a git repo (no .git/)" >&2
  exit 2
fi

SRC_QA="$(cd "$(dirname "$0")/.." && pwd)"   # → .inform/qa/

if [ ! -d "$SRC_QA" ]; then
  echo "error: source $SRC_QA missing — run from inside inform-gateway" >&2
  exit 2
fi

echo "installing .inform/qa/ → $DEST/.inform/qa/"
mkdir -p "$DEST/.inform/qa"
rsync -a --delete-after "$SRC_QA"/ "$DEST/.inform/qa/"
echo
echo "✓ installed."
echo
echo "Next steps in $DEST:"
echo "  - decide whether to commit .inform/qa/ or add .inform/ to .gitignore"
echo "  - run .inform/qa/scripts/fix_until_green.sh to verify"
