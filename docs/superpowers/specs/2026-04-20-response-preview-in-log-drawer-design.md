# Response Preview in Log Drawer — Design Spec

**Date:** 2026-04-20
**Status:** Approved

## Problem

The log details drawer shows the request body and error message, but no response content. When a tool call succeeds without an explicit error but returns unexpected or garbage data, there is no way to spot-check it in the dashboard. The operator has to go to raw DB queries or add external logging to investigate.

## Goal

Add a **Response Preview** section to the log drawer — a 400-char truncated snapshot of the response — so operators can immediately see "does this look okay?" without leaving the dashboard.

## Scope

- Store the first 400 chars of every tool response at write time (not the full body)
- Surface it in the drawer as a "Response Preview" section with a size hint
- No new API endpoints; no new query parameters
- Existing log rows will have `NULL` for this field — the section simply won't appear

## Architecture

### Files Changed

| File | Change |
|---|---|
| `remote-gateway/core/telemetry.py` | Add `response_preview TEXT` column, migration, `record()` param, `raw_logs()` return field |
| `remote-gateway/core/mcp_server.py` | Capture first 400 chars of `str(result)` and pass as `response_preview` to `record()` |
| `remote-gateway/core/admin_dashboard.html` | Add `_logsResponseMap`, drawer HTML section, drawer JS population |

### Data Layer

**Schema addition** — `telemetry.py`:
```python
response_preview TEXT  -- first 400 chars of str(result), NULL for old rows
```

**Migration** — add to `_MIGRATIONS` list (same pattern as existing entries):
```python
("tool_calls", "response_preview", "TEXT"),
```

**Capture** — `mcp_server.py`, at every point `_calculate_response_size(result)` is called, also compute:
```python
response_preview = str(result)[:400] if result is not None else None
```
Pass as `response_preview=response_preview` to `_telemetry.record()`.

**Storage** — `telemetry.py` `record()` signature gains `response_preview: str | None = None`, inserted into the same `INSERT` statement.

**Query** — `raw_logs()` already selects all columns from the `SELECT` list; add `response_preview` to the SELECT and to the returned dict.

### Frontend

**Data map** — in `renderLogsTable`, populate alongside existing maps:
```javascript
if (row.response_preview != null) _logsResponseMap[row.id] = row.response_preview;
```

**Drawer HTML** — new section placed between Error and Request:
```html
<div id="drawer-response-section" style="display:none;">
  <div class="drawer-section-label response">Response Preview</div>
  <pre class="drawer-pre response" id="drawer-response-content"></pre>
  <div class="drawer-response-hint" id="drawer-response-hint"></div>
</div>
```

**CSS** — reuse existing `.drawer-section-label` and `.drawer-pre` patterns; add a `response` color variant (neutral/text color, not orange) and a small hint style:
```css
.drawer-section-label.response { color: var(--text-muted); }
.drawer-pre.response            { color: var(--text); }
.drawer-response-hint {
  font-family: 'Courier New', monospace;
  font-size: 0.68rem;
  color: var(--text-muted);
  margin-top: -0.8rem;
  margin-bottom: 1.2rem;
}
```

**Drawer JS** — in `openLogDrawer`, after the error section block:
```javascript
const preview = _logsResponseMap[id];
const responseSection = document.getElementById('drawer-response-section');
if (preview != null) {
  document.getElementById('drawer-response-content').textContent = preview;
  const fullSize = _logsResponseSizeMap[id];
  const hint = fullSize && fullSize > 400
    ? `preview · full response: ${fullSize.toLocaleString()} chars`
    : 'full response';
  document.getElementById('drawer-response-hint').textContent = hint;
  responseSection.style.display = 'block';
} else {
  responseSection.style.display = 'none';
}
```

This requires a second map `_logsResponseSizeMap` populated from `row.response_size` (already returned by `raw_logs()`).

## Drawer Section Order

1. **Error** (orange) — if `error_message` present
2. **Response Preview** (neutral) — if `response_preview` present
3. **Request** (neutral) — if `input_body` present

## Edge Cases

- `response_preview` is NULL for log rows written before this change → section hidden, no visual gap
- Response is ≤400 chars → no truncation indicator shown (`full response` hint instead of `preview · N chars`)
- `result` is `None` → `response_preview` stored as NULL → section hidden

## Out of Scope

- Storing the full response body
- A "show full response" expand button (can be added later)
- Filtering logs by response content
