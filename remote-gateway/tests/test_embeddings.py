"""Unit tests for embeddings.py pure functions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


from embeddings import (  # noqa: E402
    SCORE_FLOOR,
    hybrid_score,
    keyword_overlap,
    skill_embed_hash,
    skill_embed_source,
)


def test_skill_embed_source_combines_name_and_description():
    source = skill_embed_source("briefing", "Morning summary")
    assert "briefing" in source
    assert "Morning summary" in source


def test_skill_embed_hash_is_stable():
    source = skill_embed_source("briefing", "Morning summary")
    h1 = skill_embed_hash(source)
    h2 = skill_embed_hash(source)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_skill_embed_hash_changes_with_content():
    h1 = skill_embed_hash(skill_embed_source("a", "b"))
    h2 = skill_embed_hash(skill_embed_source("a", "c"))
    assert h1 != h2


def test_keyword_overlap_identical_texts():
    score = keyword_overlap("search attio for companies", "search attio for companies")
    assert score == pytest.approx(1.0)


def test_keyword_overlap_disjoint_texts():
    score = keyword_overlap("search attio", "write gmail")
    assert score == pytest.approx(0.0)


def test_keyword_overlap_partial():
    score = keyword_overlap("search attio for leads", "search contacts in crm")
    assert 0.0 < score < 1.0


def test_hybrid_score_high_cosine_low_keyword():
    # cosine=1.0, disjoint words → 0.8*1.0 + 0.2*0.0 = 0.8
    score = hybrid_score(1.0, "abc def", "xyz uvw")
    assert score == pytest.approx(0.8, abs=0.01)


def test_hybrid_score_low_cosine_high_keyword():
    # cosine=0.0, identical words → 0.8*0.0 + 0.2*1.0 = 0.2
    score = hybrid_score(0.0, "search attio", "search attio")
    assert score == pytest.approx(0.2, abs=0.01)


def test_score_floor_is_float_between_zero_and_one():
    assert isinstance(SCORE_FLOOR, float)
    assert 0.0 < SCORE_FLOOR < 1.0
