"""
Decision Ledger tools — direct Supabase (PostgREST) implementation.

Company-strategy decisions/tasks live in agent-inform's Supabase `decisions`
table. This integration exposes read/mint/resolve over the gateway MCP so an
operator can manage decisions conversationally and scheduled agents can check
them off. The gateway holds Supabase creds but stores nothing — Supabase is the
single source of truth (church/state: gateway = access, not storage).

Follows the same pattern as tools/integrations/apollo.py (sync, lazy httpx).

Required env vars:
    SUPABASE_URL — e.g. https://abc.supabase.co
    SUPABASE_KEY — the same service key agent-inform uses
"""
from __future__ import annotations

import os
from typing import Any, Optional

# Compact field set returned to agents (keeps MCP context small).
_LIST_FIELDS = "id,title,detail,priority,kind,status,opened_at"


def _base() -> str:
    url = os.environ.get("SUPABASE_URL")
    if not url:
        raise ValueError("SUPABASE_URL environment variable is not set")
    return f"{url.rstrip('/')}/rest/v1/decisions"


def _headers(extra: Optional[dict] = None) -> dict[str, str]:
    key = os.environ.get("SUPABASE_KEY")
    if not key:
        raise ValueError("SUPABASE_KEY environment variable is not set")
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def list_open_decisions() -> dict[str, Any]:
    """List open + in-progress decisions, newest first.

    Returns the company-strategy decisions that still need attention — the
    "what's pending" view. Resolved/dropped decisions are excluded. Use this to
    answer "what decisions are open?" or to render a brief's pending list.

    Returns:
        Dict with 'decisions': list of {id, title, detail, priority, kind,
        status, opened_at}, newest first.
    """
    import httpx

    params = {
        "select": _LIST_FIELDS,
        "status": "in.(open,in_progress)",
        "order": "opened_at.desc",
    }
    with httpx.Client() as client:
        resp = client.get(_base(), headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        return {"decisions": resp.json()}


def upsert_decision(
    title: str,
    kind: str = "decision",
    detail: str = "",
    priority: str = "M",
    source: str = "",
) -> dict[str, Any]:
    """Mint a decision/task, deduped on case-insensitive title.

    If an active (non-dropped) decision with the same title already exists, this
    is a no-op that returns the existing row — re-running never duplicates. Use
    kind='task' for a concrete to-do, 'decision' for a strategic call.

    Args:
        title: Short decision title (the dedup key, case-insensitive).
        kind: 'decision' | 'task'. Default 'decision'.
        detail: Free-text context.
        priority: 'H' | 'M' | 'L'. Default 'M'.
        source: Who/what minted it (agent or note slug).

    Returns:
        Dict with 'decision': the created or existing row.
    """
    import httpx

    with httpx.Client() as client:
        # Dedup against active rows. ilike with no wildcards is a case-insensitive
        # exact match; httpx URL-encodes the value, so titles with special chars
        # (parens, '#', '/' — e.g. "Apollo/Wiza enrichment (#27)") match fine.
        # Mirrors agent-inform's supabase-py `.ilike("title", title)`.
        existing = client.get(
            _base(),
            headers=_headers(),
            params={
                "select": "*",
                "title": f"ilike.{title}",
                "status": "not.eq.dropped",
                "order": "opened_at.desc",
                "limit": "1",
            },
            timeout=30,
        )
        existing.raise_for_status()
        rows = existing.json()
        if rows:
            return {"decision": rows[0]}

        payload = {
            "kind": kind,
            "title": title,
            "detail": detail or None,
            "status": "open",
            "priority": priority,
            "signal_type": "manual",
            "source": source or None,
        }
        resp = client.post(
            _base(),
            headers=_headers({"Prefer": "return=representation"}),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"decision": data[0] if data else None}


def resolve_decision(
    decision_id: str, status: str = "resolved", resolution: str = ""
) -> dict[str, Any]:
    """Close or update a decision so it stops surfacing.

    status='resolved' when done, 'dropped' to abandon, 'in_progress' to mark
    started, 'open' to reopen. Terminal statuses stamp resolved_at. Use when an
    operator says "I finished X" or an agent completes a tracked task.

    Args:
        decision_id: The decision's UUID.
        status: 'resolved' | 'dropped' | 'in_progress' | 'open'. Default 'resolved'.
        resolution: Free-text note on how/why it closed.

    Returns:
        Dict with 'decision': the updated row.
    """
    import datetime as _dt

    import httpx

    payload: dict[str, Any] = {"status": status}
    if resolution:
        payload["resolution"] = resolution
    if status in ("resolved", "dropped"):
        payload["resolved_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()

    with httpx.Client() as client:
        resp = client.patch(
            _base(),
            headers=_headers({"Prefer": "return=representation"}),
            params={"id": f"eq.{decision_id}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"decision": data[0] if data else None}


def register(mcp: Any) -> None:
    """Register decision-ledger tools on the FastMCP server."""
    mcp.tool()(list_open_decisions)
    mcp.tool()(upsert_decision)
    mcp.tool()(resolve_decision)
