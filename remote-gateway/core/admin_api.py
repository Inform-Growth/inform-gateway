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

import os
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

_DASHBOARD_HTML = Path(__file__).parent / "admin_dashboard.html"
_DEFAULT_TOKEN = "inform-admin-2026"


def _admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", _DEFAULT_TOKEN)


def _is_authorized(request: Request) -> bool:
    return request.query_params.get("token", "") == _admin_token()


def _forbidden() -> Response:
    return JSONResponse({"error": "forbidden — invalid admin token"}, status_code=403)


def create_admin_app(telemetry: Any) -> Starlette:
    """Return a Starlette sub-app with all admin routes bound to telemetry.

    Args:
        telemetry: A TelemetryStore instance.
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
        perms = telemetry.get_tool_permissions(user_id)
        return JSONResponse({"user_id": user_id, "permissions": perms})

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
    ]

    return Starlette(routes=routes)


def _build_sankey(common_flows: list[dict]) -> dict:
    """Convert user_flow_analysis common_flows into D3-sankey nodes/links format.

    Only includes pair-level flows (sequence with exactly one "->").

    Args:
        common_flows: List of {"sequence": "tool_a -> tool_b", "count": N} dicts.

    Returns:
        Dict with "nodes" (list of {id, name}) and "links" (list of {source, target, value}).
    """
    node_set: set[str] = set()
    links: list[dict] = []

    for item in common_flows:
        parts = item["sequence"].split(" -> ")
        if len(parts) != 2:
            continue  # skip triplets to avoid double-counting
        src, tgt = parts
        node_set.add(src)
        node_set.add(tgt)
        links.append({"source": src, "target": tgt, "value": item["count"]})

    nodes = [{"id": name, "name": name} for name in sorted(node_set)]
    return {"nodes": nodes, "links": links}
