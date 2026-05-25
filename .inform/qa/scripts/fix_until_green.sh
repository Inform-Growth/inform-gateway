#!/usr/bin/env bash
# fix_until_green.sh — run tests; if they fail, ask Claude to fix; repeat.
#
# This is the unattended/CLI form. For interactive sessions inside Claude Code,
# invoke the .inform/qa/skills/fix-until-green/SKILL.md skill instead.
#
# Exit codes:
#   0 — tests passed within FIX_MAX_ITERATIONS
#   1 — tests still failing after FIX_MAX_ITERATIONS
#   2 — required tool missing (claude CLI, etc.)

set -uo pipefail

: "${FIX_MAX_ITERATIONS:=5}"
: "${FIX_TEST_CMD:=pytest -x --no-header -q}"
: "${FIX_MODEL:=sonnet}"
: "${FIX_BUDGET_USD:=5}"
: "${FIX_ALLOWED_TOOLS:=Edit Bash(pytest*) Bash(ruff*) Bash(python*)}"

if ! command -v claude >/dev/null 2>&1; then
  echo "error: claude CLI not on PATH. Install from https://github.com/anthropics/claude-code" >&2
  exit 2
fi

echo "fix_until_green: max_iterations=$FIX_MAX_ITERATIONS model=$FIX_MODEL budget=\$$FIX_BUDGET_USD/iter"
echo "fix_until_green: test cmd: $FIX_TEST_CMD"
echo "fix_until_green: allowed tools: $FIX_ALLOWED_TOOLS"
echo

TMP_OUT=$(mktemp -t fix-until-green-XXXXXX.log)
trap 'rm -f "$TMP_OUT"' EXIT

for i in $(seq 1 "$FIX_MAX_ITERATIONS"); do
  echo "=== iteration $i/$FIX_MAX_ITERATIONS: running tests ==="
  if $FIX_TEST_CMD >"$TMP_OUT" 2>&1; then
    cat "$TMP_OUT"
    echo
    echo "=== tests green after $i iteration(s) ==="
    exit 0
  fi

  cat "$TMP_OUT"
  echo
  echo "=== iteration $i: tests failed; invoking claude to fix ==="

  PROMPT="The test command \`$FIX_TEST_CMD\` failed. Fix the source code (not the tests, unless a test is clearly wrong) so the suite passes. Be surgical — only change what the failure requires. Do not refactor unrelated code. When done, do not run the tests yourself; the harness will re-run them.

Test output below:

$(cat "$TMP_OUT")"

  # shellcheck disable=SC2086  # FIX_ALLOWED_TOOLS is a deliberate word-split list
  if ! claude --print \
       --model "$FIX_MODEL" \
       --max-budget-usd "$FIX_BUDGET_USD" \
       --allowedTools $FIX_ALLOWED_TOOLS \
       "$PROMPT"; then
    echo "error: claude invocation failed on iteration $i" >&2
    exit 2
  fi
  echo
done

echo "=== did not reach green after $FIX_MAX_ITERATIONS iteration(s) — exiting ==="
exit 1
