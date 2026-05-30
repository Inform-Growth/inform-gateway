"""Tests for on-deploy skill embedding backfill."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.modules.pop("telemetry", None)


# ------------------------------------------------------------------
# get_skills_without_embedding
# ------------------------------------------------------------------

def test_get_skills_without_embedding_returns_empty_without_pgvector(store):
    """No pgvector in test env → always returns empty list."""
    result = store.get_skills_without_embedding()
    assert result == []


# ------------------------------------------------------------------
# backfill_skill_embeddings — no-op cases
# ------------------------------------------------------------------

def test_backfill_returns_zero_counts_without_pgvector(store):
    """pgvector not available → no-op, zero counts."""
    calls = []
    result = store.backfill_skill_embeddings(embed_fn=lambda t: calls.append(t) or [0.1] * 1536)
    assert result == {"embedded": 0, "skipped": 0, "failed": 0}
    assert len(calls) == 0


def test_backfill_returns_zero_when_no_skills_need_embedding(store):
    """No skills without embeddings → zero counts, embed_fn never called."""
    calls = []

    with patch.object(store, "get_skills_without_embedding", return_value=[]):
        result = store.backfill_skill_embeddings(embed_fn=lambda t: calls.append(t) or [0.1] * 1536)

    assert result == {"embedded": 0, "skipped": 0, "failed": 0}
    assert len(calls) == 0


# ------------------------------------------------------------------
# backfill_skill_embeddings — happy path
# ------------------------------------------------------------------

def test_backfill_calls_embed_fn_for_each_skill(store):
    """Each skill without an embedding gets embed_fn called."""
    calls = []
    fake_skills = [
        {"org_id": "acme", "name": "briefing", "description": "Morning summary"},
        {"org_id": "acme", "name": "crm_search", "description": "Search CRM records"},
    ]

    with patch.object(store, "get_skills_without_embedding", return_value=fake_skills), \
         patch.object(store, "store_skill_embedding") as mock_store:
        result = store.backfill_skill_embeddings(embed_fn=lambda t: calls.append(t) or [0.1] * 1536)

    assert len(calls) == 2
    assert result["embedded"] == 2
    assert result["skipped"] == 0
    assert result["failed"] == 0


def test_backfill_passes_name_and_description_to_embed_fn(store):
    """embed_fn receives source text built from name + description."""
    received = []
    fake_skills = [{"org_id": "acme", "name": "briefing", "description": "Morning summary"}]

    with patch.object(store, "get_skills_without_embedding", return_value=fake_skills), \
         patch.object(store, "store_skill_embedding"):
        store.backfill_skill_embeddings(embed_fn=lambda t: received.append(t) or [0.1] * 1536)

    assert len(received) == 1
    assert "briefing" in received[0]
    assert "Morning summary" in received[0]


def test_backfill_calls_store_skill_embedding_with_correct_args(store):
    """store_skill_embedding is called with org_id, name, vector, hash."""
    stored = []
    fake_skills = [{"org_id": "acme", "name": "briefing", "description": "Morning summary"}]
    fake_vec = [0.5] * 1536

    with patch.object(store, "get_skills_without_embedding", return_value=fake_skills), \
         patch.object(store, "store_skill_embedding", side_effect=lambda *a: stored.append(a)):
        store.backfill_skill_embeddings(embed_fn=lambda _: fake_vec)

    assert len(stored) == 1
    org_id, name, vec, h = stored[0]
    assert org_id == "acme"
    assert name == "briefing"
    assert vec == fake_vec
    assert len(h) == 64  # sha256 hex


# ------------------------------------------------------------------
# backfill_skill_embeddings — failure handling
# ------------------------------------------------------------------

def test_backfill_continues_after_single_embed_failure(store):
    """One failed embed doesn't stop the rest."""
    call_count = [0]

    def flaky_embed(text):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("OpenAI timeout")
        return [0.1] * 1536

    fake_skills = [
        {"org_id": "acme", "name": "skill_a", "description": "First skill"},
        {"org_id": "acme", "name": "skill_b", "description": "Second skill"},
    ]

    with patch.object(store, "get_skills_without_embedding", return_value=fake_skills), \
         patch.object(store, "store_skill_embedding"):
        result = store.backfill_skill_embeddings(embed_fn=flaky_embed)

    assert result["embedded"] == 1
    assert result["failed"] == 1
    assert result["skipped"] == 0


def test_backfill_counts_skipped_when_embed_returns_none(store):
    """embed_fn returning None counts as skipped, not failed."""
    fake_skills = [{"org_id": "acme", "name": "briefing", "description": "Morning summary"}]

    with patch.object(store, "get_skills_without_embedding", return_value=fake_skills), \
         patch.object(store, "store_skill_embedding") as mock_store:
        result = store.backfill_skill_embeddings(embed_fn=lambda _: None)

    assert result["skipped"] == 1
    assert result["embedded"] == 0
    assert result["failed"] == 0
    mock_store.assert_not_called()
