# .inform/qa/ — automated test/fix loop

The deterministic side of QA (ruff + pytest in CI, pre-commit hooks) lives at the repo root and ships to every client. **This directory is the agentic side**: a loop that runs the test suite, hands failures to Claude, applies the resulting edits, and re-runs until the suite is green or the iteration budget is exhausted.

It stays in `.inform/qa/` because it's Inform Growth's in-house workflow, not something every client should run unattended.

## Contents

```
.inform/qa/
  README.md                         this file
  scripts/
    fix_until_green.sh              the iterative loop (CLI / CI usage)
    install_qa_tooling.sh           copy this directory into a client repo
  skills/
    fix-until-green/
      SKILL.md                      Claude Code skill (interactive sessions)
```

## Usage — non-interactive (CLI / cron / Railway)

```bash
.inform/qa/scripts/fix_until_green.sh
```

Tunable env vars:

| Var | Default | Purpose |
|---|---|---|
| `FIX_MAX_ITERATIONS` | `5` | Hard cap on test→fix cycles |
| `FIX_TEST_CMD` | `pytest -x --no-header -q` | Test command (must exit non-zero on failure) |
| `FIX_MODEL` | `sonnet` | Claude model alias for the fix step |
| `FIX_BUDGET_USD` | `5` | Per-iteration `--max-budget-usd` ceiling |
| `FIX_ALLOWED_TOOLS` | `Edit Bash(pytest*) Bash(ruff*)` | Tools the fix-step agent may invoke |

Exit codes: `0` — green within budget; `1` — exhausted iterations without green; `2` — Claude CLI invocation failed.

## Usage — interactive (Claude Code session)

Type `/fix-until-green` (or invoke the skill manually) at any point. The skill instructs Claude to run the test command, analyze failures, propose minimal edits, apply them, and re-run, narrating each loop.

## Installing into a client repo

When Inform Growth is engaged to maintain a client gateway:

```bash
.inform/qa/scripts/install_qa_tooling.sh /path/to/client-repo
```

This rsyncs `.inform/qa/` into the destination repo. Add `.inform/` to that client's `.gitignore` if you'd rather not commit the tooling on their side, or commit it if it's part of the engagement deliverable.

## Why this isn't synced via distribute.yml

`distribute.yml` enumerates `CORE_FILES` and `CORE_DIRS`. `.inform/**` is never listed. The discipline is "secret sauce stays in `main`'s `.inform/`; it reaches client repos only via the manual installer."
