# Admin Dashboard Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add global tool toggles to the Tools tab, replace the inline log detail panel with a slide-over drawer, and add prev/next pagination to both the Logs and Tools tables.

**Architecture:** All changes are in a single file — `remote-gateway/core/admin_dashboard.html`. No backend changes are needed; the existing `/api/permissions/*` and `/api/logs` endpoints already support all required operations. The four tasks are independent and can be committed separately.

**Tech Stack:** Vanilla JS, HTML/CSS — no build step. Served by Starlette from `admin_api.py`.

---

## File Map

| File | Role |
|---|---|
| `remote-gateway/core/admin_dashboard.html` | All changes — CSS, HTML structure, JavaScript |

**Spec:** `docs/superpowers/specs/2026-04-19-admin-dashboard-improvements-design.md`

---

## How to Test

There is no automated test suite for the dashboard HTML. Each task ends with a browser verification checklist. To run the server locally:

```bash
cd /path/to/inform-gateway
pip install -e .
python remote-gateway/core/mcp_server.py
# Then open: http://localhost:8000/admin/?token=inform-admin-2026
```

---

## Task 1: Slide-Over Log Detail Drawer

Replace the inline `#logs-body-panel` with a fixed right-side drawer that slides in over the page.

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`

- [ ] **Step 1: Add drawer CSS**

In the `<style>` block, replace the entire `/* ---- RESPONSIVE ---- */` comment block (keeping the responsive rules) by inserting the following CSS **before** the responsive rules:

```css
/* ---- LOG DRAWER ---- */
#log-drawer-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.3);
  z-index: 199;
}
#log-drawer-overlay.open { display: block; }

#log-drawer {
  position: fixed;
  top: 0;
  right: 0;
  height: 100vh;
  width: 420px;
  background: var(--cream-light);
  border-left: 2px solid var(--border);
  z-index: 200;
  transform: translateX(100%);
  transition: transform 0.2s ease;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
#log-drawer.open { transform: translateX(0); }

.drawer-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 1rem 1.2rem;
  border-bottom: 1px solid var(--border);
  background: var(--cream-dark);
  flex-shrink: 0;
}
.drawer-title {
  font-family: 'Courier New', monospace;
  font-size: 0.88rem;
  color: var(--green);
  font-weight: 700;
  word-break: break-all;
}
.drawer-meta {
  font-family: 'Courier New', monospace;
  font-size: 0.72rem;
  color: var(--text-muted);
  margin-top: 0.2rem;
}
.drawer-close {
  background: none;
  border: none;
  font-size: 1.3rem;
  cursor: pointer;
  color: var(--text-muted);
  padding: 0;
  line-height: 1;
  flex-shrink: 0;
  margin-left: 0.75rem;
}
.drawer-close:hover { color: var(--orange); }
.drawer-body {
  padding: 1rem 1.2rem;
  flex: 1;
  overflow-y: auto;
}
.drawer-section-label {
  font-family: 'Arial', sans-serif;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 0.4rem;
}
.drawer-section-label.error  { color: var(--orange); }
.drawer-section-label.request { color: var(--text-muted); }
.drawer-pre {
  font-family: 'Courier New', monospace;
  font-size: 0.78rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 340px;
  overflow-y: auto;
  margin: 0 0 1.2rem 0;
}
.drawer-pre.error   { color: var(--orange); }
.drawer-pre.request { color: var(--text); }
#logs-tbody tr.log-selected { background: #d8ecd3; outline: 1px solid var(--green); }
```

- [ ] **Step 2: Add drawer HTML and remove inline panel**

In the HTML, directly before the closing `</body>` tag, add:

```html
<div id="log-drawer-overlay" onclick="closeLogDrawer()"></div>
<div id="log-drawer">
  <div class="drawer-header">
    <div>
      <div class="drawer-title" id="drawer-tool-name"></div>
      <div class="drawer-meta" id="drawer-meta"></div>
    </div>
    <button class="drawer-close" onclick="closeLogDrawer()">&#x2715;</button>
  </div>
  <div class="drawer-body">
    <div id="drawer-error-section" style="display:none;">
      <div class="drawer-section-label error">Error</div>
      <pre class="drawer-pre error" id="drawer-error-content"></pre>
    </div>
    <div id="drawer-request-section" style="display:none;">
      <div class="drawer-section-label request">Request</div>
      <pre class="drawer-pre request" id="drawer-request-content"></pre>
    </div>
  </div>
</div>
```

Also **remove** the entire `<div id="logs-body-panel" ...>` block (lines 616–626 in the current file — the inline panel below the logs table, including its child `#logs-error-section` and `#logs-request-section` divs).

- [ ] **Step 3: Add drawer open/close JS**

In the `<script>` block, replace the existing `showLogBody` function and the `_logsBodyMap`, `_logsErrorMap`, `_selectedLogId` variable declarations with the following:

```javascript
let _logsBodyMap = {};
let _logsErrorMap = {};
let _logsToolMap = {};
let _logsTimeMap = {};
let _selectedLogId = null;

function openLogDrawer(id) {
  document.getElementById('drawer-tool-name').textContent = _logsToolMap[id] || '';
  document.getElementById('drawer-meta').textContent = _logsTimeMap[id] || '';

  const errorMsg = _logsErrorMap[id];
  const errorSection = document.getElementById('drawer-error-section');
  document.getElementById('drawer-error-content').textContent = errorMsg || '';
  errorSection.style.display = errorMsg ? 'block' : 'none';

  const body = _logsBodyMap[id];
  const requestSection = document.getElementById('drawer-request-section');
  if (body) {
    try {
      document.getElementById('drawer-request-content').textContent =
        JSON.stringify(JSON.parse(body), null, 2);
    } catch (_) {
      document.getElementById('drawer-request-content').textContent = body;
    }
    requestSection.style.display = 'block';
  } else {
    requestSection.style.display = 'none';
  }

  document.getElementById('log-drawer-overlay').classList.add('open');
  document.getElementById('log-drawer').classList.add('open');
  _selectedLogId = id;

  document.querySelectorAll('#logs-tbody tr').forEach(r => {
    r.classList.toggle('log-selected', r.dataset.logId === String(id));
  });
}

function closeLogDrawer() {
  document.getElementById('log-drawer-overlay').classList.remove('open');
  document.getElementById('log-drawer').classList.remove('open');
  _selectedLogId = null;
  document.querySelectorAll('#logs-tbody tr').forEach(r => r.classList.remove('log-selected'));
}

function toggleLogDrawer(id) {
  if (_selectedLogId === id) { closeLogDrawer(); return; }
  openLogDrawer(id);
}
```

- [ ] **Step 4: Update `renderLogsTable` to populate maps and use drawer**

Replace the existing `renderLogsTable` function with:

```javascript
function renderLogsTable(logs) {
  _logsBodyMap = {};
  _logsErrorMap = {};
  _logsToolMap = {};
  _logsTimeMap = {};
  _selectedLogId = null;
  closeLogDrawer();

  const tbody = document.getElementById('logs-tbody');

  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-muted);font-style:italic;text-align:center;">No log entries match.</td></tr>';
    return;
  }

  logs.forEach(row => {
    if (row.input_body   != null) _logsBodyMap[row.id]  = row.input_body;
    if (row.error_message != null) _logsErrorMap[row.id] = row.error_message;
    _logsToolMap[row.id] = row.tool_name || '';
    _logsTimeMap[row.id] = row.called_at || '';
  });

  tbody.innerHTML = logs.map(row => {
    const statusBadge = row.success
      ? '<span class="badge badge-green">OK</span>'
      : row.error_type === 'PermissionError'
        ? '<span class="badge badge-red" title="Tool blocked by permissions">BLOCKED</span>'
        : '<span class="badge badge-orange" title="' + escHtml(row.error_type || '') + '">' + escHtml(row.error_type || 'ERR') + '</span>';
    const hasDetail = row.input_body != null || row.error_message != null;
    const rowStyle = hasDetail ? 'cursor:pointer;' : '';
    const onclick  = hasDetail ? ' onclick="toggleLogDrawer(' + escJs(String(row.id)) + ')"' : '';
    return '<tr style="' + rowStyle + '" data-log-id="' + escHtml(String(row.id)) + '"' + onclick + '>'
      + '<td style="white-space:nowrap;font-size:0.75rem;">' + escHtml(row.called_at || '—') + '</td>'
      + '<td>' + escHtml(row.tool_name) + '</td>'
      + '<td style="font-size:0.78rem;">' + escHtml(row.user_id || '—') + '</td>'
      + '<td>' + fmtMs(row.duration_ms) + '</td>'
      + '<td>' + fmtBytes(row.input_size) + '</td>'
      + '<td>' + fmtBytes(row.response_size) + '</td>'
      + '<td>' + statusBadge + '</td>'
      + '</tr>';
  }).join('');
}
```

- [ ] **Step 5: Add Escape key listener**

At the very bottom of the `<script>` block, just before the `loadExec()` call, add:

```javascript
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLogDrawer(); });
```

- [ ] **Step 6: Verify in browser**

Start the server and open the Logs tab.

Checklist:
- Clicking a row with data → drawer slides in from the right ✓
- Drawer shows tool name and timestamp in header ✓
- Error message shown in orange (if error row) ✓
- Request body shown as pretty-printed JSON ✓
- Clicking the same row again → drawer closes ✓
- Clicking × button → drawer closes ✓
- Pressing Escape → drawer closes ✓
- Clicking outside the drawer (grey overlay) → drawer closes ✓
- Clicking a different row while drawer is open → drawer updates to new row ✓
- Clicking a row with no detail → no drawer opens ✓
- No `#logs-body-panel` visible anywhere ✓

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: replace inline log detail panel with slide-over drawer"
```

---

## Task 2: Logs Pagination

Add prev/next pagination to the Logs table. Page size: 100. Server-side via `limit`/`offset`.

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`

- [ ] **Step 1: Add pagination CSS**

In the `<style>` block, add before the responsive rules:

```css
/* ---- PAGINATION ---- */
.pagination-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.75rem;
}
.page-label {
  font-family: 'Courier New', monospace;
  font-size: 0.82rem;
  color: var(--text-muted);
  min-width: 60px;
  text-align: center;
}
.btn:disabled {
  opacity: 0.4;
  cursor: default;
}
```

- [ ] **Step 2: Add pagination HTML below the logs table**

In the Logs view section, directly after the closing `</div>` of the `style="overflow-x:auto;"` wrapper (which contains `#logs-table`), add:

```html
<div class="pagination-bar" id="logs-pagination">
  <button class="btn btn-green" id="logs-prev" onclick="logsPagePrev()" disabled>Prev</button>
  <span class="page-label" id="logs-page-label">Page 1</span>
  <button class="btn btn-green" id="logs-next" onclick="logsPageNext()">Next</button>
</div>
```

- [ ] **Step 3: Add pagination state and functions**

In the `<script>` block, add after the `_selectedLogId` declaration:

```javascript
let _logsPage = 0;
let _logsHasMore = false;

function logsPagePrev() {
  if (_logsPage === 0) return;
  _logsPage--;
  loadLogs();
}

function logsPageNext() {
  if (!_logsHasMore) return;
  _logsPage++;
  loadLogs();
}

function resetLogsPage() {
  _logsPage = 0;
  loadLogs();
}
```

- [ ] **Step 4: Update `loadLogs` to use pagination**

Replace the existing `loadLogs` function with:

```javascript
async function loadLogs() {
  const tool       = (document.getElementById('logs-filter-tool').value    || '').trim();
  const user       = (document.getElementById('logs-filter-user').value    || '').trim();
  const successVal =  document.getElementById('logs-filter-success').value;

  let url = apiUrl('/api/logs') + '&limit=100&offset=' + (_logsPage * 100);
  if (tool) url += '&tool='    + encodeURIComponent(tool);
  if (user) url += '&user='    + encodeURIComponent(user);
  if (successVal === 'blocked') {
    url += '&success=false&error_type=PermissionError';
  } else if (successVal) {
    url += '&success=' + encodeURIComponent(successVal);
  }

  try {
    const res  = await fetch(url);
    const logs = await res.json();
    const arr  = Array.isArray(logs) ? logs : [];
    _logsHasMore = arr.length === 100;
    renderLogsTable(arr);
    updateTimestamp();

    document.getElementById('logs-page-label').textContent = 'Page ' + (_logsPage + 1);
    document.getElementById('logs-prev').disabled = _logsPage === 0;
    document.getElementById('logs-next').disabled = !_logsHasMore;
  } catch (e) {
    console.error('loadLogs error:', e);
  }
}
```

- [ ] **Step 5: Update filter inputs to reset page**

In the Logs view HTML, change the three filter inputs to call `resetLogsPage()` instead of `loadLogs()`:

```html
<!-- tool filter -->
oninput="resetLogsPage()"

<!-- user filter -->
oninput="resetLogsPage()"

<!-- success select -->
onchange="resetLogsPage()"
```

- [ ] **Step 6: Verify in browser**

Open the Logs tab.

Checklist:
- Prev is disabled on page 1 ✓
- Next is disabled when fewer than 100 rows are returned ✓
- Next is enabled when exactly 100 rows are returned ✓
- Clicking Next advances to Page 2 and loads next 100 rows ✓
- Clicking Prev returns to Page 1 ✓
- Changing a filter resets to Page 1 ✓
- Pagination bar is visible below the table ✓

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: add prev/next pagination to logs table"
```

---

## Task 3: Global Tool Toggles

Add a "Global" toggle column to the Tools table. Toggle calls `PUT /api/permissions/*/{tool_name}`. Globally-disabled tools show as `GLOBAL OFF` (non-interactive) in the Ops permissions panel.

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`

- [ ] **Step 1: Add global permissions state and tools page state**

In the `<script>` block, add after the `_toolsData` declaration:

```javascript
let _globalDisabled = new Set();
let _toolsPage = 0;
```

- [ ] **Step 2: Update `loadTools` to fetch global permissions in parallel**

Replace the existing `loadTools` function with:

```javascript
async function loadTools() {
  try {
    const fetches = [fetch(apiUrl('/api/tools')), fetch(apiUrl('/api/permissions/*'))];
    if (!_healthData.length) fetches.push(fetch(apiUrl('/api/stats')));
    const results = await Promise.all(fetches);

    _toolsData = await results[0].json();

    const globalPerms = await results[1].json();
    _globalDisabled = new Set(
      (globalPerms.permissions || [])
        .filter(p => !p.enabled)
        .map(p => p.tool_name)
    );

    if (results[2]) {
      const stats = await results[2].json();
      _healthData = stats.tools || [];
    }

    renderToolsTable();
    updateTimestamp();
  } catch (e) {
    console.error('loadTools error:', e);
  }
}
```

- [ ] **Step 3: Add "Global" column header to tools table**

In the Tools view HTML, replace the `<thead>` of `#tools-table`:

```html
<thead>
  <tr>
    <th onclick="sortTools('name')">Tool</th>
    <th>Description</th>
    <th onclick="sortTools('call_count')">Calls</th>
    <th onclick="sortTools('status')">Status</th>
    <th onclick="sortTools('last_called')">Last Called</th>
    <th>Global</th>
  </tr>
</thead>
```

- [ ] **Step 4: Update `renderToolsTable` to include global toggle per row**

Replace the `tbody.innerHTML = rows.map(r => { ... }).join('');` block inside `renderToolsTable` with:

```javascript
tbody.innerHTML = rows.map(r => {
  const isDisabled = _globalDisabled.has(r.name);
  const rowOpacity = isDisabled ? 'opacity:0.5;' : '';
  const badge = isDisabled
    ? '<span class="badge badge-red">Disabled</span>'
    : r.status === 'active'
      ? '<span class="badge badge-green">Active</span>'
      : '<span class="badge" style="background:var(--cream-dark);color:var(--text-muted);">Never called</span>';
  const toggleChecked = isDisabled ? '' : 'checked';
  const tid = 'gtoggle-' + r.name.replace(/[^a-z0-9]/gi, '_');
  return `<tr style="${rowOpacity}">
    <td>${escHtml(r.name)}</td>
    <td style="font-size:0.78rem;color:var(--text-muted);font-family:'Arial',sans-serif;max-width:320px;">${escHtml(r.description)}</td>
    <td>${escHtml(r.call_count)}</td>
    <td>${badge}</td>
    <td>${fmtDate(r.last_called)}</td>
    <td>
      <label class="toggle-wrap" title="${isDisabled ? 'Globally disabled' : 'Globally enabled'}">
        <input type="checkbox" id="${escHtml(tid)}" ${toggleChecked}
          onchange="setGlobalPermission('${escJs(r.name)}',this.checked)" />
        <span class="toggle-slider"></span>
      </label>
    </td>
  </tr>`;
}).join('');
```

- [ ] **Step 5: Add `setGlobalPermission` function**

In the `<script>` block, add after `loadTools`:

```javascript
async function setGlobalPermission(toolName, enabled) {
  try {
    await fetch(
      apiUrl('/api/permissions/*/' + encodeURIComponent(toolName)),
      {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled}),
      }
    );
    if (enabled) {
      _globalDisabled.delete(toolName);
    } else {
      _globalDisabled.add(toolName);
    }
    renderToolsTable();
    // Keep Ops permissions panel in sync if a user is selected
    if (_selectedUser) await loadPermissions(_selectedUser);
  } catch (e) {
    console.error('setGlobalPermission error:', e);
  }
}
```

- [ ] **Step 6: Update `loadPermissions` to also fetch global perms**

Replace the existing `loadPermissions` function with:

```javascript
async function loadPermissions(userId) {
  try {
    const [permsRes, globalRes] = await Promise.all([
      fetch(apiUrl('/api/permissions/' + encodeURIComponent(userId))),
      fetch(apiUrl('/api/permissions/*')),
    ]);
    const data       = await permsRes.json();
    const globalData = await globalRes.json();
    _globalDisabled = new Set(
      (globalData.permissions || [])
        .filter(p => !p.enabled)
        .map(p => p.tool_name)
    );
    renderPermissions(userId, data.permissions || []);
  } catch (e) {
    console.error('loadPermissions error:', e);
  }
}
```

- [ ] **Step 7: Update `_renderPermRows` to show GLOBAL OFF**

Replace the existing `_renderPermRows` function with:

```javascript
function _renderPermRows(permissions, userId) {
  const list = document.getElementById('perms-list');
  if (permissions.length === 0) {
    list.innerHTML = '<p class="muted-msg">No tools match.</p>';
    return;
  }
  list.innerHTML = permissions.map(p => {
    if (_globalDisabled.has(p.tool_name)) {
      return `<div class="perm-row">
        <span class="perm-tool-name" style="opacity:0.5;">${escHtml(p.tool_name)}</span>
        <span class="badge badge-red" style="font-size:0.65rem;letter-spacing:0.04em;">GLOBAL OFF</span>
      </div>`;
    }
    const checked = p.enabled ? 'checked' : '';
    const tid = 'toggle-' + escHtml(p.tool_name).replace(/[^a-z0-9]/gi, '_');
    return `<div class="perm-row">
      <span class="perm-tool-name">${escHtml(p.tool_name)}</span>
      <label class="toggle-wrap" title="${p.enabled ? 'Enabled' : 'Disabled'}">
        <input type="checkbox" id="${escHtml(tid)}" ${checked}
          onchange="setPermission('${escJs(escHtml(userId))}','${escJs(escHtml(p.tool_name))}',this.checked)" />
        <span class="toggle-slider"></span>
      </label>
    </div>`;
  }).join('');
}
```

- [ ] **Step 8: Verify in browser**

Open the Tools tab.

Checklist:
- "Global" column appears as the rightmost column with a toggle per row ✓
- All toggles default to ON (checked) for tools with no global override ✓
- Toggling a tool OFF → row dims, status badge changes to "Disabled" ✓
- Refresh page → previously disabled tools still show as off (persisted via API) ✓
- Switch to Ops tab, select a user → globally disabled tool shows "GLOBAL OFF" label instead of a toggle ✓
- Toggle a tool back ON in Tools tab → GLOBAL OFF label disappears in Ops panel (if already open) ✓

- [ ] **Step 9: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: add global tool toggles to Tools tab"
```

---

## Task 4: Tools Pagination

Add client-side prev/next pagination to the Tools table. Page size: 50.

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`

- [ ] **Step 1: Add tools pagination functions**

In the `<script>` block, add after `_toolsPage` (declared in Task 3 Step 1):

```javascript
function toolsPagePrev() {
  if (_toolsPage === 0) return;
  _toolsPage--;
  renderToolsTable();
}

function toolsPageNext() {
  _toolsPage++;
  renderToolsTable();
}
```

- [ ] **Step 2: Update `renderToolsTable` to slice for current page**

At the top of `renderToolsTable`, after the `rows.sort(...)` call and before `tbody.innerHTML`, add:

```javascript
const PAGE_SIZE = 50;
const pageRows  = rows.slice(_toolsPage * PAGE_SIZE, (_toolsPage + 1) * PAGE_SIZE);
const hasNext   = (_toolsPage + 1) * PAGE_SIZE < rows.length;
```

Then change `rows.map(r => {` to `pageRows.map(r => {` in the `tbody.innerHTML` assignment added in Task 3 Step 4.

At the end of `renderToolsTable`, after setting `tbody.innerHTML`, add:

```javascript
document.getElementById('tools-page-label').textContent = 'Page ' + (_toolsPage + 1);
document.getElementById('tools-prev').disabled = _toolsPage === 0;
document.getElementById('tools-next').disabled = !hasNext;
```

- [ ] **Step 3: Reset page on sort**

In the `sortTools` function, add `_toolsPage = 0;` before the `renderToolsTable()` call:

```javascript
function sortTools(key) {
  if (_toolsSortKey === key) _toolsSortAsc = !_toolsSortAsc;
  else { _toolsSortKey = key; _toolsSortAsc = true; }
  _toolsPage = 0;
  renderToolsTable();
}
```

- [ ] **Step 4: Add pagination HTML below tools table**

In the Tools view section, directly after the closing `</div>` of `#tools-table`'s parent `.section-box` — actually, place it inside the `.section-box`, after the `</table>` tag:

```html
<div class="pagination-bar" id="tools-pagination">
  <button class="btn btn-green" id="tools-prev" onclick="toolsPagePrev()" disabled>Prev</button>
  <span class="page-label" id="tools-page-label">Page 1</span>
  <button class="btn btn-green" id="tools-next" onclick="toolsPageNext()">Next</button>
</div>
```

(The `.pagination-bar` CSS was added in Task 2 Step 1 — no new CSS needed here.)

- [ ] **Step 5: Verify in browser**

Open the Tools tab (with enough tools to exceed 50).

Checklist:
- Pagination bar appears below the tools table ✓
- Prev is disabled on page 1 ✓
- Next is disabled when total tools ≤ 50 ✓
- Next navigates to page 2 when total tools > 50 ✓
- Clicking a column header to sort resets to page 1 ✓
- Global toggle still works correctly on paginated rows ✓

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: add prev/next pagination to tools table"
```
