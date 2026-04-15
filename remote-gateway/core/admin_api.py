"""
Gateway Admin API — Starlette sub-app mounted at /admin.

All routes require ?token=<ADMIN_TOKEN>. The token is read from the
ADMIN_TOKEN environment variable; it defaults to "inform-admin-2026" for
local development.

Mount in mcp_server.py:
    from admin_api import create_admin_app
    Mount("/admin", app=create_admin_app(telemetry_instance))
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

_logger = logging.getLogger(__name__)

_DASHBOARD_HTML = Path(__file__).parent / "admin_dashboard.html"
_DEFAULT_TOKEN = "inform-admin-2026"

if not os.environ.get("ADMIN_TOKEN"):
    print(
        "[admin] WARNING: ADMIN_TOKEN env var not set — using insecure default token."
        " Set ADMIN_TOKEN in production.",
        flush=True,
    )


def _admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", _DEFAULT_TOKEN)


def _is_authorized(request: Request) -> bool:
    return request.query_params.get("token", "") == _admin_token()


def _forbidden() -> Response:
    return JSONResponse({"error": "forbidden — invalid admin token"}, status_code=403)


def create_admin_app(telemetry: Any, list_tools_fn: Any = None) -> Starlette:
    """Return a Starlette sub-app with all admin routes bound to telemetry.

    Args:
        telemetry: A TelemetryStore instance.
        list_tools_fn: Optional async callable that returns a list of registered
            tools (each with .name and .description). Used by GET /api/tools.
            When omitted, that endpoint returns 503.
    """

    async def dashboard(request: Request) -> Response:
        if not _is_authorized(request):
            return HTMLResponse(
                "<h1>403 Forbidden</h1><p>Invalid or missing admin token.</p>",
                status_code=403,
            )
        if not _DASHBOARD_HTML.exists():
            return HTMLResponse("<h1>Admin dashboard not found.</h1>", status_code=500)
        return HTMLResponse(_DASHBOARD_HTML.read_text())

    async def api_stats(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        return JSONResponse(telemetry.stats())

    async def api_sessions(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        session_data = telemetry.session_usage(limit=200)
        flow_data = telemetry.user_flow_analysis(limit=500)
        sankey = _build_sankey(flow_data.get("common_flows", []))
        return JSONResponse({
            "sankey": sankey,
            "user_breakdown": session_data.get("user_breakdown", {}),
            "recent_sequences": session_data.get("recent_sequences", {}),
        })

    async def api_users_list(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        return JSONResponse(telemetry.list_users())

    async def api_users_create(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        user_id = (body.get("user_id") or "").strip()
        if not user_id:
            return JSONResponse({"error": "user_id is required"}, status_code=400)
        key = telemetry.add_api_key(user_id)
        return JSONResponse({"user_id": user_id, "key": key}, status_code=201)

    async def api_users_delete(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        deleted = telemetry.delete_user(user_id)
        if deleted == 0:
            return JSONResponse({"error": "user not found"}, status_code=404)
        return JSONResponse({"deleted": deleted, "user_id": user_id})

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
                tool_names = sorted(set(t.name for t in tools) | explicit.keys())
            except Exception as exc:
                _logger.warning(
                    "list_tools_fn failed in api_permissions_get, "
                    "falling back to explicit rows: %s",
                    exc,
                )
                tool_names = sorted(explicit.keys())
        else:
            tool_names = sorted(explicit.keys())

        permissions = [
            {"tool_name": name, "enabled": explicit.get(name, True)}
            for name in tool_names
        ]
        return JSONResponse({"user_id": user_id, "permissions": permissions})

    async def api_timeline(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        try:
            days = int(request.query_params.get("days", "30"))
        except ValueError:
            days = 30
        return JSONResponse(telemetry.daily_activity_by_user(days=days))

    async def api_tools(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        if list_tools_fn is None:
            return JSONResponse({"error": "tool listing not configured"}, status_code=503)
        tools = await list_tools_fn()
        return JSONResponse([
            {"name": t.name, "description": t.description or ""}
            for t in tools
        ])

    async def api_logs(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        try:
            limit = max(1, min(int(request.query_params.get("limit", "100")), 1000))
            offset = max(0, int(request.query_params.get("offset", "0")))
        except ValueError:
            limit, offset = 100, 0
        tool = request.query_params.get("tool") or None
        user = request.query_params.get("user") or None
        success_param = request.query_params.get("success")
        success: bool | None = None
        if success_param == "true":
            success = True
        elif success_param == "false":
            success = False
        error_type = request.query_params.get("error_type") or None
        return JSONResponse(
            telemetry.raw_logs(
                limit=limit,
                offset=offset,
                tool_name=tool,
                user_id=user,
                success=success,
                error_type=error_type,
            )
        )

    async def api_permissions_set(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        tool_name = request.path_params["tool_name"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if "enabled" not in body:
            return JSONResponse({"error": "enabled (bool) is required"}, status_code=400)
        telemetry.set_tool_permission(user_id, tool_name, bool(body["enabled"]))
        return JSONResponse({"ok": True, "user_id": user_id, "tool_name": tool_name,
                             "enabled": bool(body["enabled"])})

    routes = [
        Route("/", dashboard),
        Route("/api/stats", api_stats),
        Route("/api/sessions", api_sessions),
        Route("/api/users", api_users_list, methods=["GET"]),
        Route("/api/users", api_users_create, methods=["POST"]),
        Route("/api/users/{user_id}", api_users_delete, methods=["DELETE"]),
        Route("/api/permissions/{user_id}", api_permissions_get, methods=["GET"]),
        Route("/api/permissions/{user_id}/{tool_name:path}", api_permissions_set, methods=["PUT"]),
        Route("/api/timeline", api_timeline),
        Route("/api/tools", api_tools),
        Route("/api/logs", api_logs),
    ]

    return Starlette(routes=routes)


def _build_sankey(common_flows: list[dict]) -> dict:
    """Convert user_flow_analysis common_flows into D3-sankey nodes/links format.

    Only includes pair-level flows (sequence with exactly one "->").
    Bidirectional pairs (A→B and B→A) are resolved by keeping the dominant
    direction (higher count); this prevents d3-sankey circular-link errors.

    Args:
        common_flows: List of {"sequence": "tool_a -> tool_b", "count": N} dicts.

    Returns:
        Dict with "nodes" (list of {id, name}) and "links" (list of {source, target, value}).
    """
    # Accumulate counts per directed pair, collapsing duplicates.
    pair_counts: dict[tuple[str, str], int] = {}

    for item in common_flows:
        parts = item["sequence"].split(" -> ")
        if len(parts) != 2:
            continue  # skip triplets to avoid double-counting
        src, tgt = parts
        if src == tgt:
            continue  # skip self-loops — d3-sankey rejects circular links
        key = (src, tgt)
        pair_counts[key] = pair_counts.get(key, 0) + item["count"]

    # Resolve bidirectional pairs: keep only the dominant direction.
    resolved: dict[tuple[str, str], int] = {}
    for (src, tgt), count in pair_counts.items():
        reverse = (tgt, src)
        if reverse in resolved:
            # Reverse already won — skip this direction.
            continue
        rev_count = pair_counts.get(reverse, 0)
        if count >= rev_count:
            resolved[(src, tgt)] = count
        # else: reverse will be picked up when its key is iterated

    node_set: set[str] = set()
    links: list[dict] = []
    for (src, tgt), count in resolved.items():
        node_set.add(src)
        node_set.add(tgt)
        links.append({"source": src, "target": tgt, "value": count})

    nodes = [{"id": name, "name": name} for name in sorted(node_set)]
    return {"nodes": nodes, "links": links}
