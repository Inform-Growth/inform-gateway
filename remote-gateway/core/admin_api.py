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

import contextlib
import logging
import os
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from telemetry import INTENT_NEVER_REQUIRED, VALID_ROLES

_logger = logging.getLogger(__name__)

DIST = Path(__file__).parent.parent / "admin-ui" / "dist"
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


def _get_primary_org_id(telemetry: Any) -> str:
    """Return the first initialized org_id, falling back to 'default'."""
    return telemetry.get_primary_initialized_org() or "default"


def create_admin_app(telemetry: Any, list_tools_fn: Any = None) -> Starlette:
    """Return a Starlette sub-app with all admin routes bound to telemetry.

    Args:
        telemetry: A TelemetryStore instance.
        list_tools_fn: Optional async callable that returns a list of registered
            tools (each with .name and .description). Used by GET /api/tools.
            When omitted, that endpoint returns 503.
    """

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
        try:
            key = telemetry.add_api_key(user_id)
        except Exception as exc:
            _logger.exception("Failed to create user %r", user_id)
            return JSONResponse({"error": f"failed to create user: {exc}"}, status_code=500)
        return JSONResponse({"user_id": user_id, "key": key}, status_code=201)

    async def api_users_delete(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        deleted = telemetry.delete_user(user_id)
        if deleted == 0:
            return JSONResponse({"error": "user not found"}, status_code=404)
        return JSONResponse({"deleted": deleted, "user_id": user_id})

    async def api_user_role_set(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json body"}, status_code=400)
        role = body.get("role")
        if role not in VALID_ROLES:
            return JSONResponse(
                {"error": f"role must be one of {sorted(VALID_ROLES)}"},
                status_code=400,
            )
        telemetry.set_user_role(user_id, role)
        return JSONResponse({"ok": True, "user_id": user_id, "role": role})

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
        task_id = request.query_params.get("task_id") or None
        return JSONResponse(
            telemetry.raw_logs(
                limit=limit,
                offset=offset,
                tool_name=tool,
                user_id=user,
                success=success,
                error_type=error_type,
                task_id=task_id,
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

    async def api_skill_permissions_get(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        org_id = _get_primary_org_id(telemetry)
        explicit = {
            row["skill_name"]: row["enabled"]
            for row in telemetry.get_skill_permissions(user_id)
        }
        known = {s["name"] for s in telemetry.list_skills(org_id)}
        skill_names = sorted(known | explicit.keys())
        permissions = [
            {"skill_name": name, "enabled": explicit.get(name, True)}
            for name in skill_names
        ]
        return JSONResponse({"user_id": user_id, "permissions": permissions})

    async def api_skill_permissions_set(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        skill_name = request.path_params["skill_name"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if "enabled" not in body:
            return JSONResponse({"error": "enabled (bool) is required"}, status_code=400)
        telemetry.set_skill_permission(user_id, skill_name, bool(body["enabled"]))
        return JSONResponse({"ok": True, "user_id": user_id, "skill_name": skill_name,
                             "enabled": bool(body["enabled"])})

    async def api_tool_intent_get(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        explicit = {
            row["tool_name"]: row["requires_intent"]
            for row in telemetry.get_tool_intent_overrides(user_id)
        }
        tool_names = set(INTENT_NEVER_REQUIRED) | explicit.keys()
        if list_tools_fn is not None:
            try:
                tools = await list_tools_fn()
                tool_names |= {t.name for t in tools}
            except Exception:
                pass
        overrides = []
        for name in sorted(tool_names):
            locked = name in INTENT_NEVER_REQUIRED
            if locked:
                requires_intent = False
            elif name in explicit:
                requires_intent = bool(explicit[name])
            else:
                # Reflect default resolution
                from mcp_server import _tool_requires_intent
                requires_intent = _tool_requires_intent(user_id, name)
            overrides.append({
                "tool_name": name,
                "requires_intent": requires_intent,
                "locked": locked,
                "explicit": name in explicit,
            })
        return JSONResponse({"user_id": user_id, "overrides": overrides})

    async def api_tool_intent_set(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        tool_name = request.path_params["tool_name"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if "requires_intent" not in body:
            return JSONResponse({"error": "requires_intent (bool) is required"},
                                status_code=400)
        try:
            telemetry.set_tool_intent_override(user_id, tool_name,
                                               bool(body["requires_intent"]))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "user_id": user_id, "tool_name": tool_name,
                             "requires_intent": bool(body["requires_intent"])})

    async def api_tool_intent_delete(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        user_id = request.path_params["user_id"]
        tool_name = request.path_params["tool_name"]
        telemetry.clear_tool_intent_override(user_id, tool_name)
        return JSONResponse({"ok": True, "cleared": True,
                             "user_id": user_id, "tool_name": tool_name})

    async def api_org_profile_get(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        profile = telemetry.get_org_profile(org_id)
        initialized = telemetry.is_initialized(org_id)
        return JSONResponse({"org_id": org_id, "initialized": initialized, "profile": profile})

    async def api_org_profile_update(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
        updated = telemetry.update_org_profile(org_id, body)
        return JSONResponse({"org_id": org_id, "profile": updated})

    async def api_skills_list(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        return JSONResponse(telemetry.list_skills(org_id))

    async def api_skills_create(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        for required in ("name", "description", "prompt_template"):
            if not body.get(required):
                return JSONResponse({"error": f"{required} is required"}, status_code=400)
        skill = telemetry.create_skill(
            org_id, body["name"], body["description"], body["prompt_template"]
        )
        return JSONResponse(skill, status_code=201)

    async def api_skills_update(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        name = request.path_params["name"]
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        fields = {k: v for k, v in body.items() if k in ("description", "prompt_template")}
        result = telemetry.update_skill(org_id, name, **fields)
        if result is None:
            return JSONResponse(
                {"error": f"skill '{name}' not found or is a system skill"}, status_code=404
            )
        return JSONResponse(result)

    async def api_skills_delete(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        name = request.path_params["name"]
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        deleted = telemetry.delete_skill(org_id, name)
        if not deleted:
            return JSONResponse(
                {"error": f"skill '{name}' not found or is a system skill"}, status_code=404
            )
        return JSONResponse({"deleted": name})

    async def api_hints_list(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        return JSONResponse(telemetry.list_tool_hints(org_id))

    async def api_hints_upsert(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        tool_name = request.path_params["tool_name"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        hint = telemetry.upsert_tool_hint(
            org_id,
            tool_name,
            interpretation_hint=body.get("interpretation_hint"),
            usage_rules=body.get("usage_rules"),
            data_sensitivity=body.get("data_sensitivity", "internal"),
        )
        return JSONResponse(hint)

    async def api_tasks(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        org_id = request.query_params.get("org_id") or _get_primary_org_id(telemetry)
        status = request.query_params.get("status") or None
        try:
            limit = max(1, min(int(request.query_params.get("limit", "100")), 500))
        except ValueError:
            limit = 100
        from_ts: float | None = None
        to_ts: float | None = None
        if "from" in request.query_params:
            with contextlib.suppress(ValueError):
                from_ts = float(request.query_params["from"])
        if "to" in request.query_params:
            with contextlib.suppress(ValueError):
                to_ts = float(request.query_params["to"])
        exclude_process = request.query_params.get("exclude_process", "").lower() == "true"
        tasks = telemetry.list_tasks_for_org(
            org_id,
            status=status,
            limit=limit,
            from_ts=from_ts,
            to_ts=to_ts,
            exclude_process=exclude_process,
        )
        return JSONResponse({"org_id": org_id, "tasks": tasks, "count": len(tasks)})

    async def _serve_spa(request: Request) -> Response:
        if not _is_authorized(request):
            return _forbidden()
        index = DIST / "index.html"
        if not index.exists():
            return HTMLResponse(
                "<h1>admin-ui not built</h1>"
                "<p>Run <code>cd remote-gateway/admin-ui &amp;&amp; npm run build</code> "
                "or use <code>./dev.sh</code> for development.</p>",
                status_code=503,
            )
        return FileResponse(index)

    asset_routes: list[Mount] = []
    if (DIST / "assets").exists():
        asset_routes.append(
            Mount("/assets", app=StaticFiles(directory=DIST / "assets"), name="admin-assets")
        )

    routes = [
        Route("/api/stats", api_stats),
        Route("/api/sessions", api_sessions),
        Route("/api/users", api_users_list, methods=["GET"]),
        Route("/api/users", api_users_create, methods=["POST"]),
        Route("/api/users/{user_id}", api_users_delete, methods=["DELETE"]),
        Route("/api/users/{user_id}/role", api_user_role_set, methods=["PUT"]),
        Route("/api/permissions/{user_id}", api_permissions_get, methods=["GET"]),
        Route("/api/permissions/{user_id}/{tool_name:path}", api_permissions_set, methods=["PUT"]),
        Route("/api/skill-permissions/{user_id}", api_skill_permissions_get, methods=["GET"]),
        Route("/api/skill-permissions/{user_id}/{skill_name:path}",
              api_skill_permissions_set, methods=["PUT"]),
        Route("/api/tool-intent/{user_id}", api_tool_intent_get, methods=["GET"]),
        Route("/api/tool-intent/{user_id}/{tool_name:path}",
              api_tool_intent_set, methods=["PUT"]),
        Route("/api/tool-intent/{user_id}/{tool_name:path}",
              api_tool_intent_delete, methods=["DELETE"]),
        Route("/api/timeline", api_timeline),
        Route("/api/tools", api_tools),
        Route("/api/logs", api_logs),
        Route("/api/org-profile", api_org_profile_get, methods=["GET"]),
        Route("/api/org-profile", api_org_profile_update, methods=["PUT"]),
        Route("/api/skills", api_skills_list, methods=["GET"]),
        Route("/api/skills", api_skills_create, methods=["POST"]),
        Route("/api/skills/{name}", api_skills_update, methods=["PUT"]),
        Route("/api/skills/{name}", api_skills_delete, methods=["DELETE"]),
        Route("/api/tool-hints", api_hints_list, methods=["GET"]),
        Route("/api/tool-hints/{tool_name:path}", api_hints_upsert, methods=["PUT"]),
        Route("/api/tasks", api_tasks, methods=["GET"]),
        *asset_routes,
        Route("/{path:path}", _serve_spa),  # SPA catch-all — MUST be last
    ]

    return Starlette(routes=routes)


def _remove_cycles(edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Return edges with back-edges removed so the graph is a DAG.

    Uses iterative DFS. When a back edge (edge to an in-progress ancestor) is
    found it is dropped. This prevents recharts' Sankey layout — which does an
    unbounded depth-first traversal — from entering infinite recursion.
    """
    from collections import defaultdict

    adj: dict[str, list[str]] = defaultdict(list)
    for src, tgt in edges:
        adj[src].append(tgt)

    visited: set[str] = set()
    in_stack: set[str] = set()
    back_edges: set[tuple[str, str]] = set()
    all_nodes = {n for pair in edges for n in pair}

    for start in all_nodes:
        if start in visited:
            continue
        visited.add(start)
        in_stack.add(start)
        stack: list[tuple[str, any]] = [(start, iter(adj[start]))]
        while stack:
            node, neighbors = stack[-1]
            try:
                neighbor = next(neighbors)
                if neighbor not in visited:
                    visited.add(neighbor)
                    in_stack.add(neighbor)
                    stack.append((neighbor, iter(adj[neighbor])))
                elif neighbor in in_stack:
                    back_edges.add((node, neighbor))
            except StopIteration:
                in_stack.discard(node)
                stack.pop()

    return [(src, tgt) for src, tgt in edges if (src, tgt) not in back_edges]


def _build_sankey(common_flows: list[dict]) -> dict:
    """Convert user_flow_analysis common_flows into D3-sankey nodes/links format.

    Only includes pair-level flows (sequence with exactly one "->").
    Bidirectional pairs (A→B and B→A) are resolved by keeping the dominant
    direction (higher count). Any remaining indirect cycles (A→B→C→A) are
    broken by _remove_cycles before the data reaches the client.

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

    # Break any remaining indirect cycles (e.g. A→B→C→A).
    safe_edges = _remove_cycles(list(resolved.keys()))
    safe_set = set(safe_edges)

    node_set: set[str] = set()
    links: list[dict] = []
    for (src, tgt), count in resolved.items():
        if (src, tgt) not in safe_set:
            continue
        node_set.add(src)
        node_set.add(tgt)
        links.append({"source": src, "target": tgt, "value": count})

    nodes = [{"id": name, "name": name} for name in sorted(node_set)]
    return {"nodes": nodes, "links": links}
