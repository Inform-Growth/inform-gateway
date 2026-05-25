# Permissions Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Ops tab permissions panel fully functional — show all registered tools with toggle switches, searchable, and correctly persisting to the DB.

**Architecture:** The backend's `api_permissions_get` endpoint already has access to `list_tools_fn` via closure; it just needs to call it and merge the results with explicit DB rows. The frontend toggle mechanism already works end-to-end. We add a search input above the (now-long) list.

**Tech Stack:** Python/Starlette (backend), vanilla JS/D3 dashboard HTML, pytest + Starlette TestClient (tests)

---

## File Map

| File | Change |
|---|---|
| `remote-gateway/core/admin_api.py` | Modify `api_permissions_get` to merge `list_tools_fn()` with explicit DB rows |
| `remote-gateway/core/admin_dashboard.html` | Add search input + JS filter to permissions panel |
| `remote-gateway/tests/test_admin_api.py` | Update existing empty-permissions test; add merge-behavior tests |

---

### Task 1: Backend — merge all tools into permissions response

**Files:**
- Modify: `remote-gateway/core/admin_api.py` (function `api_permissions_get`, ~line 110)
- Test: `remote-gateway/tests/test_admin_api.py`

- [ ] **Step 1: Write the failing test**

Add to `remote-gateway/tests/test_admin_api.py`. The `client` fixture currently passes no `list_tools_fn`, so add a second fixture that does:

```python
class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = ""


@pytest.fixture()
def client_with_tools(store):
    async def _list_tools():
        return [_FakeTool("health_check"), _FakeTool("get_tool_stats"), _FakeTool("write_note")]

    app = create_admin_app(store, list_tools_fn=_list_tools)
    return TestClient(app, raise_server_exceptions=True), store


def test_permissions_shows_all_tools_when_no_explicit_rows(client_with_tools):
    """All tools appear with enabled=True when no explicit permissions exist."""
    c, _ = client_with_tools
    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    assert resp.status_code == 200
    perms = {p["tool_name"]: p["enabled"] for p in resp.json()["permissions"]}
    assert set(perms.keys()) == {"health_check", "get_tool_stats", "write_note"}
    assert all(v is True for v in perms.values())


def test_permissions_merges_explicit_row_with_tool_list(client_with_tools):
    """An explicit disabled row overrides the default enabled=True."""
    c, store = client_with_tools
    store.set_tool_permission("alice@example.com", "health_check", False)
    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    perms = {p["tool_name"]: p["enabled"] for p in resp.json()["permissions"]}
    assert perms["health_check"] is False
    assert perms["get_tool_stats"] is True


def test_permissions_falls_back_to_explicit_rows_when_no_list_fn(client):
    """Without list_tools_fn, only explicit rows are returned (existing behavior)."""
    c, store = client
    store.set_tool_permission("alice@example.com", "write_note", False)
    resp = c.get(f"/api/permissions/alice@example.com?token={TOKEN}")
    perms = {p["tool_name"]: p["enabled"] for p in resp.json()["permissions"]}
    assert list(perms.keys()) == ["write_note"]
```

- [ ] **Step 2: Run to verify the new tests fail**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/test_admin_api.py::test_permissions_shows_all_tools_when_no_explicit_rows \
       remote-gateway/tests/test_admin_api.py::test_permissions_merges_explicit_row_with_tool_list \
       remote-gateway/tests/test_admin_api.py::test_permissions_falls_back_to_explicit_rows_when_no_list_fn \
       -v
```

Expected: 3 FAILs (the endpoint still returns `[]` for the first two and returns explicit rows for the third — but the third may pass already if the behavior happens to match).

- [ ] **Step 3: Modify `api_permissions_get` to merge tool list**

In `remote-gateway/core/admin_api.py`, replace the `api_permissions_get` function (currently ~line 110):

```python
async def api_permissions_get(request: Request) -> Response:
    if not _is_authorized(request):
        return _forbidden()
    user_id = request.path_params["user_id"]
    explicit = {
        row["tool_name"]: row["enabled"]
        for row in telemetry.get_tool_permissions(user_id)
    }

    if list_tools_fn is not None:
        try:
            tools = await list_tools_fn()
            tool_names = sorted(t.name for t in tools)
        except Exception:
            tool_names = sorted(explicit.keys())
    else:
        tool_names = sorted(explicit.keys())

    permissions = [
        {"tool_name": name, "enabled": explicit.get(name, True)}
        for name in tool_names
    ]
    return JSONResponse({"user_id": user_id, "permissions": permissions})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/test_admin_api.py -v
```

Expected: All pass. The old `test_get_permissions_empty` test may now fail because with no `list_tools_fn` it still returns `[]` — confirm it still passes (it uses `client` which has no `list_tools_fn`, so explicit-only path returns `[]`, which is correct).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat: permissions endpoint returns all tools merged with explicit rows"
```

---

### Task 2: Frontend — search filter for permissions panel

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`
  - CSS: add `.perms-search` styles (~line 345, after `#perms-placeholder` block)
  - HTML: add `<input>` inside `#perms-content` (~line 528)
  - JS: update `renderPermissions` to track full list and filter on input (~line 1015)

- [ ] **Step 1: Add CSS for the search input**

In `admin_dashboard.html`, after the `.perm-row` rule block (~line 371), add:

```css
.perms-search {
  width: 100%;
  padding: 0.35rem 0.6rem;
  margin-bottom: 0.75rem;
  border: 1px solid var(--border);
  background: var(--cream);
  font-family: 'Arial', sans-serif;
  font-size: 0.82rem;
  color: var(--text);
  outline: none;
}
.perms-search:focus { border-color: var(--green); }
```

- [ ] **Step 2: Add the search input to the permissions panel HTML**

In `admin_dashboard.html`, the `#perms-content` div currently looks like (~line 528):

```html
<div id="perms-content" style="display:none;">
  <div id="perms-user-header"></div>
  <div id="perms-list"></div>
</div>
```

Replace with:

```html
<div id="perms-content" style="display:none;">
  <div id="perms-user-header"></div>
  <input
    type="text"
    class="perms-search"
    id="perms-search"
    placeholder="Filter tools…"
    oninput="filterPerms(this.value)"
  />
  <div id="perms-list"></div>
</div>
```

- [ ] **Step 3: Update `renderPermissions` and add `filterPerms`**

In `admin_dashboard.html`, find `function renderPermissions(userId, permissions)` (~line 1015). Replace the entire function and add `filterPerms` directly after it:

```js
let _allPerms = [];  // module-level cache, declared before renderPermissions

function renderPermissions(userId, permissions) {
  document.getElementById('perms-placeholder').style.display = 'none';
  const content = document.getElementById('perms-content');
  content.style.display = 'block';
  document.getElementById('perms-user-header').textContent = userId;
  document.getElementById('perms-search').value = '';
  _allPerms = permissions;
  _renderPermRows(permissions, userId);
}

function filterPerms(query) {
  const q = query.toLowerCase();
  const filtered = q
    ? _allPerms.filter(p => p.tool_name.toLowerCase().includes(q))
    : _allPerms;
  // Re-derive userId from the header element (avoids extra closure state).
  const userId = document.getElementById('perms-user-header').textContent;
  _renderPermRows(filtered, userId);
}

function _renderPermRows(permissions, userId) {
  const list = document.getElementById('perms-list');
  if (permissions.length === 0) {
    list.innerHTML = '<p class="muted-msg">No tools match.</p>';
    return;
  }
  list.innerHTML = permissions.map(p => {
    const checked = p.enabled ? 'checked' : '';
    const tid = 'toggle-' + escHtml(p.tool_name).replace(/[^a-z0-9]/gi, '_');
    return `<div class="perm-row">
      <span class="perm-tool-name">${escHtml(p.tool_name)}</span>
      <label class="toggle-wrap" title="${p.enabled ? 'Enabled' : 'Disabled'}">
        <input type="checkbox" id="${escHtml(tid)}" ${checked}
          onchange="setPermission('${escHtml(userId)}','${escHtml(p.tool_name)}',this.checked)" />
        <span class="toggle-slider"></span>
      </label>
    </div>`;
  }).join('');
}
```

Note: `_allPerms` must be declared at module scope (before `renderPermissions`). Find `let _selectedUser = null;` (~line 888) and add `let _allPerms = [];` on the line before it.

- [ ] **Step 4: Verify no duplicate `_allPerms` declaration**

Search the file for existing `_allPerms` occurrences. The old `renderPermissions` body had the perms list embedded inline — confirm the old `list.innerHTML = permissions.map(...)` block is fully removed and replaced by the `_renderPermRows` call.

```bash
grep -n "_allPerms\|_renderPermRows\|filterPerms" \
  remote-gateway/core/admin_dashboard.html
```

Expected: each identifier appears exactly as many times as the new code defines/uses it (no duplicates from the old code).

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: add search filter to permissions panel; render all tools"
```

---

### Task 3: End-to-end smoke test

- [ ] **Step 1: Run the full test suite**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Start the server and manually verify**

```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py
```

Open `http://localhost:8000/admin/?token=inform-admin-2026` in a browser.

Checklist:
- [ ] Ops tab → create a user → click the user row → permissions panel shows all registered tools (not "No explicit permissions set.")
- [ ] Type in the filter box → list narrows to matching tool names
- [ ] Toggle a tool to OFF → refresh the page → tool is still OFF (persisted)
- [ ] Toggle it back ON → refresh → back to ON

- [ ] **Step 3: Commit if any fixups were needed**

```bash
git add -p   # stage only intentional fixups
git commit -m "fix: permissions panel smoke-test fixups"
```
