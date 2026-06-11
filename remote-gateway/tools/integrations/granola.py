"""
Granola meeting notes tools — read-only access to the Granola REST API.

Lists meetings, fetches AI summaries, and pulls transcripts (flattened
server-side into readable dialogue lines) so agents can ground work in
meeting context.

Note: the Granola API only returns notes that have a finished AI summary
and transcript — notes still processing or never summarized are invisible.

Required env vars:
    GRANOLA_API_KEY — Granola personal API key (Bearer token, starts with grn_)
"""
from __future__ import annotations

import os
from typing import Any

from core.field_registry import registry

_GRANOLA_BASE = "https://public-api.granola.ai/v1"
_MAX_PAGE_SIZE = 30


def _headers() -> dict[str, str]:
    """Return Granola API request headers using GRANOLA_API_KEY from env."""
    api_key = os.environ.get("GRANOLA_API_KEY")
    if not api_key:
        raise ValueError(
            "GRANOLA_API_KEY environment variable is not set "
            "(generate a personal key in the Granola desktop app: Settings > API)"
        )
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET a Granola API path and return the parsed JSON body.

    Args:
        path: API path starting with "/" (e.g. "/notes").
        params: Optional query parameters.

    Returns:
        Parsed JSON response dict.

    Raises:
        ValueError: If GRANOLA_API_KEY is not set.
        PermissionError: On 401 invalid/expired API key.
        RuntimeError: On 400 bad request or 404 not found.
    """
    import httpx

    with httpx.Client() as client:
        resp = client.get(
            f"{_GRANOLA_BASE}{path}",
            headers=_headers(),
            params=params or {},
        )

    if resp.status_code == 400:
        raise RuntimeError(f"Granola bad request: {resp.text}")
    if resp.status_code == 401:
        raise PermissionError("GRANOLA_API_KEY is invalid or expired")
    if resp.status_code == 404:
        raise RuntimeError(f"Granola resource not found: {path}")
    resp.raise_for_status()
    return resp.json()


def _validated(result: dict[str, Any]) -> dict[str, Any]:
    """Attach _field_validation when the result drifts from the granola schema."""
    validation = registry.validate_response("granola", result)
    if not validation.valid:
        result["_field_validation"] = validation.summary()
    return result
