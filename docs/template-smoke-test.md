# Template smoke test

A reproducible verification recipe for confirming the template scaffolds, installs, tests, and runs end-to-end. Run this before every push of a substantive change to the template branch.

## Prerequisites

- Python 3.11+ on PATH
- `pip install copier` (one-time, in any environment with pip)

## Steps

```bash
# 1. Fresh sandbox
SCRATCH=$(mktemp -d -t agent-gateway-smoke-XXXXXX)
echo "scratch dir: $SCRATCH"

# 2. Scaffold from the template branch (run from the template repo root)
copier copy --vcs-ref HEAD --trust --defaults . "$SCRATCH"
# Note: --defaults uses the Copier-generated random admin_token. Drop
# --defaults to be prompted for project_name, project_slug, etc.

# 3. Verify substitutions worked (no << >> placeholders should remain)
grep -rln "<<.*>>" "$SCRATCH" | grep -v ".git" || echo "all placeholders resolved"

# 4. Bootstrap a venv inside the scratch dir
cd "$SCRATCH"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 5. Run the test suite — should be 176 passing, no errors
pytest -q

# 6. Start the gateway (combined transport for SSE + streamable-HTTP)
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py > /tmp/gateway.log 2>&1 &
GW_PID=$!

# 7. Wait until the health endpoint responds
until curl -fs http://localhost:8000/health > /dev/null 2>&1; do sleep 1; done

# 8. Capture the scaffold-generated admin token from the startup log
ADMIN_TOKEN=$(grep -oE "scaffold-generated default '[a-f0-9]+'" /tmp/gateway.log | head -1 | sed -E "s/.*'([a-f0-9]+)'.*/\1/")
echo "admin token: $ADMIN_TOKEN"

# 9. Verify the seeded skill-creator is in SQLite as is_system=1
sqlite3 "$SCRATCH/data/telemetry.db" "SELECT name, is_system, org_id FROM skills;"
# Expect: skill-creator|1|default

# 10. Verify the admin API surfaces the skill
curl -s "http://localhost:8000/admin/api/skills?token=$ADMIN_TOKEN" | python3 -m json.tool | head -10

# 11. Cleanly shut down + tear down
kill $GW_PID
rm -rf "$SCRATCH" /tmp/gateway.log
```

## Expected results

| Step | Expectation |
|---|---|
| 3 | "all placeholders resolved" — no `<< x >>` literals leak through |
| 4 | venv creates; `pip install -e ".[dev]"` succeeds with no setuptools auto-discovery errors |
| 5 | `176 passed` (the count grows as new tests land — the floor is "all green, zero collection errors") |
| 6 | Gateway log shows `[system_skills] seeded 1 system skill(s) for org 'default'` and `Application startup complete.` |
| 7 | `/health` returns `{"status":"ok","transport":"combined"}` within ~3 seconds |
| 8 | The startup `[admin] WARNING` line includes a 32-char hex token (scaffold-generated, different per run) |
| 9 | Exactly one row: `skill-creator | 1 | default` |
| 10 | JSON list includes `skill-creator` with `is_system: 1` and the full prompt_template |

## What this proves

A client could clone the template branch, run `copier copy`, follow the README, and have a working gateway with the seeded skill-creator skill in their org's SQLite. Zero post-scaffold touch-ups required.

## What this does NOT prove

- End-to-end MCP client interaction with `run_skill("skill-creator", ...)` over a transport. The MCP `cli` from `mcp[cli]` can drive this if you want to extend the recipe; SQLite presence + admin API visibility is sufficient for the v1 smoke test.
- Real proxied integrations (HubSpot, etc.) — those require live vendor credentials and are out of scope for the template smoke test.
- Production-shaped deploys (Docker image, persistent volume, real ADMIN_TOKEN). The Dockerfile is shipped but not exercised here.

## When to re-run

- Before pushing to the template branch (and any future standalone template repo).
- After changes to `pyproject.toml`, `copier.yml`, `system_skills.json`, the seeder, or any startup code path.
- After ruff/pytest config changes.
