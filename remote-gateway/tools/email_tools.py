"""
Email utility tools — HTML conversion for clean email rendering.

Gmail's SMTP layer folds plain-text lines at ~78 characters regardless of
what is sent, causing mid-sentence line breaks. normalize_email_body converts
the draft to HTML so Gmail handles word-wrapping on the receiving end and
never inserts hard breaks mid-sentence.
"""
from __future__ import annotations

import re
from typing import Any


def normalize_email_body(body: str) -> dict[str, Any]:
    """Convert a plain-text email draft to HTML for clean rendering in Gmail.

    Gmail's SMTP layer folds plain-text lines at ~78 characters, inserting
    hard line breaks mid-sentence regardless of what the sender intended.
    This tool converts the draft to HTML so Gmail handles word-wrapping on
    the receiving end — no mid-sentence breaks, no formatting artifacts.

    Each paragraph (separated by a blank line) becomes a <p> element.
    Single newlines within a paragraph are collapsed to a space first.
    URLs are left as-is (Gmail auto-links them in HTML mode).

    Use this tool on the email draft before calling gmail__send_email.
    Pass the returned 'body' value directly to gmail__send_email's body field.

    Args:
        body: Raw email body text with paragraphs separated by blank lines.

    Returns:
        Dict with 'body' key containing the HTML string, ready to pass
        to gmail__send_email.

    Example:
        Input:  "Hey Sarah,\\n\\nYour work on RevOps tooling\\ncaught my attention."
        Output: "<p>Hey Sarah,</p><p>Your work on RevOps tooling caught my attention.</p>"
    """
    # Normalize line endings
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    # Split into paragraphs on double (or more) newlines
    paragraphs = re.split(r"\n{2,}", body)
    # Within each paragraph, collapse single newlines to spaces then strip
    paragraphs = [p.replace("\n", " ").strip() for p in paragraphs]
    # Wrap each non-empty paragraph in <p> tags
    html_parts = [f"<p>{p}</p>" for p in paragraphs if p]
    return {"body": "".join(html_parts)}


def register(mcp: Any) -> None:
    """Register email utility tools on the FastMCP server.

    Args:
        mcp: FastMCP server instance with telemetry patch already applied.
    """
    mcp.tool()(normalize_email_body)
