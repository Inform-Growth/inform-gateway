# Skills Gating & Per-Tool Intent-Required Toggle — Design

**Date:** 2026-05-08
**Status:** Draft for review
**Branch:** `main` (port to `template/clean-gateway` as follow-up)

## Problem

Two governance gaps in the current gateway:

1. **Skills have no permission model.** Any authenticated agent can call `skill_list` and `run_skill` for every skill in their org. Tools have `tool_permissions` (per-user + global `*` sentinel); skills have nothing equivalent.
2. **The init/intent gate is hardcoded.** `_TASK_BYPASS` is a frozenset in `core/mcp_server.py` listing the ~16 tools that skip the `declare_intent` requirement. Admins cannot adjust this without code changes — they can't, for example, require intent declaration before `run_skill` even though that's a high-leverage action worth governing.

Roles / permission sets are explicitly out of scope for this design — they're a future consideration.

## Goals

- Gate skills using the same model as tools (per-user + global `*` sentinel, default-allow).
- Let admins toggle the intent requirement per tool, per user, with a global `*` override.
- Prevent admins from accidentally locking the org out by toggling bootstrap-critical tools.
- Zero behavior change on deploy until an admin sets an override.

## Non-Goals

- Roles or permission sets.
- A bulk-edit UI; toggles remain per-row.
- A separate audit log table (telemetry already records every admin API call).
- Versioned migration tooling (Alembic etc.) — keep the existing additive pattern.

## Architecture

Two new SQLite tables in `core/telemetry.py`, two new admin API route pairs, two new admin UI panels (or a tabbed extension of the existing `PermissionsPanel`), and one resolution helper in `core/mcp_server.py`.

### 1. Skills gating

#### Schema

Added to `_SCHEMA_TABLES` in `core/telemetry.py`:

```sql
CREATE TABLE IF NOT EXISTS skill_permissions (
    user_id    TEXT    NOT NULL,
    skill_name TEXT    NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, skill_name)
);
```

Identical shape to `tool_permissions`. `user_id = '*'` is the global toggle. Default-allow: absence of a row means the skill is enabled for that user.

#### TelemetryStore additions

Methods mirror the tool-permission API:

- `is_skill_enabled(user_id: str, skill_name: str) -> bool` — checks user-specific row, then global `*` row, then returns `True`.
- `get_skill_permissions(user_id: str) -> list[dict]` — every skill known to the org with its effective enabled state.
- `set_skill_permission(user_id: str, skill_name: str, enabled: bool) -> None`.
- `_disabled_skills_cache: dict[str, set[str]]` populated at startup like `_disabled_cache`, keyed by `user_id` (with `'*'` as the global key).

#### Enforcement

In `tools/_core/skill_manager.py`:

- `skill_list()` filters its return value, dropping any skill where `is_skill_enabled(user_id, name)` is `False`.
- `run_skill(name, ...)` raises `PermissionError` (caught by the wrapper layer and turned into a structured error) when the skill is disabled. Error shape:
  ```json
  {"gateway_status": "skill_disabled", "skill": "<name>", "message": "This skill is disabled for your account."}
  ```
- `_AuthMiddleware` already guarantees a resolved `user_id` on every MCP transport request, so the lookup always has a real user to check; no anonymous-call edge case to handle.

#### Admin API

In `core/admin_api.py`:

- `GET /api/skill-permissions/{user_id}` — lists every skill in the org with the effective enabled state. `user_id='*'` returns the global view.
- `PUT /api/skill-permissions/{user_id}/{skill_name}` — body `{"enabled": bool}`. Validates `skill_name` exists in the org's skills table.

#### Admin UI

`remote-gateway/admin-ui/src/routes/operators/`:

- New `SkillPermissionsPanel.tsx` — table of skills with enable/disable toggle, parallels `PermissionsPanel.tsx`.
- Operator detail view gets a tabbed layout: **Tools** | **Skills**.
- Global toggles page (currently for tool `*` permissions) gets the same tab split.

Hook: `usePermissions.ts` is generalized to take a resource type, OR a parallel `useSkillPermissions.ts` is added — choose whichever is less invasive when implementing.

### 2. Per-tool intent-required toggle

#### Schema

Added to `_SCHEMA_TABLES`:

```sql
CREATE TABLE IF NOT EXISTS tool_intent_overrides (
    user_id         TEXT    NOT NULL,
    tool_name       TEXT    NOT NULL,
    requires_intent INTEGER NOT NULL,
    PRIMARY KEY (user_id, tool_name)
);
```

`requires_intent = 1` means intent is required; `0` means not. Absence falls through to the next tier of resolution.

#### Default resolution

In `core/mcp_server.py`:

- Rename `_TASK_BYPASS` → `_TASK_BYPASS_DEFAULTS` (semantics unchanged: tools listed here default to NOT requiring intent).
- New frozenset `_INTENT_NEVER_REQUIRED` — bootstrap tools that admins cannot toggle to require intent:
  ```python
  _INTENT_NEVER_REQUIRED: frozenset[str] = frozenset({
      "setup_start", "setup_save_profile", "setup_complete",
      "health_check",
      "declare_intent", "complete_task", "get_tasks",
      "get_operator_instructions", "create_user",
      "profile_get", "profile_update",
      "list_prompts", "get_prompt",
  })
  ```
  This is slightly tighter than today's `_TASK_BYPASS_DEFAULTS`: the four skill-management tools (`skill_create`, `skill_update`, `skill_list`, `run_skill`) are no longer in the never-required set, so admins CAN choose to require intent before any of them — useful for compliance-conscious orgs.

- New helper:
  ```python
  def _tool_requires_intent(user_id: str | None, tool_name: str) -> bool:
      if tool_name in _INTENT_NEVER_REQUIRED:
          return False
      override = _telemetry.get_tool_intent_override(user_id, tool_name)  # checks user, then '*'
      if override is not None:
          return override
      return tool_name not in _TASK_BYPASS_DEFAULTS
  ```

- The four call sites (currently `if fn.__name__ not in _TASK_BYPASS:` at lines 500, 557, 642, 696) become `if _tool_requires_intent(user_id, fn.__name__):`.

#### TelemetryStore additions

- `get_tool_intent_override(user_id: str | None, tool_name: str) -> bool | None` — returns user-specific override, falling through to `*`, returning `None` if neither exists.
- `set_tool_intent_override(user_id: str, tool_name: str, requires_intent: bool) -> None` — raises `ValueError` if `tool_name in _INTENT_NEVER_REQUIRED`. (The hard-block list is duplicated in telemetry to keep the safety check at the storage layer too; document the duplication and keep them in sync. Alternatively, accept an injected blocklist — implementer's choice.)
- `clear_tool_intent_override(user_id: str, tool_name: str) -> None` — deletes the row, restoring default behavior.
- `get_tool_intent_overrides(user_id: str) -> list[dict]` — every known tool with effective `requires_intent` for the given user (factoring in defaults, global `*`, hard-block).
- Cached at startup analogous to `_disabled_cache`.

#### Admin API

- `GET /api/tool-intent/{user_id}` — list with effective `requires_intent` per tool. Response includes a `locked: bool` flag for tools in `_INTENT_NEVER_REQUIRED`.
- `PUT /api/tool-intent/{user_id}/{tool_name}` — body `{"requires_intent": bool}`. Returns 400 with a clear message if `tool_name` is locked.
- `DELETE /api/tool-intent/{user_id}/{tool_name}` — clears the override.

#### Admin UI

- Extend `PermissionsPanel.tsx` with an additional column **Requires intent** (toggle). Locked rows render the toggle disabled with a tooltip: "Bootstrap tool — intent cannot be required."
- Same column added to the global `*` view.

## Data Flow

### Skill enforcement (run_skill)

```
agent --(run_skill name)--> mcp_server
                              |
                              v
                       skill_manager.run_skill
                              |
                              v
                  is_skill_enabled(user, name)?
                       /              \
                     no                yes
                      |                 |
                      v                 v
              return error      render template & return
```

### Intent enforcement (any gated tool)

```
agent --(call tool)--> mcp_server wrapper
                              |
                              v
                  _tool_requires_intent(user, name)?
                       /              \
                     no                yes
                      |                 |
                      v                 v
                  invoke tool   task_id present?
                                       / \
                                    yes   no
                                     |     |
                                     v     v
                              invoke tool   no_active_task redirect
```

## Migrations

Both new tables are added via `CREATE TABLE IF NOT EXISTS` in `_SCHEMA_TABLES`. New orgs and existing orgs both get them on next boot, idempotently. The `_MIGRATIONS` list (used for `ALTER TABLE ADD COLUMN` on existing tables) is not touched.

Default-allow + default-resolution semantics ensure zero behavior change on deploy until an admin explicitly sets an override.

## Testing

New pytest files in `remote-gateway/tests/`:

### `test_skill_permissions.py`
- Skill is allowed by default for any user.
- User-specific disable hides it from `skill_list` and blocks `run_skill` with a structured error.
- Global `*` disable affects every user.
- User-specific enable beats global `*` disable.
- Admin API: `GET` returns effective state; `PUT` updates; nonexistent skill returns 404.
- Cache is updated when a permission row is written via the API.

### `test_intent_overrides.py`
- For every name in current `_TASK_BYPASS_DEFAULTS`, `_tool_requires_intent('any-user', name)` returns `False` by default.
- For a sample of non-bypass tools, returns `True` by default.
- Global `*` override flips a default-no tool to require intent, and vice versa.
- User-specific override beats global `*`.
- `set_tool_intent_override` raises for every name in `_INTENT_NEVER_REQUIRED`.
- Admin API `PUT` returns 400 for any tool in `_INTENT_NEVER_REQUIRED`; succeeds for `skill_*` tools (verifying the looser hard-block list).
- `DELETE` restores default behavior.
- End-to-end: configure global override requiring intent on `run_skill`, call `run_skill` without `task_id` → receive `no_active_task` redirect.

Existing tests remain green — `_TASK_BYPASS_DEFAULTS` keeps the same membership as today's `_TASK_BYPASS` so the default behavior is unchanged.

## Out of Scope

- Roles / permission sets.
- Bulk-edit operations in admin UI.
- Audit log table (telemetry covers it).
- Versioned migration tooling.
- Per-skill intent requirements (skills are gated by enabled/disabled only; if you want to require intent before `run_skill`, use the per-tool intent toggle on `run_skill` itself).
- Porting to `template/clean-gateway` — tracked as a follow-up. The work in this spec lands on `main` first; the template port is a separate plan after the feature has soaked.

## Risk & Mitigation

- **Risk:** Admin disables `*` for `run_skill` and locks all users out of skills. **Mitigation:** UI shows a confirmation when toggling a global `*` row; tooltip warns about scope.
- **Risk:** Cache drift between `_disabled_skills_cache` and DB. **Mitigation:** All write paths (`set_skill_permission`) update the cache in the same call, mirroring how tool permissions already work.
- **Risk:** Hard-block list drifts between `mcp_server.py` and `telemetry.py`. **Mitigation:** Define `_INTENT_NEVER_REQUIRED` once and import from a single module; reference it from both layers.
- **Risk:** New tables cause issues for orgs with read-only DB filesystems. **Mitigation:** None needed — telemetry already disables itself on setup failure (`_setup` catches Exception); no change to that path.

## Open Questions

None at design time. Ready for plan.
