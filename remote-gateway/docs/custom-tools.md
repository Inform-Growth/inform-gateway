# Adding a custom Python tool

For when you need a tool that doesn't exist as an upstream MCP — bespoke business logic, a thin wrapper around an internal API, or an aggregation across multiple integrations. Write it as a Python module under `remote-gateway/tools/`, register it from `core/mcp_server.py`, and the gateway gives you telemetry, gates, and task-id wrapping for free.

## Module layout

Create `remote-gateway/tools/<integration>.py` with a `register(mcp, ...)` function:

```python
"""Weather forecast tools — example custom integration."""
from __future__ import annotations

import os
from typing import Any

import httpx


async def weather__forecast(city: str, days: int = 3) -> dict[str, Any]:
    """Return a multi-day weather forecast for a city.

    Args:
        city: City name, e.g. "Vancouver".
        days: Number of forecast days (1–10). Defaults to 3.

    Returns:
        Dict with city, units, and a list of daily forecasts.
    """
    api_key = os.environ.get("WEATHER_API_KEY")
    if not api_key:
        return {"error": "WEATHER_API_KEY env var not set"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.example.com/forecast",
            params={"city": city, "days": days, "key": api_key},
        )
        resp.raise_for_status()
        return resp.json()


def register(mcp: Any) -> None:
    """Register weather tools on the FastMCP server instance."""
    mcp.tool()(weather__forecast)
```

## Wire it into mcp_server.py

In `remote-gateway/core/mcp_server.py`, after the existing `from tools._core import …` block:

```python
from tools import weather as _weather_tools  # noqa: E402
```

And after the existing `_xyz_tools.register(...)` calls:

```python
_weather_tools.register(mcp)
```

That's it. The next gateway boot exposes `weather__forecast` to all authorized operators.

## What you get for free

The gateway monkey-patches `mcp.tool()` (via `_tracked_mcp_tool` in `mcp_server.py`) so every tool registered through it gets:

- **Telemetry**: timing, success/failure, request_id, user_id, response size — all written to SQLite. No code in your tool needed.
- **Auth gating**: each tool call resolves a user_id from the API key and checks the `tool_permissions` table. Per-user disable, global disable (`user_id="*"`), and the init gate (uninitialized orgs are redirected to setup) all work without any code in your tool.
- **task_id injection**: the wrapper injects an optional `task_id` parameter into your tool's signature. Agents pass it on every call to attribute work to a declared task. If your tool wants to read `task_id` (e.g. for cross-tool linking), just declare it as a parameter; otherwise the wrapper pops it before calling you.

You don't need to import `_telemetry` or call `record(...)`. Don't reimplement any of this.

## Tool naming convention

Use the prefix `<integration>__<verb_or_noun>` (double underscore) — same as proxied tools. The prefix groups tools in `tools/list` and makes it easy for agents to filter by integration.

Examples: `weather__forecast`, `slack__post_message`, `pricing__quote`.

## Field registry (optional, recommended)

If your tool returns structured data with named fields, document those fields in `remote-gateway/context/fields/<integration>.yaml` and wrap the response with `validated()`. The registry surfaces drift when the upstream changes its schema.

```python
from field_registry import registry

async def weather__forecast(city: str, days: int = 3) -> dict[str, Any]:
    raw = await _fetch_forecast(city, days)
    result = registry.validate_response("weather", raw)
    if not result.valid:
        # log drift but still return the data — never block on validation
        print(result.summary())
    return raw
```

The YAML schema lives at `remote-gateway/context/fields/weather.yaml`. Use `remote-gateway/context/fields/_template.yaml` as a starting point.

## Tests

Tests for tool modules live in `remote-gateway/tests/test_<integration>.py`. The existing tests (e.g. `test_notes.py`, `test_skill_manager.py`) show the patterns:

- Import the module under test directly (skip the FastMCP server scaffolding).
- For tools that need a `TelemetryStore`, use `pytest.fixture` with `tmp_path / "test.db"`.
- For tools that hit external APIs, mock `httpx` (or whatever client you use) — never let CI hit a real API.

## Read-only by default

The gateway's house style: tools are read-only unless explicitly granted write permission. If your tool mutates external state (creates a record, sends a message), call it out in the docstring and require a write-scoped permission via `tool_permissions`. See `core/admin_dashboard.html` for the per-user toggle UI.
