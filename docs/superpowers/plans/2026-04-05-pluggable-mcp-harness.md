# Pluggable MCP Connection Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the gateway's HTTP proxy to use an explicit auth strategy block per connection, add per-integration tool filtering, move internal tools to a subfolder, and add Exa and GitHub as new connections.

**Architecture:** `mcp_proxy.py` gains an auth dispatcher (`resolve_auth_headers`) that reads `config["auth"]["type"]` and returns the appropriate headers — replacing hardcoded Bearer logic. Tool filtering is enforced at registration time via `_should_register_tool`. Internal tools move from `mcp_server.py` into `remote-gateway/tools/` modules, each exposing a `register(mcp)` function.

**Tech Stack:** Python 3.14, FastMCP, httpx, pytest, `@modelcontextprotocol/server-github` (npm), `attio-mcp` (npm, already configured)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `remote-gateway/tests/test_proxy_auth.py` | Create | Tests for `resolve_auth_headers` and `_should_register_tool` |
| `remote-gateway/core/mcp_proxy.py` | Modify | Auth dispatcher, tool filter, remove dead code |
| `remote-gateway/mcp_connections.json` | Modify | Apollo migrated to new schema, Exa + GitHub added |
| `remote-gateway/tools/__init__.py` | Create | Empty package marker |
| `remote-gateway/tools/notes.py` | Create | Notes tools extracted from mcp_server.py |
| `remote-gateway/tools/registry.py` | Create | Field registry tools extracted from mcp_server.py |
| `remote-gateway/tools/meta.py` | Create | health_check + get_tool_stats extracted from mcp_server.py |
| `remote-gateway/core/mcp_server.py` | Modify | Import + register from tools/, remove extracted functions |
| `remote-gateway/.env.example` | Modify | Add EXA_API_KEY |

`mcp_connections.json` and `mcp_proxy.py` must be updated together (Task 2+3 before Task 4). Tools subfolder (Tasks 5-6) is independent and can be done before or after.

---

### Task 1: Write failing tests for auth dispatcher and tool filter

**Files:**
- Create: `remote-gateway/tests/test_proxy_auth.py`

- [ ] **Step 1: Create the test file**

```python
"""
Unit tests for resolve_auth_headers and _should_register_tool.

Run with:
    pytest remote-gateway/tests/test_proxy_auth.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


def _import_proxy():
    """Import mcp_proxy without triggering server startup."""
    import importlib.util
    import types

    path = Path(__file__).parent.parent / "core" / "mcp_proxy.py"
    spec = importlib.util.spec_from_file_location("mcp_proxy", path)
    mod = types.ModuleType("mcp_proxy")
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# resolve_auth_headers
# ---------------------------------------------------------------------------


def test_resolve_auth_headers_header_type(monkeypatch):
    """auth.type='header' returns resolved header dict."""
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key-123")
    proxy = _import_proxy()
    config = {
        "auth": {
            "type": "header",
            "headers": {"x-api-key": "${EXA_API_KEY}"},
        }
    }
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {"x-api-key": "test-exa-key-123"}


def test_resolve_auth_headers_none_type():
    """auth.type='none' returns empty dict."""
    proxy = _import_proxy()
    config = {"auth": {"type": "none"}}
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {}


def test_resolve_auth_headers_missing_auth_block():
    """Missing auth block defaults to empty dict (no auth)."""
    proxy = _import_proxy()
    config = {"transport": "http", "url": "https://example.com"}
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {}


def test_resolve_auth_headers_oauth_type_opaque_token(monkeypatch):
    """auth.type='oauth' with opaque token (non-JWT) returns Bearer header without refresh."""
    monkeypatch.setenv("TEST_ACCESS_TOKEN", "opaque-token-abc")
    proxy = _import_proxy()
    config = {
        "auth": {
            "type": "oauth",
            "access_token": "${TEST_ACCESS_TOKEN}",
            "token_url": "https://example.com/token",
            "client_id": "test-client",
            "refresh_token": "test-refresh",
        }
    }
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {"Authorization": "Bearer opaque-token-abc"}


def test_resolve_auth_headers_header_multiple_headers(monkeypatch):
    """header type passes multiple headers through."""
    monkeypatch.setenv("API_KEY", "key-val")
    monkeypatch.setenv("TENANT_ID", "tenant-123")
    proxy = _import_proxy()
    config = {
        "auth": {
            "type": "header",
            "headers": {
                "x-api-key": "${API_KEY}",
                "x-tenant-id": "${TENANT_ID}",
            },
        }
    }
    result = asyncio.run(proxy.resolve_auth_headers(config))
    assert result == {"x-api-key": "key-val", "x-tenant-id": "tenant-123"}


# ---------------------------------------------------------------------------
# _should_register_tool
# ---------------------------------------------------------------------------


def test_should_register_tool_no_filter():
    """No tools config registers everything."""
    proxy = _import_proxy()
    assert proxy._should_register_tool("search_records", None) is True
    assert proxy._should_register_tool("delete_record", None) is True


def test_should_register_tool_allow_list():
    """Allow list only registers listed tools."""
    proxy = _import_proxy()
    tools_config = {"allow": ["get_file_contents", "create_or_update_file"]}
    assert proxy._should_register_tool("get_file_contents", tools_config) is True
    assert proxy._should_register_tool("create_or_update_file", tools_config) is True
    assert proxy._should_register_tool("delete_repository", tools_config) is False


def test_should_register_tool_deny_list():
    """Deny list blocks listed tools and allows everything else."""
    proxy = _import_proxy()
    tools_config = {"deny": ["delete_repository", "create_repository"]}
    assert proxy._should_register_tool("get_file_contents", tools_config) is True
    assert proxy._should_register_tool("delete_repository", tools_config) is False
    assert proxy._should_register_tool("create_repository", tools_config) is False


def test_should_register_tool_empty_allow_list():
    """Empty allow list registers nothing."""
    proxy = _import_proxy()
    tools_config = {"allow": []}
    assert proxy._should_register_tool("anything", tools_config) is False


def test_should_register_tool_empty_deny_list():
    """Empty deny list registers everything."""
    proxy = _import_proxy()
    tools_config = {"deny": []}
    assert proxy._should_register_tool("anything", tools_config) is True
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
cd /path/to/repo  # repo root
pytest remote-gateway/tests/test_proxy_auth.py -v
```

Expected: all 10 tests FAIL with `AttributeError` — `resolve_auth_headers` and `_should_register_tool` don't exist yet.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tests/test_proxy_auth.py
git commit -m "test: add failing tests for auth dispatcher and tool filter"
```

---

### Task 2: Implement auth dispatcher in `mcp_proxy.py`

**Files:**
- Modify: `remote-gateway/core/mcp_proxy.py`

This task adds `_extract_env_var_name`, `_get_oauth_token`, and `resolve_auth_headers`, then updates `_run_http_proxy` to use them. It also removes the three functions that become dead code: `_get_current_token`, `_access_token_env_var`, `_refresh_token_env_var`.

- [ ] **Step 1: Add `_extract_env_var_name` helper**

Find the comment `# OAuth token refresh helpers` in `mcp_proxy.py` (around line 100). Add this function BEFORE `_jwt_exp`:

```python
def _extract_env_var_name(ref: str) -> str | None:
    """Extract the variable name from a ``${VAR_NAME}`` reference string.

    Args:
        ref: A string like ``"${APOLLO_ACCESS_TOKEN}"``.

    Returns:
        The variable name (e.g. ``"APOLLO_ACCESS_TOKEN"``), or None if not a
        ``${...}`` reference.
    """
    if isinstance(ref, str) and ref.startswith("${") and ref.endswith("}"):
        return ref[2:-1]
    return None
```

- [ ] **Step 2: Add `_get_oauth_token` (replaces `_get_current_token`)**

Add this function after `_refresh_oauth_token` (around line 175):

```python
async def _get_oauth_token(auth: dict) -> str:
    """Return a valid Bearer token for an OAuth auth config block.

    Resolves ``${VAR}`` references in the auth block, checks expiry,
    and refreshes the token if needed.

    Args:
        auth: The ``auth`` block from a connection config (type must be ``"oauth"``).

    Returns:
        Valid access token string.
    """
    resolved = resolve_headers(auth)
    token = resolved.get("access_token", "")

    if _token_needs_refresh(token):
        refresh_config = {
            "token_url": resolved.get("token_url", ""),
            "client_id": resolved.get("client_id", ""),
            "refresh_token": resolved.get("refresh_token", ""),
            "_refresh_env_var": _extract_env_var_name(auth.get("refresh_token", "")),
        }
        print("  [proxy] OAuth token expiring soon — refreshing...")
        token = await _refresh_oauth_token(refresh_config)
        access_var = _extract_env_var_name(auth.get("access_token", ""))
        if access_var:
            os.environ[access_var] = token
        print("  [proxy] Token refreshed.")

    return token
```

- [ ] **Step 3: Add `resolve_auth_headers`**

Add this function immediately after `_get_oauth_token`:

```python
async def resolve_auth_headers(config: dict) -> dict[str, str]:
    """Resolve the auth headers for an HTTP connection based on its auth strategy.

    Dispatches on ``config["auth"]["type"]``:
    - ``"header"``: resolve and return all configured headers as-is
    - ``"oauth"``: get/refresh Bearer token, return Authorization header
    - ``"none"`` or missing: return empty dict (no auth)

    Args:
        config: Full connection config dict from mcp_connections.json.

    Returns:
        Dict of resolved HTTP headers to send with upstream requests.
    """
    auth = config.get("auth", {})
    auth_type = auth.get("type", "none")

    if auth_type == "header":
        return resolve_headers(auth.get("headers", {}))

    if auth_type == "oauth":
        token = await _get_oauth_token(auth)
        return {"Authorization": f"Bearer {token}"}

    return {}
```

- [ ] **Step 4: Update `_run_http_proxy` to use `resolve_auth_headers`**

Find the `while True:` loop inside `_run_http_proxy`. Replace the current connection block:

Old code (remove these lines):
```python
            token = await _get_current_token(config)
            auth_headers = {"Authorization": f"Bearer {token}"}
            print(f"  [proxy] '{name}' connecting with token ...{token[-8:]}")
```

New code (replace with):
```python
            auth_headers = await resolve_auth_headers(config)
            print(f"  [proxy] '{name}' connecting...")
```

- [ ] **Step 5: Update the 401 retry block in `_run_http_proxy`**

Find the 401 retry section inside the `except Exception` block. Replace:

Old code (remove):
```python
            is_auth_error = "401" in exc_text or "unauthorized" in exc_text.lower()
            if is_auth_error and config.get("oauth") and auth_retries < max_auth_retries:
                auth_retries += 1
                print(f"  [proxy] '{name}' got 401 — refreshing token (attempt {auth_retries}/{max_auth_retries})...")
                try:
                    oauth = resolve_headers(config["oauth"])
                    oauth["_refresh_env_var"] = _refresh_token_env_var(config)
                    new_token = await _refresh_oauth_token(oauth)
                    print(f"  [proxy] '{name}' got new token ...{new_token[-8:]}")
                    access_var = _access_token_env_var(config)
                    if access_var:
                        os.environ[access_var] = new_token
                    await asyncio.sleep(1)
                    continue
                except Exception as refresh_exc:  # noqa: BLE001
                    print(f"  [proxy] '{name}' token refresh failed: {refresh_exc}")
```

New code (replace with):
```python
            is_auth_error = "401" in exc_text or "unauthorized" in exc_text.lower()
            auth = config.get("auth", {})
            if is_auth_error and auth.get("type") == "oauth" and auth_retries < max_auth_retries:
                auth_retries += 1
                print(f"  [proxy] '{name}' got 401 — refreshing token (attempt {auth_retries}/{max_auth_retries})...")
                try:
                    resolved = resolve_headers(auth)
                    refresh_config = {
                        "token_url": resolved.get("token_url", ""),
                        "client_id": resolved.get("client_id", ""),
                        "refresh_token": resolved.get("refresh_token", ""),
                        "_refresh_env_var": _extract_env_var_name(auth.get("refresh_token", "")),
                    }
                    new_token = await _refresh_oauth_token(refresh_config)
                    print(f"  [proxy] '{name}' token refreshed.")
                    access_var = _extract_env_var_name(auth.get("access_token", ""))
                    if access_var:
                        os.environ[access_var] = new_token
                    await asyncio.sleep(1)
                    continue
                except Exception as refresh_exc:  # noqa: BLE001
                    print(f"  [proxy] '{name}' token refresh failed: {refresh_exc}")
```

- [ ] **Step 6: Remove dead code**

Delete these three functions entirely from `mcp_proxy.py` (they are fully replaced):
- `_get_current_token` (replaced by `_get_oauth_token` + `resolve_auth_headers`)
- `_access_token_env_var` (replaced by `_extract_env_var_name`)
- `_refresh_token_env_var` (replaced by `_extract_env_var_name`)

- [ ] **Step 7: Run the auth tests**

```bash
pytest remote-gateway/tests/test_proxy_auth.py -v -k "resolve_auth"
```

Expected: all 5 `test_resolve_auth_headers_*` tests PASS. The `_should_register_tool` tests still FAIL (implemented in Task 3).

- [ ] **Step 8: Commit**

```bash
git add remote-gateway/core/mcp_proxy.py
git commit -m "feat(proxy): add resolve_auth_headers dispatcher, remove hardcoded Bearer logic"
```

---

### Task 3: Implement tool filter in `mcp_proxy.py`

**Files:**
- Modify: `remote-gateway/core/mcp_proxy.py`

- [ ] **Step 1: Add `_should_register_tool`**

Find the comment `# Tool registration` in `mcp_proxy.py`. Add this function BEFORE `_register_proxy_tool`:

```python
def _should_register_tool(tool_name: str, tools_config: dict | None) -> bool:
    """Return True if this tool should be registered given the filter config.

    Supports two mutually exclusive filter modes:
    - ``allow``: whitelist — only listed tools are registered
    - ``deny``: blacklist — all tools except listed ones are registered
    Omitting ``tools_config`` (or passing None) registers everything.

    Args:
        tool_name: Upstream tool name to check.
        tools_config: The ``tools`` block from a connection config, or None.

    Returns:
        True if the tool should be registered on the gateway.
    """
    if not tools_config:
        return True
    if "allow" in tools_config:
        return tool_name in tools_config["allow"]
    if "deny" in tools_config:
        return tool_name not in tools_config["deny"]
    return True
```

- [ ] **Step 2: Update `_register_proxy_tool` call sites to pass tools config**

`_register_proxy_tool` is called inside both `_run_stdio_proxy` and `_run_http_proxy`. In each, find the tool registration loop:

Old (in both proxy runners):
```python
                    for tool in tools_response.tools:
                        _register_proxy_tool(mcp_server, name, tool, session)
```

New (in both proxy runners):
```python
                    tools_config = config.get("tools")
                    for tool in tools_response.tools:
                        if _should_register_tool(tool.name, tools_config):
                            _register_proxy_tool(mcp_server, name, tool, session)
```

There are two occurrences — one in `_run_stdio_proxy` and one in `_run_http_proxy`. Update both.

- [ ] **Step 3: Run all proxy auth tests**

```bash
pytest remote-gateway/tests/test_proxy_auth.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/core/mcp_proxy.py
git commit -m "feat(proxy): add tool filter support (allow/deny list per connection)"
```

---

### Task 4: Migrate `mcp_connections.json`

Update Apollo to new auth schema, add Exa and GitHub.

**Files:**
- Modify: `remote-gateway/mcp_connections.json`

- [ ] **Step 1: Write the new config**

Replace the entire contents of `remote-gateway/mcp_connections.json` with:

```json
{
  "_comment": "OPTIONAL. Mature integrations the admin has chosen to centralize on the gateway. Employees whose local MCP connections for these integrations have been retired will use these gateway-proxied versions instead. Tools appear as <integration>__<tool_name>. Credentials are server-side env vars only. Start empty — add entries as integrations graduate from local R&D to org-wide shared access.",
  "connections": {
    "exa": {
      "transport": "http",
      "url": "https://mcp.exa.ai/mcp",
      "auth": {
        "type": "header",
        "headers": {
          "x-api-key": "${EXA_API_KEY}"
        }
      }
    },
    "apollo": {
      "transport": "http",
      "url": "https://mcp.apollo.io/mcp",
      "auth": {
        "type": "oauth",
        "access_token": "${APOLLO_ACCESS_TOKEN}",
        "token_url": "https://mcp.apollo.io/api/v1/oauth/token",
        "client_id": "${APOLLO_CLIENT_ID}",
        "refresh_token": "${APOLLO_REFRESH_TOKEN}"
      }
    },
    "attio": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "attio-mcp"],
      "env": {
        "ATTIO_API_KEY": "${ATTIO_API_KEY}"
      }
    },
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      },
      "tools": {
        "allow": [
          "get_file_contents",
          "create_or_update_file",
          "list_files_in_repo",
          "search_repositories",
          "get_issue",
          "list_issues"
        ]
      }
    }
  }
}
```

- [ ] **Step 2: Update the config validation test for Apollo's new schema**

Open `remote-gateway/tests/test_attio_config.py`. Add these tests at the bottom to cover the Apollo migration and confirm the file structure is valid:

```python
# ---------------------------------------------------------------------------
# Apollo migration validation
# ---------------------------------------------------------------------------


def _load_apollo() -> dict:
    """Load and return the apollo connection entry from mcp_connections.json."""
    if not CONNECTIONS_FILE.exists():
        pytest.fail(f"Config file not found: {CONNECTIONS_FILE}")
    data = json.loads(CONNECTIONS_FILE.read_text())
    if "apollo" not in data.get("connections", {}):
        pytest.fail("No 'apollo' entry found in connections")
    return data["connections"]["apollo"]


def test_apollo_uses_http_transport():
    apollo = _load_apollo()
    assert apollo.get("transport") == "http"


def test_apollo_auth_type_is_oauth():
    apollo = _load_apollo()
    assert apollo.get("auth", {}).get("type") == "oauth", (
        "Apollo auth.type must be 'oauth'"
    )


def test_apollo_auth_has_access_token():
    apollo = _load_apollo()
    assert apollo.get("auth", {}).get("access_token") == "${APOLLO_ACCESS_TOKEN}"


def test_apollo_has_no_top_level_headers():
    apollo = _load_apollo()
    assert "headers" not in apollo, (
        "Apollo must not have a top-level 'headers' key — auth moved to auth block"
    )


def test_apollo_has_no_top_level_oauth():
    apollo = _load_apollo()
    assert "oauth" not in apollo, (
        "Apollo must not have a top-level 'oauth' key — auth moved to auth block"
    )
```

- [ ] **Step 3: Run all config tests**

```bash
pytest remote-gateway/tests/test_attio_config.py -v
```

Expected: all existing 8 attio tests PASS, all 5 new apollo tests PASS. 13 passed total.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/mcp_connections.json remote-gateway/tests/test_attio_config.py
git commit -m "feat(connections): migrate Apollo to auth block schema, add Exa and GitHub"
```

---

### Task 5: Create `remote-gateway/tools/` subfolder

Extract the three tool groups from `mcp_server.py` into focused modules. Each module exposes a `register(mcp)` function that `mcp_server.py` calls after patching `mcp.tool`.

**Files:**
- Create: `remote-gateway/tools/__init__.py`
- Create: `remote-gateway/tools/notes.py`
- Create: `remote-gateway/tools/registry.py`
- Create: `remote-gateway/tools/meta.py`
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 1: Create `remote-gateway/tools/__init__.py`**

```python
"""Internal gateway tools — notes, field registry, and meta."""
```

- [ ] **Step 2: Create `remote-gateway/tools/notes.py`**

```python
"""
GitHub-backed markdown notes tools.

Reads and writes .md files in a GitHub repository, providing a
persistent notes store that survives gateway redeployments.

Required env vars:
    GITHUB_TOKEN  — fine-grained PAT with Contents read+write on the repo
    GITHUB_REPO   — owner/repo slug, e.g. "acme/inform-notes"
    GITHUB_BRANCH — branch to read/write (default: "main")
    NOTES_PATH    — folder inside GITHUB_REPO (default: "notes")
"""
from __future__ import annotations

import base64
import os
from typing import Any


def _github_headers() -> dict[str, str]:
    """Return GitHub API request headers using GITHUB_TOKEN from env."""
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_file_url(path: str) -> str:
    """Return the GitHub Contents API URL for a file path."""
    repo = os.environ.get("GITHUB_REPO", "")
    return f"https://api.github.com/repos/{repo}/contents/{path}"


def _notes_path(filename: str) -> str:
    """Resolve a filename to its full repo path under the notes folder."""
    notes_base = os.environ.get("NOTES_PATH", "notes")
    safe = os.path.basename(filename)
    if not safe.endswith(".md"):
        safe = safe + ".md"
    return f"{notes_base}/{safe}"


def list_notes() -> dict:
    """List all markdown notes stored in the gateway's notes folder.

    Notes are stored in the GitHub repository and persist across redeployments.

    Returns:
        Dict with 'notes' list of filenames and their last-commit message.
    """
    import httpx

    notes_base = os.environ.get("NOTES_PATH", "notes")
    repo = os.environ.get("GITHUB_REPO", "")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    url = _github_file_url(notes_base)

    with httpx.Client() as client:
        resp = client.get(url, headers=_github_headers(), params={"ref": branch})

    if resp.status_code == 404:
        return {"notes": [], "message": "No notes found — notes folder does not exist yet."}

    resp.raise_for_status()
    entries = resp.json()
    notes = [
        {"name": e["name"], "path": e["path"], "sha": e["sha"]}
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".md")
    ]
    return {"notes": notes, "count": len(notes), "repo": repo, "branch": branch}


def read_note(filename: str) -> dict:
    """Read a markdown note from the gateway's notes folder.

    Args:
        filename: Note filename, with or without .md extension (e.g. "onboarding").

    Returns:
        Dict with 'filename', 'content' (decoded markdown text), and 'sha'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _notes_path(filename)
    url = _github_file_url(path)

    with httpx.Client() as client:
        resp = client.get(url, headers=_github_headers(), params={"ref": branch})

    if resp.status_code == 404:
        return {"status": "not_found", "filename": os.path.basename(path)}

    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return {
        "filename": data["name"],
        "path": data["path"],
        "content": content,
        "sha": data["sha"],
    }


def write_note(filename: str, content: str, commit_message: str = "") -> dict:
    """Create or update a markdown note in the gateway's notes folder.

    The note is committed directly to the repository and persists across redeployments.
    To update an existing note you do not need the SHA — it is fetched automatically.

    Args:
        filename: Note filename, with or without .md extension (e.g. "onboarding").
        content: Full markdown content to write.
        commit_message: Optional git commit message. Defaults to "chore: update <filename>".

    Returns:
        Dict confirming the commit with 'sha', 'filename', and 'commit_url'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _notes_path(filename)
    url = _github_file_url(path)
    base_name = os.path.basename(path)
    message = commit_message or f"chore: update {base_name}"

    sha: str | None = None
    with httpx.Client() as client:
        check = client.get(url, headers=_github_headers(), params={"ref": branch})
        if check.status_code == 200:
            sha = check.json()["sha"]

        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        resp = client.put(url, headers=_github_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    commit = result.get("commit", {})
    return {
        "status": "ok",
        "filename": base_name,
        "path": path,
        "sha": commit.get("sha", ""),
        "commit_url": commit.get("html_url", ""),
        "action": "updated" if sha else "created",
    }


def delete_note(filename: str, commit_message: str = "") -> dict:
    """Delete a markdown note from the gateway's notes folder.

    Args:
        filename: Note filename, with or without .md extension.
        commit_message: Optional git commit message. Defaults to "chore: delete <filename>".

    Returns:
        Dict confirming deletion with 'filename' and 'commit_url'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _notes_path(filename)
    url = _github_file_url(path)
    base_name = os.path.basename(path)

    with httpx.Client() as client:
        check = client.get(url, headers=_github_headers(), params={"ref": branch})
        if check.status_code == 404:
            return {"status": "not_found", "filename": base_name}
        check.raise_for_status()
        sha = check.json()["sha"]

        body = {
            "message": commit_message or f"chore: delete {base_name}",
            "sha": sha,
            "branch": branch,
        }
        resp = client.request("DELETE", url, headers=_github_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    commit = result.get("commit", {})
    return {
        "status": "deleted",
        "filename": base_name,
        "commit_url": commit.get("html_url", ""),
    }


def register(mcp: Any) -> None:
    """Register all notes tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
    """
    mcp.tool()(list_notes)
    mcp.tool()(read_note)
    mcp.tool()(write_note)
    mcp.tool()(delete_note)
```

- [ ] **Step 3: Create `remote-gateway/tools/registry.py`**

```python
"""
Field registry tools — lookup, drift detection, and discovery.

These tools expose the gateway's field registry to connected agents,
allowing them to look up field definitions, detect schema drift, and
generate definitions for new integrations.
"""
from __future__ import annotations

from typing import Any


def _infer_type(key: str, value: Any) -> str:
    """Infer a semantic field type from key name and value."""
    if value is None:
        return "unknown"

    key_lower = key.lower()

    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        if any(k in key_lower for k in ("amount", "price", "revenue", "mrr", "arr", "value")):
            return "currency_usd"
        if any(k in key_lower for k in ("rate", "percent", "ratio", "pct")):
            return "percentage"
        return "number"
    if isinstance(value, str):
        if any(k in key_lower for k in ("_at", "_date", "timestamp", "created", "updated")):
            return "timestamp"
        if any(k in key_lower for k in ("_id", "uuid", "key")):
            return "id"
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"

    return "unknown"


def make_list_field_integrations(registry: Any):
    """Return a list_field_integrations tool function bound to the given registry."""

    def list_field_integrations() -> dict:
        """List all integrations that have field definitions in the registry.

        Returns:
            Dict with 'integrations' key containing a sorted list of slugs.
        """
        return {"integrations": registry.list_integrations()}

    return list_field_integrations


def make_lookup_field(registry: Any):
    """Return a lookup_field tool function bound to the given registry."""

    def lookup_field(integration: str, field_name: str) -> dict:
        """Return the business context definition for a specific field.

        Use this when a tool returns a field whose meaning is unclear. The
        registry maps technical field names to business definitions, types,
        and any calculation notes.

        Args:
            integration: Integration slug (e.g., "stripe", "hubspot").
            field_name: Exact field key as returned by the integration.

        Returns:
            Field definition dict, or a 'not_found' status if undefined.
        """
        definition = registry.lookup(integration, field_name)
        if definition is None:
            return {
                "status": "not_found",
                "integration": integration,
                "field": field_name,
                "message": (
                    f"'{field_name}' is not in the registry for '{integration}'. "
                    "Run discover_fields() to generate definitions for new integrations."
                ),
            }
        return {"integration": integration, "field": field_name, "definition": definition}

    return lookup_field


def make_get_field_definitions(registry: Any):
    """Return a get_field_definitions tool function bound to the given registry."""

    def get_field_definitions(integration: str) -> dict:
        """Return all field definitions for an integration.

        Args:
            integration: Integration slug (e.g., "stripe", "hubspot").

        Returns:
            Dict with 'integration' and 'fields' keys, or empty fields if unknown.
        """
        return {"integration": integration, "fields": registry.get_all(integration)}

    return get_field_definitions


def make_check_field_drift(registry: Any):
    """Return a check_field_drift tool function bound to the given registry."""

    def check_field_drift(integration: str, fresh_sample: dict[str, Any]) -> dict:
        """Compare a current API/MCP response against the stored field definitions.

        Run this periodically or when you suspect an integration has changed its
        schema. Returns a diff of new, removed, and unchanged fields.

        Args:
            integration: Integration slug (e.g., "stripe").
            fresh_sample: A current response dict from the integration to compare.

        Returns:
            Drift report with new_fields, removed_fields, unchanged_fields, and
            has_drift flag.
        """
        result = registry.check_drift(integration, fresh_sample)
        return {
            "integration": integration,
            "has_drift": result.has_drift,
            "new_fields": result.new_fields,
            "removed_fields": result.removed_fields,
            "unchanged_fields": result.unchanged_fields,
            "summary": result.summary(),
        }

    return check_field_drift


def make_discover_fields(registry: Any):
    """Return a discover_fields tool function bound to the given registry."""

    def discover_fields(integration: str, sample_response: dict[str, Any]) -> dict:
        """Generate field definitions for a new integration from a sample response.

        Call this when adding a new MCP or API integration. Pass in a real
        response sample; the tool creates a YAML entry for each field, using
        field names and values to infer types. Business descriptions are left
        as placeholders — an admin or AI agent should enrich them after discovery.

        Existing field definitions are never overwritten; only new fields are added.

        Args:
            integration: Integration slug for the new source (e.g., "hubspot").
            sample_response: A representative response dict from the integration.

        Returns:
            Dict with the fields that were discovered and written to the registry.
        """
        discovered: dict[str, Any] = {}

        for key, value in sample_response.items():
            if registry.lookup(integration, key) is not None:
                continue

            inferred_type = _infer_type(key, value)
            discovered[key] = {
                "display_name": key.replace("_", " ").title(),
                "description": f"TODO: Add business description for '{key}'.",
                "type": inferred_type,
                "notes": "",
                "nullable": value is None,
            }

        if discovered:
            registry.upsert(integration, {"integration": integration, "fields": discovered})

        return {
            "integration": integration,
            "discovered_count": len(discovered),
            "fields": list(discovered.keys()),
            "message": (
                f"Discovered {len(discovered)} new field(s) for '{integration}'. "
                "Update 'description' and 'notes' in "
                f"remote-gateway/context/fields/{integration}.yaml."
            )
            if discovered
            else f"No new fields found — '{integration}' registry is up to date.",
        }

    return discover_fields


def register(mcp: Any, registry: Any) -> None:
    """Register all field registry tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
        registry: The FieldRegistry instance from field_registry.py.
    """
    mcp.tool()(make_list_field_integrations(registry))
    mcp.tool()(make_lookup_field(registry))
    mcp.tool()(make_get_field_definitions(registry))
    mcp.tool()(make_check_field_drift(registry))
    mcp.tool()(make_discover_fields(registry))
```

- [ ] **Step 4: Create `remote-gateway/tools/meta.py`**

```python
"""
Gateway meta tools — health check and telemetry stats.
"""
from __future__ import annotations

from typing import Any


def make_health_check(server_name_fn: Any):
    """Return a health_check tool function that reads server name at call time.

    Args:
        server_name_fn: Zero-arg callable returning the server's display name.
    """

    def health_check() -> dict:
        """Check that the Gateway MCP server is running and responsive.

        Returns:
            A dict with status and server name.
        """
        return {"status": "ok", "server": server_name_fn()}

    return health_check


def make_get_tool_stats(telemetry: Any):
    """Return a get_tool_stats tool function bound to the given telemetry instance."""

    def get_tool_stats(tool_name: str = "") -> dict:
        """Return call statistics for all gateway tools.

        Use this to monitor tool health: identify tools with high error rates
        (possible API degradation), tools that have never been called (stale
        candidates for deprecation), and overall call volume.

        Stats reset if the gateway is redeployed without a persistent volume.
        For persistent history on Railway or Render, set TELEMETRY_DB_PATH to a
        path on a mounted volume (e.g., /data/telemetry.db).

        Args:
            tool_name: Filter to a specific tool by name, or leave empty for all.

        Returns:
            Dict with 'tools' list and 'summary'. Each tool entry includes
            call_count, error_count, error_rate, last_called, avg_duration_ms,
            and max_duration_ms. summary.high_error_rate lists tools with
            ≥5% error rate over ≥10 calls.
        """
        return telemetry.stats(tool_name or None)

    return get_tool_stats


def register(mcp: Any, server_name_fn: Any, telemetry: Any) -> None:
    """Register meta tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
        server_name_fn: Zero-arg callable returning the server's display name.
        telemetry: The Telemetry instance from telemetry.py.
    """
    mcp.tool()(make_health_check(server_name_fn))
    mcp.tool()(make_get_tool_stats(telemetry))
```

- [ ] **Step 5: Update `mcp_server.py` to use the tools modules**

In `mcp_server.py`, after the `mcp.tool = _tracked_mcp_tool` line (around line 97), add these imports and registration calls. Also remove the extracted function definitions.

Add after `mcp.tool = _tracked_mcp_tool`:

```python
# ---------------------------------------------------------------------------
# Register internal tools from tools/ modules
# (imported here so .env is loaded and mcp.tool telemetry patch is active)
# ---------------------------------------------------------------------------

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import meta as _meta_tools  # noqa: E402
from tools import notes as _notes_tools  # noqa: E402
from tools import registry as _registry_tools  # noqa: E402

_meta_tools.register(mcp, lambda: mcp.name, _telemetry)
_notes_tools.register(mcp)
_registry_tools.register(mcp, registry)
```

Then delete from `mcp_server.py`:
- The `health_check` function and its `@mcp.tool()` decorator
- The `get_tool_stats` function and its `@mcp.tool()` decorator
- The `list_field_integrations` function and its `@mcp.tool()` decorator
- The `lookup_field` function and its `@mcp.tool()` decorator
- The `get_field_definitions` function and its `@mcp.tool()` decorator
- The `check_field_drift` function and its `@mcp.tool()` decorator
- The `discover_fields` function and its `@mcp.tool()` decorator
- The `list_notes` function and its `@mcp.tool()` decorator
- The `read_note` function and its `@mcp.tool()` decorator
- The `write_note` function and its `@mcp.tool()` decorator
- The `delete_note` function and its `@mcp.tool()` decorator
- The helper functions `_github_headers`, `_github_file_url`, `_notes_path`
- The `_NOTES_BASE` module-level variable
- The `_infer_type` helper (moved to `tools/registry.py`)
- The top-level `import base64` (no longer needed in mcp_server.py)

Keep in `mcp_server.py`:
- The `.env` loading block
- All imports still needed (`asyncio`, `functools`, `os`, `time`, `httpx`, `Path`, `FastMCP`, `registry`, `mount_all_proxies`, `telemetry`)
- The `lifespan` function
- The `mcp` instance creation
- The telemetry patch (`_tracked_mcp_tool`)
- The `validated` helper
- The promoted tools section comment
- The `if __name__ == "__main__"` block

- [ ] **Step 6: Run the gateway to verify tools still work**

```bash
python remote-gateway/core/mcp_server.py
```

Expected startup output includes all the same tools as before. If you see `ImportError` or `AttributeError`, check that:
1. The `tools/` folder is in the Python path (the `_sys.path.insert` call handles this)
2. The `register` function signatures match what `mcp_server.py` is calling

- [ ] **Step 7: Run existing notes tests**

```bash
GITHUB_TOKEN=<token> GITHUB_REPO=<repo> python remote-gateway/tests/test_notes.py
```

Expected: all assertions pass (same behavior as before the refactor).

- [ ] **Step 8: Commit**

```bash
git add remote-gateway/tools/ remote-gateway/core/mcp_server.py
git commit -m "refactor: move internal tools to remote-gateway/tools/ subfolder"
```

---

### Task 6: Update `.env.example` and run ruff

**Files:**
- Modify: `remote-gateway/.env.example`

- [ ] **Step 1: Add EXA_API_KEY to `.env.example`**

Find the `# Data Source API Keys` section. Add above it:

```
# Exa (web search, proxied via gateway)
# Get from: exa.ai → Dashboard → API Keys
# EXA_API_KEY=your_api_key_here
```

- [ ] **Step 2: Run ruff across changed files**

```bash
ruff check remote-gateway/core/mcp_proxy.py remote-gateway/tools/ remote-gateway/core/mcp_server.py
```

Fix any issues reported. Common fixes: unused imports, line length. Re-run until clean.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/.env.example remote-gateway/core/mcp_proxy.py remote-gateway/tools/ remote-gateway/core/mcp_server.py
git commit -m "docs: add EXA_API_KEY to .env.example; fix ruff issues"
```

---

### Task 7: Smoke test all connections

No code changes. Verify the gateway starts correctly with all integrations.

- [ ] **Step 1: Set env vars in `remote-gateway/.env`**

Ensure these are set (in addition to existing vars):
```
EXA_API_KEY=your_exa_api_key
GITHUB_TOKEN=<already set for notes tools>
```

- [ ] **Step 2: Start the gateway**

```bash
python remote-gateway/core/mcp_server.py
```

Expected startup log (order may vary):
```
  [proxy] 'exa' connecting...
  [proxy] 'exa' connected — N tool(s) available
  [proxy] 'apollo' connecting...
  [proxy] 'apollo' connected — N tool(s) available
  [proxy] 'attio' connecting...
  [proxy] 'attio' connected — 36 tool(s) available
  [proxy] 'github' connecting...
  [proxy] 'github' connected — 6 tool(s) available
```

GitHub should show exactly 6 tools (matching the allow list). If it shows more, the tool filter isn't working.

- [ ] **Step 3: Test Exa**

Call `exa__web_search_exa` with query `"Inform Growth CRM"`. Expected: JSON results with web search hits.

- [ ] **Step 4: Test GitHub**

Call `github__get_file_contents` with `owner=Inform-Growth`, `repo=inform-notes`, `path=notes`. Expected: file listing or contents.

- [ ] **Step 5: Verify Apollo still works**

Call `apollo__apollo_users_api_profile`. Expected: Jaron Sander's profile (same as before).

- [ ] **Step 6: Push and deploy to Railway**

```bash
git checkout main
git merge operator/jaron
git push origin main
git checkout operator/jaron
```

In Railway dashboard: add `EXA_API_KEY`. `GITHUB_TOKEN` is already set.
