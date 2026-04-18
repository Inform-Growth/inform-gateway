# Tool Visibility Filtering & Global Toggle — Design Spec

**Date:** 2026-04-17
**Status:** Approved

---

## Problem

The gateway already blocks disabled tools at call time via the `tool_permissions` table. But clients see the full tool list in `tools/list` regardless of what they're permitted to call. There is also no runtime way to globally disable a proxied MCP tool — the only option today is editing `mcp_connections.json` and restarting the server.

This spec adds two capabilities:
1. **Per-user tool visibility** — tools disabled for a user are hidden from their `tools/list`
2. **Global tool toggle** — any tool can be turned off for all users at runtime without a restart

---

## Constraints

- No new DB table. Both features use the existing `tool_permissions` table.
- No server restart required to toggle tools.
- Filtering must be in-memory at list time — no DB query per `tools/list` call.
- Unauthenticated requests only see the global filter (no per-user filtering).
- Never block on DB failure — fail open (show all tools) rather than hiding tools due to a DB error.

---

## Data Model

### Sentinel `user_id = "*"` for Global Toggles

The existing `tool_permissions` table (`user_id, tool_name, enabled`) already handles per-user state. A new row with `user_id = "*"` represents a global disable — it applies to all users regardless of their individual permissions.

```sql
-- disable a tool globally (hides from all users + blocks all calls)
INSERT INTO tool_permissions (user_id, tool_name, enabled)
VALUES ('*', 'attio__search_records', 0)
ON CONFLICT(user_id, tool_name) DO UPDATE SET enabled = excluded.enabled;

-- re-enable it globally
UPDATE tool_permissions SET enabled = 1 WHERE user_id = '*' AND tool_name = 'attio__search_records';
```

No schema migration required. The `PRIMARY KEY (user_id, tool_name)` constraint already accommodates `"*"` as a valid `user_id`.

### In-Memory Cache

`TelemetryStore` gains a `_disabled_cache: dict[str, set[str]]` attribute:

```python
# structure: user_id → set of disabled tool names
{
    "*":        {"attio__search_records", "attio__create_record"},
    "user_abc": {"apollo__contacts_create"},
}
```

- Populated once at startup by querying all `enabled = 0` rows from `tool_permissions`
- Updated synchronously on every `set_tool_permission` write
- Never hit the DB again for list-time filtering

---

## New TelemetryStore Methods

### `load_disabled_cache() -> None`
Called once during `TelemetryStore.__init__` (after `_setup`). Reads all `enabled = 0` rows from `tool_permissions` and populates `_disabled_cache`. Silent no-op if DB is unavailable.

### `filter_visible_tools(user_id: str | None, tool_names: list[str]) -> set[str]`
Returns the subset of `tool_names` the user is allowed to see. Checks only the in-memory cache — no DB query.

```python
def filter_visible_tools(self, user_id: str | None, tool_names: list[str]) -> set[str]:
    globally_disabled = self._disabled_cache.get("*", set())
    user_disabled = self._disabled_cache.get(user_id, set()) if user_id else set()
    hidden = globally_disabled | user_disabled
    return {name for name in tool_names if name not in hidden}
```

### `set_tool_permission` (extended, no signature change)
After writing to the DB, update `_disabled_cache` in the same call so the cache stays consistent:

```python
# after the DB write:
if enabled:
    self._disabled_cache.get(user_id, set()).discard(tool_name)
else:
    self._disabled_cache.setdefault(user_id, set()).add(tool_name)
```

### `has_permission` (extended, no signature change)
Currently only checks per-user rows. Extend to also check the `"*"` sentinel via the cache, so globally disabled tools are blocked at call time for all users:

```python
def has_permission(self, user_id: str, tool_name: str) -> bool:
    # global disable takes priority
    if tool_name in self._disabled_cache.get("*", set()):
        return False
    # per-user check (existing DB query unchanged)
    ...
```

---

## Tool Listing Filter (mcp_server.py)

`_current_user` ContextVar and `_AuthMiddleware` already exist. No changes needed there.

After the existing `mcp.add_tool = _tracked_add_tool` patch, add a patch for `mcp.list_tools`:

```python
_orig_list_tools = mcp.list_tools

async def _filtered_list_tools() -> list[Any]:
    tools = await _orig_list_tools()
    user_id = _current_user.get()
    if not _telemetry._enabled:
        return tools  # fail open
    visible = _telemetry.filter_visible_tools(user_id, [t.name for t in tools])
    return [t for t in tools if t.name in visible]

mcp.list_tools = _filtered_list_tools
```

This follows the exact same monkey-patch pattern as `mcp.tool` and `mcp.add_tool`.

**Note on FastMCP internals:** If the MCP `tools/list` RPC handler does not call `mcp.list_tools()` (i.e., it calls an internal `_tool_manager` method directly), the patch target during implementation may need to be `mcp._tool_manager.list_tools` instead. The spec intent is: intercept the tool listing at the shallowest point where user context (ContextVar) is still available. Implementation should verify this at test time.

---

## Admin API

No new endpoints. The existing `PUT /api/permissions/{user_id}/{tool_name}` endpoint in `admin_api.py` already calls `set_tool_permission`. Use `user_id = "*"` to toggle globally:

```
# globally disable a proxied tool
PUT /api/permissions/*/attio__search_records?enabled=0&token=<ADMIN_TOKEN>

# re-enable it
PUT /api/permissions/*/attio__search_records?enabled=1&token=<ADMIN_TOKEN>

# view all global toggles
GET /api/permissions/*?token=<ADMIN_TOKEN>
```

Document `"*"` as a reserved sentinel in CLAUDE.md and the admin API docstrings.

---

## Call-Time Enforcement

The existing wrappers (`_tracked_mcp_tool`, `_tracked_add_tool`) call `_telemetry.has_permission(sid, tool_name)`. Since `has_permission` is extended to check the `"*"` cache entry first, globally disabled tools are blocked at call time automatically — no changes to the wrappers themselves.

---

## Files Changed

| File | Change |
|---|---|
| `remote-gateway/core/telemetry.py` | Add `_disabled_cache`, `load_disabled_cache()`, `filter_visible_tools()`; extend `set_tool_permission` and `has_permission` |
| `remote-gateway/core/mcp_server.py` | Patch `mcp.list_tools` with `_filtered_list_tools` after the existing `add_tool` patch |
| `remote-gateway/tests/test_tool_visibility.py` | New test file (see below) |
| `CLAUDE.md` | Document `"*"` sentinel in the Admin Guardrails section |

---

## Tests (`test_tool_visibility.py`)

All tests use a temp DB fixture and monkeypatching. No real gateway startup required.

| Test | What it verifies |
|---|---|
| `test_cache_loads_from_db` | `load_disabled_cache` reads all `enabled=0` rows at startup |
| `test_filter_hides_globally_disabled` | `filter_visible_tools(user_id=None, ...)` removes `"*"` disabled tools |
| `test_filter_hides_user_disabled` | `filter_visible_tools("user_abc", ...)` removes user-disabled tools |
| `test_filter_applies_both` | Global + user disables combine (union) |
| `test_filter_shows_all_when_no_disables` | No rows → full list returned |
| `test_filter_fails_open_when_disabled` | DB unavailable → full list returned |
| `test_set_permission_updates_cache` | Cache reflects write without re-querying DB |
| `test_has_permission_blocks_global` | `has_permission` returns False for `"*"`-disabled tool regardless of user |
| `test_list_tools_filtered_by_user` | Patched `mcp.list_tools` returns only visible tools for the current contextvar user |
| `test_list_tools_unauthenticated` | `user_id=None` → only global disables apply, per-user disables not applied |

---

## Behavior Summary

| Scenario | `tools/list` result | Call result |
|---|---|---|
| Tool globally enabled, user has no explicit row | Tool visible | Allowed |
| Tool globally disabled (`user_id="*"`) | Hidden for all users | Blocked for all users |
| Tool per-user disabled | Hidden for that user only | Blocked for that user only |
| Tool per-user disabled, globally enabled | Hidden for that user; visible to others | Blocked for that user; others allowed |
| DB unavailable at list time | Full list (fail open) | Per existing behavior (fail open) |
