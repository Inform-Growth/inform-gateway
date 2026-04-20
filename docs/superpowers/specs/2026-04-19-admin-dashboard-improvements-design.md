# Admin Dashboard Improvements — Design Spec

**Date:** 2026-04-19  
**Status:** Approved  
**Scope:** `remote-gateway/core/admin_dashboard.html` only — no backend changes required.

---

## Overview

Three targeted improvements to the admin dashboard:

1. **Global tool toggles** in the Tools tab
2. **Log detail slide-over drawer** replacing the inline panel
3. **Pagination** on both Logs and Tools tables

---

## 1. Global Tool Toggles

### What it does

Each row in the Tools tab gets a "Global" toggle column. Toggling a tool off globally disables it for all users — it is hidden from `tools/list` and blocked at call time (backend already enforces this via the `user_id = "*"` sentinel in `tool_permissions`).

### Data flow

- On `loadTools()`, fetch `GET /api/permissions/*` in parallel with `GET /api/tools`.
- Build a `_globalDisabled` Set from the response: tools where `enabled === false`.
- Render a toggle per row defaulting to `true` for tools with no explicit override.
- Toggle onChange calls `PUT /api/permissions/*/{tool_name}` with `{enabled: bool}`.
- Update `_globalDisabled` in-memory on success — no full reload needed.

### Tools table changes

- New rightmost column header: **Global**
- Each row: toggle switch using the existing `.toggle-wrap` / `.toggle-slider` CSS.
- Rows for globally-disabled tools: dimmed (`opacity: 0.5`), status badge changes to `DISABLED`.

### Ops permissions panel cross-effect

In `_renderPermRows`, tools present in `_globalDisabled` render differently:
- Tool name is dimmed.
- Toggle is hidden.
- A small `GLOBAL OFF` label (styled like `.badge badge-red`) replaces the toggle.
- This makes them non-interactive in per-user permission management.

---

## 2. Log Detail Slide-Over Drawer

### Structure

A `<div id="log-drawer">` is added directly inside `<body>`, outside `<main>`. It sits at `position: fixed; right: 0; top: 0; height: 100vh; width: 420px; z-index: 200`. A semi-transparent overlay `<div id="log-drawer-overlay">` covers the rest of the viewport at `z-index: 199`.

Both start hidden. When open:
- Drawer slides in via `transform: translateX(0)` (from `translateX(100%)`), CSS transition 200ms ease.
- Overlay fades in at `opacity: 0.3` background `#000`.

### Content

- **Header**: tool name (bold) + timestamp, plus a `×` close button top-right.
- **Error section** (if present): orange label + `<pre>` with error message.
- **Request body section** (if present): muted label + `<pre>` with pretty-printed JSON.
- Both sections use the same styling as the existing inline panel.

### Interactions

- Clicking a log row with detail opens the drawer and highlights the row.
- Clicking the `×` button closes it.
- Pressing `Escape` closes it.
- Clicking the overlay closes it.
- Clicking the same row again closes it (toggle behavior).

### Removal

The existing `#logs-body-panel` div and its children are removed entirely.

---

## 3. Pagination

### Logs (server-side)

- **Page size:** 100 rows.
- **State:** `_logsPage` integer (0-indexed), reset to 0 on any filter change.
- **API:** existing `limit` and `offset` params — `limit=100&offset=(_logsPage * 100)`.
- **Controls:** Prev button, "Page N" label, Next button — rendered in a `<div>` below the logs table.
- **Prev** disabled when `_logsPage === 0`.
- **Next** disabled when the returned row count is less than 100 (signals last page).

### Tools (client-side)

- **Page size:** 50 rows.
- **State:** `_toolsPage` integer (0-indexed), reset to 0 on any sort change.
- **Rendering:** `renderToolsTable()` slices the full sorted `rows` array: `rows.slice(_toolsPage * 50, (_toolsPage + 1) * 50)`.
- **Controls:** Same Prev / "Page N" / Next pattern below the tools table.
- **Prev** disabled on page 0; **Next** disabled when the slice would be empty.

### Shared pagination control style

```html
<div class="pagination-bar">
  <button class="btn btn-green" id="X-prev">Prev</button>
  <span class="page-label">Page N</span>
  <button class="btn btn-green" id="X-next">Next</button>
</div>
```

CSS: `display: flex; align-items: center; gap: 0.75rem; margin-top: 0.75rem;`. Page label uses Courier New monospace, same muted color as table metadata.

---

## Files Changed

| File | Change |
|---|---|
| `remote-gateway/core/admin_dashboard.html` | All three improvements — CSS additions, HTML structural changes, JS logic |

No backend changes. No new API endpoints. All existing routes are sufficient.

---

## Out of Scope

- Badge/count indicators on tab bar (Option B, declined).
- Bulk enable/disable actions.
- MCP-level (connection-level) toggles — only tool-level toggles are in scope.
