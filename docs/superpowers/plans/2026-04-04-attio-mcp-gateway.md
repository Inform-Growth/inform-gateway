# Attio MCP Gateway Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile OAuth-based Attio connection in the remote gateway with the `attio-mcp` stdio server, authenticated via a long-lived API key.

**Architecture:** The gateway's existing `mcp_proxy.py` stdio path spawns `npx attio-mcp` as a subprocess at startup. The subprocess connects to Attio's REST API using `ATTIO_API_KEY`. Tools appear to operators as `attio__<tool_name>`.

**Tech Stack:** Python 3.14, FastMCP, `attio-mcp` (npm), nixpacks (Railway), pytest

---

## File Map

| File | Action | What changes |
|---|---|---|
| `remote-gateway/mcp_connections.json` | Modify | Replace attio entry: http+OAuth → stdio+API key |
| `nixpacks.toml` | Modify | Add `[phases.setup]` with `nodejs_20` |
| `remote-gateway/.env.example` | Modify | Replace 3 OAuth vars with `ATTIO_API_KEY` |
| `remote-gateway/tests/test_attio_config.py` | Create | Validates attio connection config structure |

`mcp_proxy.py` and `mcp_server.py` are **not modified**.

---

### Task 1: Write a failing config validation test

This test asserts the attio entry uses stdio transport with the correct env structure. It will fail against the current config (which uses `http`), then pass after Task 2.

**Files:**
- Create: `remote-gateway/tests/test_attio_config.py`

- [ ] **Step 1: Create the test file**

```python
"""
Validate that the attio entry in mcp_connections.json uses stdio transport
with the expected command and env structure (no OAuth blocks).

Run with:
    pytest remote-gateway/tests/test_attio_config.py -v
"""
import json
from pathlib import Path


CONNECTIONS_FILE = Path(__file__).parent.parent / "mcp_connections.json"


def _load_attio() -> dict:
    data = json.loads(CONNECTIONS_FILE.read_text())
    return data["connections"]["attio"]


def test_attio_uses_stdio_transport():
    attio = _load_attio()
    assert attio["transport"] == "stdio", (
        f"Expected 'stdio', got '{attio.get('transport')}'. "
        "The attio connection must use stdio, not http."
    )


def test_attio_command_is_npx():
    attio = _load_attio()
    assert attio["command"] == "npx", (
        f"Expected command 'npx', got '{attio.get('command')}'"
    )


def test_attio_args_include_attio_mcp():
    attio = _load_attio()
    assert "attio-mcp" in attio.get("args", []), (
        f"Expected 'attio-mcp' in args, got: {attio.get('args')}"
    )


def test_attio_env_has_api_key_reference():
    attio = _load_attio()
    env = attio.get("env", {})
    assert "ATTIO_API_KEY" in env, (
        f"Expected ATTIO_API_KEY in env, got keys: {list(env.keys())}"
    )
    assert env["ATTIO_API_KEY"] == "${ATTIO_API_KEY}", (
        f"Expected '${{ATTIO_API_KEY}}', got: {env['ATTIO_API_KEY']}"
    )


def test_attio_has_no_oauth_block():
    attio = _load_attio()
    assert "oauth" not in attio, (
        "Found 'oauth' block in attio config — OAuth must be removed."
    )


def test_attio_has_no_headers_block():
    attio = _load_attio()
    assert "headers" not in attio, (
        "Found 'headers' block in attio config — HTTP headers must be removed."
    )


def test_attio_has_no_url():
    attio = _load_attio()
    assert "url" not in attio, (
        "Found 'url' in attio config — HTTP URL must be removed."
    )
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
pytest remote-gateway/tests/test_attio_config.py -v
```

Expected: 4–5 tests FAIL (transport is `http`, no `command`/`args`/`env`, has `headers`/`oauth`/`url`). If all pass already, stop — someone already made the change.

- [ ] **Step 3: Commit the test file**

```bash
git add remote-gateway/tests/test_attio_config.py
git commit -m "test: add attio config structure validation"
```

---

### Task 2: Update `mcp_connections.json`

**Files:**
- Modify: `remote-gateway/mcp_connections.json`

- [ ] **Step 1: Replace the attio entry**

Open `remote-gateway/mcp_connections.json`. The current attio entry looks like:

```json
"attio": {
  "transport": "http",
  "url": "https://mcp.attio.com/mcp",
  "headers": {
    "Authorization": "Bearer ${ATTIO_ACCESS_TOKEN}"
  },
  "oauth": {
    "token_url": "https://app.attio.com/oidc/token",
    "client_id": "${ATTIO_CLIENT_ID}",
    "refresh_token": "${ATTIO_REFRESH_TOKEN}"
  }
}
```

Replace it with:

```json
"attio": {
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "attio-mcp"],
  "env": {
    "ATTIO_API_KEY": "${ATTIO_API_KEY}"
  }
}
```

The full file after the change:

```json
{
  "_comment": "OPTIONAL. Mature integrations the admin has chosen to centralize on the gateway. Employees whose local MCP connections for these integrations have been retired will use these gateway-proxied versions instead. Tools appear as <integration>__<tool_name>. Credentials are server-side env vars only. Start empty — add entries as integrations graduate from local R&D to org-wide shared access.",
  "connections": {
    "attio": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "attio-mcp"],
      "env": {
        "ATTIO_API_KEY": "${ATTIO_API_KEY}"
      }
    },
    "apollo": {
      "transport": "http",
      "url": "https://mcp.apollo.io/mcp",
      "headers": {
        "Authorization": "Bearer ${APOLLO_ACCESS_TOKEN}"
      },
      "oauth": {
        "token_url": "https://mcp.apollo.io/api/v1/oauth/token",
        "client_id": "${APOLLO_CLIENT_ID}",
        "refresh_token": "${APOLLO_REFRESH_TOKEN}"
      }
    }
  }
}
```

- [ ] **Step 2: Run the config tests — they should now pass**

```bash
pytest remote-gateway/tests/test_attio_config.py -v
```

Expected output:
```
PASSED test_attio_uses_stdio_transport
PASSED test_attio_command_is_npx
PASSED test_attio_args_include_attio_mcp
PASSED test_attio_env_has_api_key_reference
PASSED test_attio_has_no_oauth_block
PASSED test_attio_has_no_headers_block
PASSED test_attio_has_no_url

7 passed
```

If any test fails, fix `mcp_connections.json` until all 7 pass.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/mcp_connections.json
git commit -m "feat(attio): switch to stdio transport using attio-mcp npm package"
```

---

### Task 3: Update `nixpacks.toml` to include Node.js

Railway's Python buildpack does not include Node.js by default. `npx attio-mcp` will fail to spawn without it.

**Files:**
- Modify: `nixpacks.toml`

- [ ] **Step 1: Add the setup phase**

Current `nixpacks.toml`:

```toml
[phases.install]
cmds = ["pip install -e ."]

[start]
cmd = "MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py"
```

New `nixpacks.toml`:

```toml
[phases.setup]
nixPkgs = ["nodejs_20"]

[phases.install]
cmds = ["pip install -e ."]

[start]
cmd = "MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py"
```

- [ ] **Step 2: Verify `node` is available locally (sanity check)**

```bash
node --version
npx --version
```

Expected: both print version strings (e.g. `v20.x.x`). If not, the nixpacks change is needed for Railway even if your local machine doesn't have Node. That's fine — continue.

- [ ] **Step 3: Commit**

```bash
git add nixpacks.toml
git commit -m "chore: add nodejs_20 to nixpacks for attio-mcp stdio subprocess"
```

---

### Task 4: Update `.env.example`

**Files:**
- Modify: `remote-gateway/.env.example`

- [ ] **Step 1: Replace the Attio block**

Find the existing Attio section in `.env.example`:

```
# Attio CRM (proxied via gateway — operators need no local credentials)
# Access token auto-refreshes using the refresh token; initial value can be short-lived.
# Find these in macOS Keychain under "Claude Code-credentials" → mcpOAuth → attio.
# ATTIO_ACCESS_TOKEN=eyJ...
# ATTIO_REFRESH_TOKEN=71c8...
# ATTIO_CLIENT_ID=29df2ad6-...
```

Replace it with:

```
# Attio CRM (proxied via gateway — operators need no local credentials)
# Get from: Attio workspace settings → API Keys → Create API key (read+write scopes)
# ATTIO_API_KEY=your_api_key_here
```

- [ ] **Step 2: Commit**

```bash
git add remote-gateway/.env.example
git commit -m "docs: update .env.example for attio API key auth"
```

---

### Task 5: Local smoke test

Verify the gateway starts and Attio tools appear before deploying. Requires `ATTIO_API_KEY` in `remote-gateway/.env` and Node.js locally.

**Files:** none (read-only test)

- [ ] **Step 1: Add `ATTIO_API_KEY` to `remote-gateway/.env`**

Get an API key from Attio workspace: **Settings → API Keys → Create API key**. Grant read and write scopes.

Add to `remote-gateway/.env`:
```
ATTIO_API_KEY=your_key_here
```

Remove (or comment out) the old OAuth lines if present:
```
# ATTIO_ACCESS_TOKEN=...
# ATTIO_REFRESH_TOKEN=...
# ATTIO_CLIENT_ID=...
```

- [ ] **Step 2: Run the gateway locally in stdio mode**

```bash
python remote-gateway/core/mcp_server.py
```

Watch the startup output. Expected lines:
```
  [proxy] 'attio' connecting...
  [proxy] 'attio' connected — N tool(s) available
```

If you see `[proxy] 'attio' failed to connect`, check:
1. `ATTIO_API_KEY` is set in `.env`
2. `npx` is available (`npx --version`)
3. The `attio-mcp` package downloads without error (first run downloads from npm)

- [ ] **Step 3: Verify tools are registered**

In a separate terminal, use any MCP client to list tools from the running gateway. Confirm tools with prefix `attio__` appear (e.g. `attio__search-records`, `attio__create-record`). The exact tool names come from the `attio-mcp` package — there should be 14.

- [ ] **Step 4: Call one Attio tool to confirm end-to-end**

Via the gateway client, call:
```
attio__search-records
  resource_type: "companies"
  query: "Inform"
```

Expected: a JSON response with matching company records (or an empty result set — either confirms the auth and routing work).

---

### Task 6: Deploy to Railway

**Files:** none (deployment steps)

- [ ] **Step 1: Push the branch**

```bash
git push origin HEAD
```

- [ ] **Step 2: Update Railway environment variables**

In the Railway dashboard for the gateway service:

**Add:**
- `ATTIO_API_KEY` = your Attio API key

**Remove:**
- `ATTIO_ACCESS_TOKEN`
- `ATTIO_REFRESH_TOKEN`
- `ATTIO_CLIENT_ID`

- [ ] **Step 3: Deploy**

Trigger a Railway deploy (or it auto-deploys on push if configured). Watch the build logs to confirm nixpacks includes `nodejs_20` in the setup phase.

Watch the runtime logs for:
```
  [proxy] 'attio' connected — N tool(s) available
```

If the log instead shows a failure:
- Confirm `ATTIO_API_KEY` is set in Railway env vars
- Confirm the nixpacks build log shows Node.js being installed
- Check for npm download errors in the logs (first boot downloads `attio-mcp`)

- [ ] **Step 4: Smoke test on deployed gateway**

From the `local-workspace`, call an Attio tool through the deployed gateway to confirm end-to-end:

```
attio__search-records
  resource_type: "companies"
  query: "Inform"
```

Expected: same result as local smoke test.
