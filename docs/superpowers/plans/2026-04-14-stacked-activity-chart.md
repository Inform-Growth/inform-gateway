# Stacked Activity Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat green bar chart in the "Activity — Last 30 Days" panel with a stacked bar chart broken down by user, and increase the chart height so it's no longer vertically squished.

**Architecture:** Add a `daily_activity_by_user()` method to `TelemetryStore` that pivots `GROUP BY day, user_id` results into a D3-friendly structure `{users, days}`. The `/api/timeline` endpoint returns this new format. `renderTimeline()` in the dashboard HTML is rewritten to use `d3.stack()` with a per-user color palette and a legend row below the chart.

**Tech Stack:** Python/SQLite (telemetry), Starlette (API), D3 v7 (chart), vanilla JS/HTML

---

### Task 1: Add `daily_activity_by_user()` to TelemetryStore

**Files:**
- Modify: `remote-gateway/core/telemetry.py` (add method after `daily_activity`)
- Test: `remote-gateway/tests/test_telemetry_permissions.py` (add tests at bottom)

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `remote-gateway/tests/test_telemetry_permissions.py`:

```python
# ---------------------------------------------------------------------------
# daily_activity_by_user
# ---------------------------------------------------------------------------

def test_daily_activity_by_user_empty(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.daily_activity_by_user(days=30)
    assert result == {"users": [], "days": []}


def test_daily_activity_by_user_single_user(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    store.record("health_check", 10, True, user_id="alice@example.com")
    store.record("health_check", 20, True, user_id="alice@example.com")
    result = store.daily_activity_by_user(days=30)
    assert result["users"] == ["alice@example.com"]
    assert len(result["days"]) == 1
    day = result["days"][0]
    assert day["alice@example.com"] == 2


def test_daily_activity_by_user_multiple_users_same_day(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    store.record("health_check", 10, True, user_id="alice@example.com")
    store.record("health_check", 10, True, user_id="bob@example.com")
    store.record("health_check", 10, True, user_id="bob@example.com")
    result = store.daily_activity_by_user(days=30)
    assert sorted(result["users"]) == ["alice@example.com", "bob@example.com"]
    assert len(result["days"]) == 1
    day = result["days"][0]
    assert day["alice@example.com"] == 1
    assert day["bob@example.com"] == 2


def test_daily_activity_by_user_absent_user_gets_zero(tmp_path):
    """A user who had no calls on a given day gets 0, not a missing key."""
    store = TelemetryStore(db_path=tmp_path / "test.db")
    store.record("health_check", 10, True, user_id="alice@example.com")
    store.record("health_check", 10, True, user_id="bob@example.com")
    result = store.daily_activity_by_user(days=30)
    # Both users appear in every day record
    for day in result["days"]:
        assert "alice@example.com" in day
        assert "bob@example.com" in day


def test_daily_activity_by_user_null_user_id_becomes_unknown(tmp_path):
    """Calls with no user_id are grouped under 'unknown'."""
    store = TelemetryStore(db_path=tmp_path / "test.db")
    store.record("health_check", 10, True)   # user_id=None
    result = store.daily_activity_by_user(days=30)
    assert "unknown" in result["users"]
    assert result["days"][0]["unknown"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/test_telemetry_permissions.py -k "daily_activity_by_user" -v
```

Expected: All 5 tests FAIL with `AttributeError: 'TelemetryStore' object has no attribute 'daily_activity_by_user'`

- [ ] **Step 3: Implement `daily_activity_by_user` in `telemetry.py`**

Add this method directly after the closing `}` of `daily_activity()` (around line 628), before `raw_logs`:

```python
def daily_activity_by_user(self, days: int = 30) -> dict[str, Any]:
    """Return per-user, per-day call counts for the last N calendar days.

    Args:
        days: How many days back to include (default: 30).

    Returns:
        Dict with:
          - ``users``: sorted list of distinct user_id strings seen in the period
          - ``days``: list of dicts ordered ascending by date, each with a
            ``'day'`` key (YYYY-MM-DD) and one key per user_id containing that
            user's call count (0 for users absent on that day).
        Days with zero activity across ALL users are omitted.
    """
    if not self._enabled:
        return {"users": [], "days": []}
    try:
        conn = self._connect()
        cutoff = time.time() - days * 86400
        rows = conn.execute(
            """
            SELECT
                date(called_at, 'unixepoch') AS day,
                COALESCE(user_id, 'unknown') AS user_id,
                COUNT(*)                     AS calls
            FROM tool_calls
            WHERE called_at >= ?
            GROUP BY day, user_id
            ORDER BY day ASC
            """,
            (cutoff,),
        ).fetchall()
        conn.close()
    except Exception:
        return {"users": [], "days": []}

    # Pivot rows into {day -> {user_id -> calls}}
    days_map: dict[str, dict[str, int]] = {}
    users_seen: set[str] = set()
    for row in rows:
        day = row["day"]
        uid = row["user_id"]
        users_seen.add(uid)
        if day not in days_map:
            days_map[day] = {}
        days_map[day][uid] = row["calls"]

    users = sorted(users_seen)
    day_records = []
    for day in sorted(days_map):
        record: dict[str, Any] = {"day": day}
        for uid in users:
            record[uid] = days_map[day].get(uid, 0)
        day_records.append(record)

    return {"users": users, "days": day_records}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/test_telemetry_permissions.py -k "daily_activity_by_user" -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/ -v
```

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_telemetry_permissions.py
git commit -m "feat: add daily_activity_by_user to TelemetryStore for per-user stacked chart"
```

---

### Task 2: Update `/api/timeline` to return per-user data

**Files:**
- Modify: `remote-gateway/core/admin_api.py` (one line change in `api_timeline`)
- Test: `remote-gateway/tests/test_admin_api.py` (add tests at bottom)

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `remote-gateway/tests/test_admin_api.py`:

```python
# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def test_timeline_empty(client):
    c, _ = client
    resp = c.get(f"/api/timeline?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"users": [], "days": []}


def test_timeline_returns_per_user_breakdown(client):
    c, store = client
    store.record("health_check", 10, True, user_id="alice@example.com")
    store.record("health_check", 10, True, user_id="bob@example.com")
    store.record("health_check", 10, True, user_id="alice@example.com")
    resp = c.get(f"/api/timeline?token={TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["users"]) == ["alice@example.com", "bob@example.com"]
    assert len(body["days"]) == 1
    day = body["days"][0]
    assert day["alice@example.com"] == 2
    assert day["bob@example.com"] == 1


def test_timeline_forbidden_without_token(client):
    c, _ = client
    resp = c.get("/api/timeline")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/test_admin_api.py -k "timeline" -v
```

Expected: `test_timeline_empty` FAILS (returns `[]` not `{"users":[], "days":[]}`), `test_timeline_returns_per_user_breakdown` FAILS, `test_timeline_forbidden_without_token` PASSES (auth check already works).

- [ ] **Step 3: Update `api_timeline` in `admin_api.py`**

In `remote-gateway/core/admin_api.py`, find the `api_timeline` function (around line 142). Change the return line from:

```python
        return JSONResponse(telemetry.daily_activity(days=days))
```

to:

```python
        return JSONResponse(telemetry.daily_activity_by_user(days=days))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/test_admin_api.py -k "timeline" -v
```

Expected: All 3 timeline tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/ -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_api.py
git commit -m "feat: update /api/timeline to return per-user breakdown for stacked chart"
```

---

### Task 3: Rewrite `renderTimeline` as a stacked bar chart

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html`
  - `renderTimeline` function (~line 741–800): full replacement
  - `loadDashboard` call site (~line 733): update format handling

- [ ] **Step 1: Update the `loadDashboard` call site**

In `admin_dashboard.html`, find the line (around line 733):

```javascript
      renderTimeline(Array.isArray(timeline) ? timeline : []);
```

Replace it with:

```javascript
      renderTimeline(timeline && typeof timeline === 'object' ? timeline : {users: [], days: []});
```

- [ ] **Step 2: Replace `renderTimeline` with the stacked implementation**

Find and replace the entire `renderTimeline` function (from `function renderTimeline(data) {` through its closing `}` at around line 800).

Replace with:

```javascript
  // --- Activity Timeline (stacked by user) ---
  function renderTimeline(data) {
    const container = document.getElementById('timeline-container');
    container.innerHTML = '';

    const users = data.users || [];
    const days  = data.days  || [];

    if (!days.length || !users.length) {
      container.innerHTML = '<p class="muted-msg">No activity in the last 30 days.</p>';
      return;
    }

    const W      = container.clientWidth || 800;
    const H      = 300;
    const margin = {top: 12, right: 16, bottom: 36, left: 40};
    const iW     = W - margin.left - margin.right;
    const iH     = H - margin.top - margin.bottom;

    // Earthy palette — consistent with the existing green/tan aesthetic
    const PALETTE = ['#2d5a27','#6b8f47','#a3b18a','#c4865a','#8b6914','#4a7c7e','#7a4f3a','#3d6b6b'];
    const colorOf = uid => PALETTE[users.indexOf(uid) % PALETTE.length];

    const svg = d3.select(container)
      .append('svg')
      .attr('viewBox', '0 0 ' + W + ' ' + H)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    const g = svg.append('g')
      .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

    // Stack
    const series = d3.stack().keys(users)(days);

    const x = d3.scaleBand()
      .domain(days.map(d => d.day))
      .range([0, iW])
      .padding(0.15);

    const y = d3.scaleLinear()
      .domain([0, d3.max(series, layer => d3.max(layer, d => d[1])) || 1])
      .nice()
      .range([iH, 0]);

    // Stacked bars — one <g> layer per user
    g.selectAll('g.layer')
      .data(series)
      .join('g')
        .attr('class', 'layer')
        .attr('fill', d => colorOf(d.key))
        .each(function(layerData) {
          d3.select(this).selectAll('rect')
            .data(layerData)
            .join('rect')
              .attr('x', d => x(d.data.day))
              .attr('y', d => y(d[1]))
              .attr('width', x.bandwidth())
              .attr('height', d => Math.max(0, y(d[0]) - y(d[1])))
              .append('title')
                .text(d => d.data.day + ' — ' + layerData.key + ': ' + (d[1] - d[0]) + ' calls');
        });

    // X axis — show ~8 evenly-spaced ticks
    const n = Math.ceil(days.length / 8);
    g.append('g')
      .attr('transform', 'translate(0,' + iH + ')')
      .call(d3.axisBottom(x)
        .tickValues(days.filter((_, i) => i % n === 0).map(d => d.day))
        .tickFormat(d => d.slice(5)))
      .call(a => a.select('.domain').attr('stroke', '#c4b492'))
      .call(a => a.selectAll('.tick line').attr('stroke', '#c4b492'))
      .call(a => a.selectAll('text').attr('font-size', '9px').attr('fill', '#6b6b50'));

    // Y axis
    g.append('g')
      .call(d3.axisLeft(y).ticks(4).tickFormat(d3.format('d')))
      .call(a => a.select('.domain').attr('stroke', '#c4b492'))
      .call(a => a.selectAll('.tick line').attr('stroke', '#c4b492'))
      .call(a => a.selectAll('text').attr('font-size', '9px').attr('fill', '#6b6b50'));

    // Legend
    const legend = d3.select(container)
      .append('div')
      .style('display', 'flex')
      .style('flex-wrap', 'wrap')
      .style('gap', '0.3rem 0.9rem')
      .style('margin-top', '0.5rem')
      .style('font-size', '0.78rem')
      .style('font-family', 'Arial, sans-serif');

    users.forEach(uid => {
      const item = legend.append('div')
        .style('display', 'flex')
        .style('align-items', 'center')
        .style('gap', '0.3rem');
      item.append('span')
        .style('display', 'inline-block')
        .style('width', '10px')
        .style('height', '10px')
        .style('background', colorOf(uid))
        .style('border-radius', '2px')
        .style('flex-shrink', '0');
      item.append('span')
        .style('color', '#6b6b50')
        .text(uid);
    });
  }
```

- [ ] **Step 3: Verify the dashboard HTML is valid (no syntax errors)**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
python -c "
from pathlib import Path
html = Path('remote-gateway/core/admin_dashboard.html').read_text()
assert 'function renderTimeline(data)' in html
assert 'd3.stack()' in html
assert 'PALETTE' in html
assert 'H      = 300' in html
print('OK')
"
```

Expected output: `OK`

- [ ] **Step 4: Start the server and visually verify**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
MCP_TRANSPORT=sse python remote-gateway/core/mcp_server.py &
# Open the admin dashboard in a browser and confirm:
# - The chart is taller
# - Bars are stacked and color-coded by user
# - Hovering a segment shows "YYYY-MM-DD — user: N calls"
# - A legend appears below the chart
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/jaronsander/main/inform/inform-gateway
pytest remote-gateway/tests/ -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "feat: stacked bar chart by user in activity timeline, taller chart height"
```
