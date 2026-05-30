"""Tests for embedding provider selection (OpenRouter vs OpenAI)."""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


from embeddings import _make_client  # noqa: E402


def test_make_client_returns_none_when_no_keys(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client, model = _make_client()
    assert client is None
    assert model is None


def test_make_client_uses_openrouter_base_url_when_key_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client, model = _make_client()
    assert client is not None
    assert "openrouter.ai" in str(client.base_url)


def test_make_client_prefers_openrouter_over_openai(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    client, model = _make_client()
    assert "openrouter.ai" in str(client.base_url)


def test_make_client_falls_back_to_openai_when_no_openrouter(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    client, model = _make_client()
    assert client is not None
    assert "openrouter.ai" not in str(client.base_url)


def test_make_client_returns_default_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    _, model = _make_client()
    assert model == "text-embedding-3-small"


def test_make_client_respects_embed_model_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("EMBED_MODEL", "text-embedding-3-large")
    _, model = _make_client()
    assert model == "text-embedding-3-large"


def test_embed_dims_defaults_to_1536(monkeypatch):
    monkeypatch.delenv("EMBED_DIMS", raising=False)
    from embeddings import embed_dims
    assert embed_dims() == 1536


def test_embed_dims_reads_from_env(monkeypatch):
    monkeypatch.setenv("EMBED_DIMS", "4096")
    from embeddings import embed_dims
    assert embed_dims() == 4096


def test_embed_text_returns_none_without_any_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from embeddings import embed_text, _embed_cached
    _embed_cached.cache_clear()
    result = embed_text("test text")
    assert result is None
