# Google Analytics Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proxy the official Google `analytics-mcp` package through the gateway so agents can query GA4 data via `google-analytics__*` tools.

**Architecture:** Add a `google-analytics` stdio entry to `mcp_connections.json` using `uvx analytics-mcp` (already available in the Docker image). Modify the Dockerfile CMD to decode a `GOOGLE_SA_JSON` env var into a credentials file before the gateway starts. Add a minimal field schema YAML for the registry.

**Tech Stack:** `analytics-mcp` (PyPI), `uvx` (already in Dockerfile), YAML field schema, pytest for config validation.

---

## File Map

| Action | File |
|---|---|
| Modify | `remote-gateway/mcp_connections.json` |
| Create | `remote-gateway/tests/test_google_analytics_config.py` |
| Create | `remote-gateway/context/fields/google-analytics.yaml` |
| Modify | `Dockerfile` |
| Modify | `remote-gateway/CLAUDE.md` |

---

### Task 1: Config test + `mcp_connections.json` entry

**Files:**
- Create: `remote-gateway/tests/test_google_analytics_config.py`
- Modify: `remote-gateway/mcp_connections.json`

- [ ] **Step 1.1: Write the failing tests**

Create `remote-gateway/tests/test_google_analytics_config.py`:

```python
"""
Validate the google-analytics entry in mcp_connections.json.

Run with:
    pytest remote-gateway/tests/test_google_analytics_config.py -v
"""
import json
from pathlib import Path

import pytest

CONNECTIONS_FILE = Path(__file__).parent.parent / "mcp_connections.json"

EXPECTED_TOOLS = [
    "run_report",
    "run_realtime_report",
    "run_funnel_report",
    "get_account_summaries",
    "get_property_details",
    "get_custom_dimensions_and_metrics",
    "list_google_ads_links",
]


def _load_ga() -> dict:
    if not CONNECTIONS_FILE.exists():
        pytest.fail(f"Config file not found: {CONNECTIONS_FILE}")
    data = json.loads(CONNECTIONS_FILE.read_text())
    if "google-analytics" not in data.get("connections", {}):
        pytest.fail("No 'google-analytics' entry found in connections.")
    return data["connections"]["google-analytics"]


def test_google_analytics_uses_stdio_transport():
    ga = _load_ga()
    assert ga["transport"] == "stdio", (
        f"Expected 'stdio', got '{ga.get('transport')}'. "
        "analytics-mcp is a subprocess — must use stdio transport."
    )


def test_google_analytics_command_is_uvx():
    ga = _load_ga()
    assert ga.get("command") == "uvx", (
        f"Expected command 'uvx', got '{ga.get('command')}'. "
        "uvx is already installed in the Dockerfile and is the correct runner."
    )


def test_google_analytics_args_are_analytics_mcp():
    ga = _load_ga()
    assert ga.get("args") == ["analytics-mcp"], (
        f"Expected args ['analytics-mcp'], got {ga.get('args')}."
    )


def test_google_analytics_env_has_credentials():
    ga = _load_ga()
    env = ga.get("env", {})
    assert "GOOGLE_APPLICATION_CREDENTIALS" in env, (
        f"Expected GOOGLE_APPLICATION_CREDENTIALS in env, got: {list(env.keys())}"
    )


def test_google_analytics_credentials_is_interpolated():
    ga = _load_ga()
    env = ga.get("env", {})
    assert env.get("GOOGLE_APPLICATION_CREDENTIALS") == "${GOOGLE_APPLICATION_CREDENTIALS}", (
        f"Expected '${{GOOGLE_APPLICATION_CREDENTIALS}}', got: {env.get('GOOGLE_APPLICATION_CREDENTIALS')}"
    )


def test_google_analytics_has_tools_allow_list():
    ga = _load_ga()
    tools = ga.get("tools", {})
    assert "allow" in tools, (
        "Expected 'tools.allow' in google-analytics config — allowlist enforces read-only access."
    )


def test_google_analytics_allow_list_contains_expected_tools():
    ga = _load_ga()
    allow = ga.get("tools", {}).get("allow", [])
    for tool in EXPECTED_TOOLS:
        assert tool in allow, (
            f"Expected '{tool}' in allow list, got: {allow}"
        )
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
pytest remote-gateway/tests/test_google_analytics_config.py -v
```

Expected: all 7 tests **FAIL** with `"No 'google-analytics' entry found in connections."`

- [ ] **Step 1.3: Add the entry to `mcp_connections.json`**

Open `remote-gateway/mcp_connections.json` and add the following entry inside the `"connections"` object (after the existing `"google"` entry):

```json
"google-analytics": {
  "_comment": "Read-only GA4 data via official analytics-mcp. Property ID is passed as a parameter on each tool call — document your property ID in the org profile so agents know which to use.",
  "transport": "stdio",
  "command": "uvx",
  "args": ["analytics-mcp"],
  "env": {
    "GOOGLE_APPLICATION_CREDENTIALS": "${GOOGLE_APPLICATION_CREDENTIALS}"
  },
  "tools": {
    "allow": [
      "run_report",
      "run_realtime_report",
      "run_funnel_report",
      "get_account_summaries",
      "get_property_details",
      "get_custom_dimensions_and_metrics",
      "list_google_ads_links"
    ]
  }
}
```

Make sure the JSON remains valid — the existing `"google"` entry needs a trailing comma before this new entry.

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
pytest remote-gateway/tests/test_google_analytics_config.py -v
```

Expected: all 7 tests **PASS**.

Also verify the full JSON parses without error:

```bash
python3 -c "import json; json.load(open('remote-gateway/mcp_connections.json')); print('valid JSON')"
```

Expected: `valid JSON`

- [ ] **Step 1.5: Run the full test suite to check for regressions**

```bash
pytest remote-gateway/tests/ -x -q
```

Expected: all existing tests still pass.

- [ ] **Step 1.6: Commit**

```bash
git add remote-gateway/mcp_connections.json remote-gateway/tests/test_google_analytics_config.py
git commit -m "feat(proxy): add google-analytics integration via analytics-mcp"
```

---

### Task 2: Field schema YAML

**Files:**
- Create: `remote-gateway/context/fields/google-analytics.yaml`
- Create test assertions inline in the test file below

GA4 `run_report` returns arbitrary dimension/metric combinations. This schema documents the most common standard metrics agents will request. It does not attempt to enumerate all 200+ GA4 dimensions/metrics.

- [ ] **Step 2.1: Write a failing test**

Add a new test file `remote-gateway/tests/test_google_analytics_fields.py`:

```python
"""
Validate that the google-analytics field schema YAML is well-formed.

Run with:
    pytest remote-gateway/tests/test_google_analytics_fields.py -v
"""
from pathlib import Path

import pytest
import yaml

FIELDS_FILE = Path(__file__).parent.parent / "context" / "fields" / "google-analytics.yaml"

REQUIRED_FIELDS = [
    "date",
    "sessions",
    "users",
    "activeUsers",
    "newUsers",
    "pageviews",
    "bounceRate",
    "averageSessionDuration",
    "eventCount",
]

REQUIRED_FIELD_KEYS = {"display_name", "description", "type", "notes", "nullable"}


def _load_schema() -> dict:
    if not FIELDS_FILE.exists():
        pytest.fail(f"Field schema not found: {FIELDS_FILE}")
    return yaml.safe_load(FIELDS_FILE.read_text())


def test_schema_has_correct_integration_name():
    schema = _load_schema()
    assert schema.get("integration") == "google-analytics", (
        f"Expected integration 'google-analytics', got: {schema.get('integration')}"
    )


def test_schema_has_fields_key():
    schema = _load_schema()
    assert "fields" in schema, "Expected top-level 'fields' key in YAML."


def test_schema_contains_required_fields():
    schema = _load_schema()
    fields = schema.get("fields", {})
    for field in REQUIRED_FIELDS:
        assert field in fields, f"Expected field '{field}' in google-analytics schema."


def test_each_field_has_required_keys():
    schema = _load_schema()
    for field_name, field_def in schema.get("fields", {}).items():
        missing = REQUIRED_FIELD_KEYS - set(field_def.keys())
        assert not missing, (
            f"Field '{field_name}' is missing keys: {missing}"
        )
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
pytest remote-gateway/tests/test_google_analytics_fields.py -v
```

Expected: **FAIL** with `"Field schema not found"`

- [ ] **Step 2.3: Create `remote-gateway/context/fields/google-analytics.yaml`**

```yaml
integration: google-analytics
fields:
  date:
    display_name: Date
    description: The date of the report row in YYYYMMDD format.
    type: string
    notes: GA4 returns dates as strings like '20240601'. Parse with datetime.strptime(v, '%Y%m%d').
    nullable: false
  sessions:
    display_name: Sessions
    description: Total number of sessions in the date range.
    type: number
    notes: A session is a group of user interactions within a 30-minute window.
    nullable: false
  users:
    display_name: Total Users
    description: Total number of unique users who triggered at least one event.
    type: number
    notes: ''
    nullable: false
  activeUsers:
    display_name: Active Users
    description: Number of distinct users who had an engaged session.
    type: number
    notes: This is the primary user metric in GA4 (replaces UA's 'Users').
    nullable: false
  newUsers:
    display_name: New Users
    description: Number of users who interacted with the site for the first time.
    type: number
    notes: ''
    nullable: false
  pageviews:
    display_name: Page Views
    description: Total number of pages viewed, including repeated views of a single page.
    type: number
    notes: ''
    nullable: false
  bounceRate:
    display_name: Bounce Rate
    description: Percentage of sessions that were not engaged (no events, <10s, single page).
    type: number
    notes: Returned as a decimal (e.g. 0.42 = 42%). Multiply by 100 for display.
    nullable: false
  averageSessionDuration:
    display_name: Avg Session Duration
    description: Average duration of sessions in seconds.
    type: number
    notes: Divide by 60 to convert to minutes for display.
    nullable: false
  eventCount:
    display_name: Event Count
    description: Total number of events logged in the date range.
    type: number
    notes: ''
    nullable: false
  conversions:
    display_name: Conversions
    description: Total number of conversion events.
    type: number
    notes: Requires conversion events to be configured in GA4 Admin.
    nullable: true
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
pytest remote-gateway/tests/test_google_analytics_fields.py -v
```

Expected: all 4 tests **PASS**.

- [ ] **Step 2.5: Commit**

```bash
git add remote-gateway/context/fields/google-analytics.yaml remote-gateway/tests/test_google_analytics_fields.py
git commit -m "feat(fields): add google-analytics field schema"
```

---

### Task 3: Dockerfile credentials handling

**Files:**
- Modify: `Dockerfile`

The current `CMD` is a single `sh -c` string. Extend it to decode `GOOGLE_SA_JSON` (raw service account JSON set as a Railway env var) into `/tmp/google-sa.json` and export `GOOGLE_APPLICATION_CREDENTIALS` before starting the gateway.

- [ ] **Step 3.1: Verify the shell logic works locally before touching the Dockerfile**

Run this in your terminal to confirm the decode logic behaves correctly:

```bash
export GOOGLE_SA_JSON='{"type":"service_account","project_id":"test"}'
sh -c 'if [ -n "$GOOGLE_SA_JSON" ]; then printf "%s" "$GOOGLE_SA_JSON" > /tmp/google-sa.json && echo "wrote credentials"; fi'
cat /tmp/google-sa.json
```

Expected output:
```
wrote credentials
{"type":"service_account","project_id":"test"}
```

Also verify the empty case is safe (gateway should start normally with no GA credentials):

```bash
unset GOOGLE_SA_JSON
sh -c 'if [ -n "$GOOGLE_SA_JSON" ]; then printf "%s" "$GOOGLE_SA_JSON" > /tmp/google-sa.json; fi && echo "gateway would start here"'
```

Expected output: `gateway would start here`

- [ ] **Step 3.2: Update the `CMD` in `Dockerfile`**

Find the current last line of the Dockerfile:

```dockerfile
CMD ["sh", "-c", "MCP_SERVER_PORT=${PORT:-8000} python3 remote-gateway/core/mcp_server.py"]
```

Replace it with:

```dockerfile
CMD ["sh", "-c", "if [ -n \"$GOOGLE_SA_JSON\" ]; then printf '%s' \"$GOOGLE_SA_JSON\" > /tmp/google-sa.json && export GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-sa.json; fi && MCP_SERVER_PORT=${PORT:-8000} python3 remote-gateway/core/mcp_server.py"]
```

- [ ] **Step 3.3: Verify the Dockerfile still builds**

```bash
docker build -t gateway-ga-test . 2>&1 | tail -5
```

Expected: `Successfully built <id>` (or equivalent). No build errors.

If Docker is not available locally, skip to Step 3.4 and rely on Railway CI.

- [ ] **Step 3.4: Commit**

```bash
git add Dockerfile
git commit -m "feat(dockerfile): decode GOOGLE_SA_JSON to credentials file at startup"
```

---

### Task 4: Document the new env vars

**Files:**
- Modify: `remote-gateway/CLAUDE.md`

- [ ] **Step 4.1: Add the two new rows to the Environment Variables table**

In `remote-gateway/CLAUDE.md`, find the `### Environment Variables` table and add these two rows after the existing Google OAuth rows:

```markdown
| `GOOGLE_SA_JSON` | GA | Raw service account JSON key content. Set this in Railway; the startup script writes it to `/tmp/google-sa.json` and exports `GOOGLE_APPLICATION_CREDENTIALS`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | GA (auto) | Set automatically by the startup script to `/tmp/google-sa.json` when `GOOGLE_SA_JSON` is present. Can also be set directly to a mounted file path. |
```

- [ ] **Step 4.2: Run the full test suite one final time**

```bash
pytest remote-gateway/tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 4.3: Commit**

```bash
git add remote-gateway/CLAUDE.md
git commit -m "docs: document GOOGLE_SA_JSON and GOOGLE_APPLICATION_CREDENTIALS env vars"
```

---

## Railway Setup (post-deploy)

After deploying, set these env vars in Railway:

1. **`GOOGLE_SA_JSON`** — paste the full contents of the service account JSON key file
2. Trigger a redeploy so the new Dockerfile CMD runs

To verify the integration is live, call `health_check` then ask an agent to call `google-analytics__get_account_summaries` — it will list all GA4 properties the service account can access.
