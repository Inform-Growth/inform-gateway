"""
Wiza Individual Reveal tool — person enrichment via LinkedIn URL.

Starts a Wiza reveal, polls until complete, and returns email, phone,
and LinkedIn profile data in a single blocking call.

Required env vars:
    WIZA_API_KEY — Wiza API key (Bearer token)
"""
from __future__ import annotations

import os
import time

from core.field_registry import registry
from typing import Any

_WIZA_BASE = "https://wiza.co/api"
_POLL_INTERVAL_S = 3.0
_MAX_POLL_ATTEMPTS = 10


def _headers() -> dict[str, str]:
    """Return Wiza API request headers using WIZA_API_KEY from env."""
    api_key = os.environ.get("WIZA_API_KEY")
    if not api_key:
        raise ValueError("WIZA_API_KEY environment variable is not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _start_reveal(linkedin_url: str) -> str:
    """POST to start a Wiza Individual Reveal. Returns the reveal ID.

    Args:
        linkedin_url: LinkedIn profile URL to enrich.

    Returns:
        Reveal ID string from the Wiza response.

    Raises:
        RuntimeError: On 400 bad request.
        PermissionError: On 401 invalid API key.
        RuntimeError: On 429 queue full.
    """
    import httpx

    with httpx.Client() as client:
        resp = client.post(
            f"{_WIZA_BASE}/individual_reveals",
            headers=_headers(),
            json={
                "individual_reveal": {
                    "profile_url": linkedin_url,
                    "enrichment_level": "full",
                }
            },
        )

    if resp.status_code == 400:
        raise RuntimeError(f"Wiza bad request: {resp.text}")
    if resp.status_code == 401:
        raise PermissionError("WIZA_API_KEY is invalid or disabled")
    if resp.status_code == 429:
        raise RuntimeError("Wiza queue full — try again later")
    resp.raise_for_status()

    return resp.json()["data"]["id"]


def _poll_reveal(reveal_id: str) -> dict[str, Any]:
    """Poll GET /individual_reveals/{id} until finished or failed.

    Polls every 3 seconds up to 10 attempts (30s total).

    Args:
        reveal_id: Reveal ID returned by _start_reveal.

    Returns:
        The finished reveal data dict.

    Raises:
        RuntimeError: If the reveal status is 'failed'.
        TimeoutError: If the reveal does not complete within 30s.
    """
    import httpx

    for _ in range(_MAX_POLL_ATTEMPTS):
        with httpx.Client() as client:
            resp = client.get(
                f"{_WIZA_BASE}/individual_reveals/{reveal_id}",
                headers=_headers(),
            )
        resp.raise_for_status()

        payload = resp.json().get("data", {})
        status = payload.get("status")

        if status == "finished":
            return payload
        if status == "failed":
            raise RuntimeError(f"Wiza reveal {reveal_id} failed")

        time.sleep(_POLL_INTERVAL_S)

    raise TimeoutError(
        f"Wiza reveal {reveal_id} did not complete within "
        f"{_MAX_POLL_ATTEMPTS * _POLL_INTERVAL_S:.0f}s"
    )


def wiza__enrich_person(linkedin_url: str) -> dict[str, Any]:
    """Enrich a person by LinkedIn URL using Wiza.

    Starts a Wiza Individual Reveal for the given LinkedIn profile URL,
    polls until enrichment is complete (up to 30s), and returns the person's
    email, mobile phone, and LinkedIn profile data.

    Uses enrichment_level 'full'. Credits are only deducted when data is found:
    2 credits for a valid email, 5 for a phone number, 1 for a LinkedIn match.

    Args:
        linkedin_url: The person's LinkedIn profile URL
            (e.g. https://www.linkedin.com/in/username).

    Returns:
        Dict with any of: name, title, linkedin_profile_url, email,
        email_status, mobile_phone, company_name, credits_used.
        Fields absent from the Wiza response are omitted.

    Raises:
        ValueError: If WIZA_API_KEY is not set.
        PermissionError: If the API key is invalid or disabled.
        RuntimeError: On 400/429 from Wiza, or if the reveal fails.
        TimeoutError: If enrichment does not complete within 30s.
    """
    reveal_id = _start_reveal(linkedin_url)
    payload = _poll_reveal(reveal_id)

    result: dict[str, Any] = {}

    for field in ("name", "title", "linkedin_profile_url", "email", "email_status", "mobile_phone"):
        val = payload.get(field)
        if val is not None:
            result[field] = val

    company = payload.get("company")
    if company:
        result["company_name"] = company

    credits_raw = payload.get("credits") or {}
    api_credits_raw = credits_raw.get("api_credits") or {}
    # credits_used is always returned — Wiza always includes a credits block,
    # and the field registry marks it nullable: false.
    result["credits_used"] = {
        "email": credits_raw.get("email_credits", 0),
        "phone": credits_raw.get("phone_credits", 0),
        "api": api_credits_raw.get("total", 0) if isinstance(api_credits_raw, dict) else 0,
    }

    validation = registry.validate_response("wiza", result)
    if not validation.valid:
        result["_field_validation"] = validation.summary()
    return result


def register(mcp: Any) -> None:
    """Register Wiza tools on the FastMCP server.

    Args:
        mcp: FastMCP server instance with telemetry patch already applied.
    """
    mcp.tool()(wiza__enrich_person)
