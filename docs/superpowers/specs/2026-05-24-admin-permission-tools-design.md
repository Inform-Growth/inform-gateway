# Admin-Gated Permission-Management MCP Tools

**Status:** Approved (2026-05-24)
**Closes:** #29 (the actual feature). Also resolves #25 (manual playbook) and the access-grant half of #27.
**Splits out:** Cost-metadata for Apollo/Wiza/Exa (#27 second half) and permission-sets / custom roles (future work) — both filed as new issues at PR time.

## Problem

The Gateway's HTTP admin API and the `tool_permissions` / `skill_permissions` tables already support per-user, per-tool access grants at the granularity callers need (e.g., `apollo__enrich_organization`, not the whole Apollo integration). What's missing is a programmatic MCP surface: an admin operator running a bootstrap session (Marketing trio, Lead Researcher, Signal Scout, etc.) cannot list users, grant tool permissions, or grant skill permissions without leaving the session to hand-edit the admin UI / DB.

Concretely from issue #29 and the #25 manual playbook: spinning up six agents required 6 `create_user` calls + ~60 admin-UI clicks for tool/skill allowlists. The gateway's whole reason to exist is to remove this kind of multi-step ceremony.

A second concern — escalation — is solved by the same surface: today `create_user` is "Admin only" in the docstring but has zero code-level enforcement. We add real admin gating in this work.

## Goals

1. Three admin-gated MCP tools cover the full bootstrap path with no admin-UI step: `list_users`, `set_tool_permission` (bulk), `set_skill_permission` (bulk).
2. A fourth tool `set_user_role` manages the admin gate itself, with the same UI surface available to admins.
3. `create_user` and the four new tools all require the caller to have `role='admin'` — enforced in code, not docstring.
4. Bulk-by-design: bootstrapping a user with 14 tools is one MCP call, not 14.
5. Existing HTTP routes (used by the React admin UI) stay intact; one new route added for the role toggle.
6. The role column is open-vocab-ready: today only `'user'` and `'admin'` are accepted, but the column and helper API don't need to be renamed when custom roles ship.

## Non-Goals

- Permission sets / role → permission-set mapping. Filed as a separate issue at PR time; this work lays the groundwork (the `role` column) but adds no lookup table.
- Surfacing per-call API credit costs for Apollo/Wiza/Exa (the second half of #27). Separate issue.
- Changing the existing singular HTTP routes for tool/skill permissions (the React admin UI's click-toggle UX is correct as-is).
- Backfilling admin enforcement on routes that aren't part of this feature (e.g., the existing global toggle `PUT /api/permissions/*/<tool>` keeps its current trust-the-key model until we explicitly revisit).

## Architecture

Three layers, each does one job. No new abstractions introduced.

```
┌───────────────────────────────────────────────────────────────┐
│  MCP tool layer  (new: tools/admin.py)                        │
│  list_users, set_tool_permission, set_skill_permission,       │
│  set_user_role, create_user (retrofitted)                     │
│  Each calls _require_admin(ctx) before touching telemetry.    │
└──────────┬────────────────────────────────────────────────────┘
           │
┌──────────▼────────────────────────────────────────────────────┐
│  Storage layer  (telemetry.py)                                │
│  api_keys.role (new column), get_role, is_admin,              │
│  set_user_role, bootstrap_admin_roles, list_users (updated)   │
└──────────┬────────────────────────────────────────────────────┘
           │
┌──────────▼────────────────────────────────────────────────────┐
│  HTTP admin layer  (admin_api.py + admin-ui/)                 │
│  New: PUT /api/users/{user_id}/role                           │
│  UI: role-select cell on the users table                      │
└───────────────────────────────────────────────────────────────┘
```

Bootstrap path: a new env var `BOOTSTRAP_ADMIN_USER_IDS` (comma-separated user_ids) is read once on startup and flips `role` to `'admin'` for matching `api_keys` rows. Idempotent, never demotes, unknown user_ids logged-and-skipped.

## Components

### Storage layer — `remote-gateway/core/telemetry.py`

Schema additions:

```python
ROLE_USER = "user"
ROLE_ADMIN = "admin"
VALID_ROLES = frozenset({ROLE_USER, ROLE_ADMIN})
```

Schema additions land via an idempotent `ALTER` appended to `_SCHEMA_STATEMENTS` (which already runs every startup):

```sql
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'
```

This both seeds the column on new deployments and backfills `'user'` on every existing row in deployed gateways — no separate migration script needed.

New helpers on the `Telemetry` class:

```python
def get_role(self, user_id: str) -> str | None:
    """Return the role of the user, or None if user_id has no api_keys row."""

def is_admin(self, user_id: str) -> bool:
    """Single chokepoint — get_role(user_id) == ROLE_ADMIN.
    Future role lookups can swap this implementation without touching call sites."""

def set_user_role(self, user_id: str, role: str) -> None:
    """Validate role ∈ VALID_ROLES; UPDATE api_keys SET role = %s WHERE user_id = %s.
    Raises ValueError on invalid role. No-op (zero rows) if user_id has no key."""

def bootstrap_admin_roles(self, user_ids: list[str]) -> dict:
    """Promote each listed user_id to ROLE_ADMIN if a matching api_keys row exists.
    Never demotes. Returns {'promoted': [...], 'skipped_unknown': [...]} for logging."""
```

Updated:

```python
def list_users(self) -> list[dict]:
    # SELECT user_id, role, MIN(created_at) AS created_at FROM api_keys GROUP BY user_id, role
    # returns: [{"user_id": ..., "role": ..., "created_at": ...}, ...]
```

Note on grouping: `api_keys` is keyed by `key`, so a user with two keys has two rows. We enforce a per-user-id role invariant on both write paths:

- `set_user_role` updates `WHERE user_id = %s` (not by key), so all of a user's rows move to the new role atomically.
- `add_api_key` is amended to inherit the existing role when a row for that user_id already exists: `COALESCE((SELECT role FROM api_keys WHERE user_id = %s LIMIT 1), 'user')`. New users default to `'user'` via the column default; second-key issuance for an existing admin keeps them admin.

With those two invariants `list_users` can safely `GROUP BY user_id, role` with no ambiguity.

### MCP server — `remote-gateway/core/mcp_server.py`

New helper:

```python
def _require_admin() -> str:
    """Resolve the calling user_id via the existing _AuthMiddleware ctx-var.
    Raises PermissionError('admin role required') if no caller is resolved
    or telemetry.is_admin(caller) is False. Returns the caller's user_id."""
```

Startup additions:

```python
# After telemetry init, before mcp.run():
admin_ids_raw = os.environ.get("BOOTSTRAP_ADMIN_USER_IDS", "")
if admin_ids_raw.strip():
    user_ids = [s.strip() for s in admin_ids_raw.split(",") if s.strip()]
    result = telemetry.bootstrap_admin_roles(user_ids)
    print(
        f"[admin-bootstrap] promoted {len(result['promoted'])} users, "
        f"skipped {len(result['skipped_unknown'])} unknown: "
        f"promoted={result['promoted']} skipped={result['skipped_unknown']}",
        flush=True,
    )
```

### MCP tools — `remote-gateway/tools/admin.py` (new)

```python
def make_list_users(telemetry):
    def list_users() -> dict:
        """List all users on the gateway with their role. Admin only.

        Returns:
            Dict with 'users': list of {user_id, role, created_at}.
        """
        _require_admin()
        return {"users": telemetry.list_users()}
    return list_users


def make_set_user_role(telemetry):
    def set_user_role(user_id: str, role: str) -> dict:
        """Set a user's role. Admin only.

        Args:
            user_id: The user whose role to update.
            role: 'user' or 'admin'.

        Returns:
            Dict with user_id and role.
        """
        _require_admin()
        telemetry.set_user_role(user_id, role)
        return {"user_id": user_id, "role": role}
    return set_user_role


def make_set_tool_permission(telemetry):
    def set_tool_permission(
        user_id: str, permissions: list[dict],
    ) -> dict:
        """Grant or revoke tool-level access for a user (bulk). Admin only.

        Args:
            user_id: The user whose tool allowlist to modify.
            permissions: List of {"tool_name": str, "enabled": bool}.
                tool_name uses the gateway-exposed name (e.g.
                "apollo__enrich_organization"). enabled=False denies.

        Returns:
            Dict with user_id and 'applied' count.
        """
        _require_admin()
        applied = 0
        for entry in permissions:
            telemetry.set_tool_permission(
                user_id, entry["tool_name"], bool(entry["enabled"])
            )
            applied += 1
        return {"user_id": user_id, "applied": applied}
    return set_tool_permission


def make_set_skill_permission(telemetry):
    def set_skill_permission(
        user_id: str, permissions: list[dict],
    ) -> dict:
        """Grant or revoke skill-level access for a user (bulk). Admin only.

        Args:
            user_id: The user whose skill allowlist to modify.
            permissions: List of {"skill_name": str, "enabled": bool}.

        Returns:
            Dict with user_id and 'applied' count.
        """
        _require_admin()
        applied = 0
        for entry in permissions:
            telemetry.set_skill_permission(
                user_id, entry["skill_name"], bool(entry["enabled"])
            )
            applied += 1
        return {"user_id": user_id, "applied": applied}
    return set_skill_permission


def register(mcp, telemetry):
    mcp.tool()(make_list_users(telemetry))
    mcp.tool()(make_set_user_role(telemetry))
    mcp.tool()(make_set_tool_permission(telemetry))
    mcp.tool()(make_set_skill_permission(telemetry))
```

### `create_user` retrofit — `remote-gateway/tools/meta.py`

Add `_require_admin()` as the first line of the `create_user` closure body. No other change. Existing callers must hold an admin key from the bootstrap env var.

### Init-gate allowlist — `INTENT_NEVER_REQUIRED`

Add: `list_users`, `set_tool_permission`, `set_skill_permission`, `set_user_role`. Rationale: an admin bootstrapping a new agent shouldn't have to `declare_intent` first just to provision; consistent with `create_user` already being in the allowlist.

### HTTP admin layer — `remote-gateway/core/admin_api.py`

New route:

```python
async def api_user_role_set(request: Request) -> Response:
    user_id = request.path_params["user_id"]
    body = await request.json()
    role = body.get("role")
    if role not in VALID_ROLES:
        return JSONResponse({"error": "invalid role"}, status_code=400)
    telemetry.set_user_role(user_id, role)
    return JSONResponse({"ok": True, "user_id": user_id, "role": role})

# Routes list:
Route("/api/users/{user_id}/role", api_user_role_set, methods=["PUT"]),
```

`api_users_list` already returns whatever `telemetry.list_users()` produces; once that returns `role`, the route does too — no change needed in the route itself.

### Admin UI — `remote-gateway/admin-ui/`

On the users table, replace the read-only role text with a select dropdown (User / Admin). On change, PUT `/api/users/{user_id}/role` with the new role; optimistic UI update with revert-on-error toast. Disable the dropdown for the currently authenticated admin (no self-demotion lock-out).

### Documentation — `CLAUDE.md` and `remote-gateway/CLAUDE.md`

- Add `BOOTSTRAP_ADMIN_USER_IDS` to the env var table.
- Document the four new tools alongside `create_user` in the built-in tools table.
- Note the role column on `api_keys`.

## Data Flows

### Admin bootstraps a new agent (the original friction)

```
1. create_user(user_id="signal_scout")
   → _require_admin OK → telemetry.add_api_key → {key: "sk-…"}
2. set_tool_permission(user_id="signal_scout", permissions=[
       {"tool_name": "exa__web_search_exa", "enabled": True},
       {"tool_name": "ingest_signal", "enabled": True},
       …12 more…
   ])
   → _require_admin OK → 14 upserts → {"applied": 14}
3. set_skill_permission(user_id="signal_scout", permissions=[
       {"skill_name": "role_signal_scout", "enabled": True},
       {"skill_name": "brief_signal_scout_daily_pull", "enabled": True},
   ])
   → {"applied": 2}
```

Before: 1 MCP call + ~16 admin-UI clicks. After: 3 MCP calls, fully scriptable.

### Admin promotes a user via the UI

```
1. Admin clicks the role dropdown for user_id="content_writer", picks Admin.
2. UI fires PUT /api/users/content_writer/role  {"role": "admin"}.
3. Route validates role ∈ {'user','admin'}, calls telemetry.set_user_role.
4. UI optimistically updates the cell; on error, reverts + toast.
```

### Startup bootstrap on existing deployments

```
1. Deploy with BOOTSTRAP_ADMIN_USER_IDS="jaron@informgrowth.com,Jaron Desktop".
2. mcp_server.py startup calls telemetry.bootstrap_admin_roles([...]).
3. Existing api_keys rows for those user_ids get role='admin'.
4. Container log: "[admin-bootstrap] promoted 2 users, skipped 0 unknown: promoted=['jaron@informgrowth.com','Jaron Desktop'] skipped_unknown=[]"
```

## Error Handling

| Surface | Condition | Result |
|---|---|---|
| Any of 4 new MCP tools + `create_user` | caller not resolved / role != admin | `PermissionError("admin role required")` |
| `set_user_role` (MCP or HTTP) | role ∉ {'user','admin'} | `ValueError` (MCP) / HTTP 400 |
| `set_tool_permission` / `set_skill_permission` | empty `permissions` list | `{"applied": 0}` (not an error) |
| `set_user_role` | user_id has no `api_keys` row | UPDATE affects zero rows; returns the requested role but the user has no effective access (no key) — same semantics as the existing `DELETE /api/users/{user_id}` flow |
| Unauth'd HTTP caller | no admin token on the admin API | existing `_AuthMiddleware` path returns 401 — nothing new |

## Testing

| File | Scope |
|---|---|
| `test_telemetry_roles.py` (NEW) | Schema: `role` column exists with default `'user'` after fresh init. ALTER is idempotent across reinitializations. `get_role`/`is_admin`/`set_user_role` round-trip. Invalid role rejected. `bootstrap_admin_roles` promotes known user_ids, skips unknown, never demotes. `set_user_role` updates ALL rows for a user_id (multi-key case). `add_api_key` for an existing admin user_id inherits the `'admin'` role. `list_users` returns `role`. |
| `test_admin_api.py` (extend) | `PUT /api/users/{user_id}/role` happy path; invalid role → 400; missing body → 400. `GET /api/users` includes `role`. |
| `test_admin_tools.py` (NEW) | For each of 4 new tools + `create_user`: admin caller succeeds, non-admin caller raises `PermissionError`, unauth'd raises. Bulk `set_tool_permission` with mixed enable/disable applies all; empty list returns `applied=0`; `applied` count reflects upserts. `set_skill_permission` symmetric. `set_user_role` rejects unknown role. `list_users` returns role field. |
| `test_init_gate.py` (extend) | New tools are in `INTENT_NEVER_REQUIRED` and callable without an active task. |
| `test_mcp_server.py` (extend) | `_require_admin` resolves caller via the existing auth middleware ctx-var; raises when no caller / role != admin. |

Fixture additions: existing pytest-postgresql fixture seeds an `admin_api_key` and a `user_api_key` for admin-vs-non-admin assertions.

## Observability

- Every new tool call flows through the existing telemetry patch — visible in `get_tool_stats` and `get_session_usage` tagged with `user_id`.
- Failed admin checks recorded as `success=0, error_type="PermissionError"`. A spike is a leading indicator of attempted escalation; worth a one-line note in the operator docs.
- Startup logs the bootstrap pass: `[admin-bootstrap] promoted <n> users, skipped <m> unknown: promoted=[…] skipped_unknown=[…]`.

## Cluster Closeout (in the same PR or immediately after merge)

- **#29** — close as "fixed by <PR>".
- **#27** — comment confirming per-tool scoping for proxied integrations already works (path-parameter `tool_name` in `tool_permissions`), close. Open new issue for cost-metadata half ("Surface API credit cost metadata for Apollo / Wiza / Exa") — that's not an access-grant concern.
- **#25** — comment with a one-liner pointing at the new MCP tools and the role-bootstrap env var; close (its job was the manual workaround).
- New issue: "Permission sets / custom roles" — depends on this work landing first; cites #25's "tool-by-tool toggling is tedious" complaint and lays out a `role → permission_set → {tools, skills}` lookup table as the next step.

## Out of Scope

- `BOOTSTRAP_ADMIN_USER_IDS` parsing edge cases (multi-byte, escaped commas) — splitting on `,` and stripping is enough for the user_id forms in use.
- Mass tool-allowlist editing UX in the admin UI (would be obsoleted by permission sets).
- Audit log of who promoted/demoted whom — call telemetry already records the caller `user_id` for `set_user_role`, which is sufficient for now.
- Self-demotion lock-out beyond disabling the dropdown for the current admin in the UI — backend allows it; the UI affordance is enough.
