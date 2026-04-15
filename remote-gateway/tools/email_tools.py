"""
Email utility tools — plain text normalization for clean email rendering.

Gmail renders hard newlines literally, causing mid-sentence line breaks when
LLMs word-wrap their output at ~80 chars. normalize_email_body fixes this by
collapsing single newlines within paragraphs into spaces while preserving
intentional paragraph breaks (double newlines).
"""
from __future__ import annotations

import re
from typing import Any


def normalize_email_body(body: str) -> dict[str, Any]:
    """Normalize a plain-text email body for clean rendering in Gmail.

    LLMs naturally word-wrap output at ~80 characters, inserting hard newlines
    mid-sentence. Gmail renders these literally, making emails look automated
    and oddly formatted. This tool collapses single newlines within paragraphs
    into spaces while preserving intentional paragraph breaks (double newlines).

    Use this tool on the email draft before calling gmail__send_email.

    Args:
        body: Raw email body text, potentially containing hard line breaks
            within sentences or paragraphs.

    Returns:
        Dict with 'body' key containing the normalized text, ready to pass
        to gmail__send_email.

    Example:
        Input:  "Hey Sarah,\\n\\nYour work on RevOps tooling\\ncaught my attention."
        Output: "Hey Sarah,\\n\\nYour work on RevOps tooling caught my attention."
    """
    # Normalize line endings
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    # Split into paragraphs on double (or more) newlines
    paragraphs = re.split(r"\n{2,}", body)
    # Within each paragraph, collapse single newlines to spaces
    paragraphs = [p.replace("\n", " ").strip() for p in paragraphs]
    # Rejoin, dropping any empty paragraphs
    normalized = "\n\n".join(p for p in paragraphs if p)
    return {"body": normalized}


def register(mcp: Any) -> None:
    """Register email utility tools on the FastMCP server.

    Args:
        mcp: FastMCP server instance with telemetry patch already applied.
    """
    mcp.tool()(normalize_email_body)
