"""Embedding utilities for semantic skill matching.

Used by skill_manager (embed on write) and task_manager (suggest on declare_intent).
All functions are fail-open — callers should catch exceptions or rely on None returns.
"""
from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

SCORE_FLOOR: float = 0.35
"""Minimum hybrid score for a skill to appear in suggested_skills."""

_EMBED_MODEL = "text-embedding-3-small"
_EMBED_DIMS_DEFAULT = 1536


def embed_dims() -> int:
    """Return the configured embedding dimension (EMBED_DIMS env var, default 1536)."""
    return int(os.environ.get("EMBED_DIMS", str(_EMBED_DIMS_DEFAULT)))
_COSINE_WEIGHT = 0.8
_KEYWORD_WEIGHT = 0.2


def skill_embed_source(name: str, description: str) -> str:
    """Canonical source text for a skill's embedding."""
    return f"{name}\n{description}"


def skill_embed_hash(source: str) -> str:
    """SHA-256 of source text — used to skip re-embedding unchanged skills."""
    return hashlib.sha256(source.encode()).hexdigest()


def keyword_overlap(query: str, skill_text: str) -> float:
    """Word-level Jaccard similarity between query and skill text."""
    q_words = set(query.lower().split())
    s_words = set(skill_text.lower().split())
    if not q_words or not s_words:
        return 0.0
    return len(q_words & s_words) / len(q_words | s_words)


def hybrid_score(cosine: float, query: str, skill_text: str) -> float:
    """Weighted combination of cosine similarity and keyword overlap."""
    kw = keyword_overlap(query, skill_text)
    return _COSINE_WEIGHT * cosine + _KEYWORD_WEIGHT * kw


def _make_client() -> tuple[Any, str] | tuple[None, None]:
    """Return a configured (OpenAI-compatible client, model) pair, or (None, None).

    Provider resolution order:
    1. OpenRouter — ``OPENROUTER_API_KEY`` + ``https://openrouter.ai/api/v1``
    2. OpenAI     — ``OPENAI_API_KEY``

    Model defaults to ``EMBED_MODEL`` env var, then ``text-embedding-3-small``.
    """
    from openai import OpenAI  # noqa: PLC0415

    model = os.environ.get("EMBED_MODEL", _EMBED_MODEL)

    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1"), model

    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAI(api_key=key), model

    return None, None


@lru_cache(maxsize=256)
def _embed_cached(text: str) -> list[float] | None:
    """Embed text, cached by exact string. Provider resolved from env at call time."""
    client, model = _make_client()
    if client is None:
        return None
    try:
        response = client.embeddings.create(input=text, model=model)
        return response.data[0].embedding
    except Exception as exc:
        logger.warning("Embedding failed: %s", exc)
        return None


def embed_text(text: str) -> list[float] | None:
    """Embed text. Returns None when no API key is configured or on any error."""
    return _embed_cached(text)
