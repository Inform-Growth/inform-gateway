"""Tests for scripts/check_catalog_copier_sync.py.

Builds tiny synthetic catalog + copier files in tmp_path and exercises the
extractor helpers + main() via monkey-patching the module-level paths.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import check_catalog_copier_sync as cc


def _write_catalog(path: Path, slugs: list[str]) -> None:
    path.write_text(yaml.safe_dump({
        "version": 1,
        "integrations": {s: {"name": s, "kind": "proxy"} for s in slugs},
    }))


def _write_copier(path: Path, slugs: list[str]) -> None:
    path.write_text(yaml.safe_dump({
        "integrations": {
            "type": "str",
            "multiselect": True,
            "choices": {f"{s} label": s for s in slugs},
        },
    }))


@pytest.fixture
def files(tmp_path: Path, monkeypatch):
    catalog = tmp_path / "catalog.yaml"
    copier = tmp_path / "copier.yml"
    monkeypatch.setattr(cc, "CATALOG_MANIFEST", catalog)
    monkeypatch.setattr(cc, "COPIER_FILE", copier)
    return {"catalog": catalog, "copier": copier}


def test_in_sync_returns_zero(files, capsys):
    _write_catalog(files["catalog"], ["apollo", "attio", "exa"])
    _write_copier(files["copier"], ["apollo", "attio", "exa"])
    assert cc.main() == 0
    assert "in sync" in capsys.readouterr().out


def test_missing_in_copier_returns_one(files, capsys):
    _write_catalog(files["catalog"], ["apollo", "attio", "exa"])
    _write_copier(files["copier"], ["apollo", "attio"])  # missing exa
    assert cc.main() == 1
    captured = capsys.readouterr().out
    assert "missing from copier.yml" in captured
    assert "exa" in captured


def test_extra_in_copier_returns_one(files, capsys):
    _write_catalog(files["catalog"], ["apollo"])
    _write_copier(files["copier"], ["apollo", "zombie"])
    assert cc.main() == 1
    captured = capsys.readouterr().out
    assert "missing from catalog" in captured
    assert "zombie" in captured


def test_missing_files_exit_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cc, "CATALOG_MANIFEST", tmp_path / "does-not-exist.yaml")
    monkeypatch.setattr(cc, "COPIER_FILE", tmp_path / "missing.yml")
    with pytest.raises(SystemExit) as exc_info:
        cc.main()
    assert exc_info.value.code == 2


def test_malformed_copier_choices_exit_two(files, capsys):
    _write_catalog(files["catalog"], ["apollo"])
    # choices as a list, not a dict — should fail loudly
    files["copier"].write_text(yaml.safe_dump({
        "integrations": {"type": "str", "choices": ["apollo"]},
    }))
    with pytest.raises(SystemExit) as exc_info:
        cc.main()
    assert exc_info.value.code == 2


def test_real_files_are_in_sync():
    """The actual repo's catalog and copier.yml must always be in sync."""
    real_catalog = Path(__file__).resolve().parent.parent / "catalog" / "catalog.yaml"
    real_copier = Path(__file__).resolve().parent.parent / "copier.yml"
    if not real_catalog.exists() or not real_copier.exists():
        pytest.skip("real files not present")
    catalog = cc._catalog_slugs(real_catalog)
    copier = cc._copier_choice_slugs(real_copier)
    assert catalog == copier, (
        f"drift: catalog has {catalog - copier}, copier has {copier - catalog}"
    )
