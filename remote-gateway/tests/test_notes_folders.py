"""Tests for folder-aware behavior on GitHubFilesAdapter."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def notes_env(monkeypatch):
    monkeypatch.setenv("NOTES_REPO", "org/test-notes")
    monkeypatch.setenv("NOTES_GITHUB_TOKEN", "ghp_test1234")


def _mock_resp(json_data=None, status_code: int = 200, text: str = "") -> MagicMock:
    m = MagicMock(spec=httpx.Response)
    m.status_code = status_code
    m.text = text or ("" if json_data is None else str(json_data))
    m.json = MagicMock(return_value=json_data)
    if status_code >= 400:
        request = httpx.Request("GET", "https://api.github.com/test")
        m.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"{status_code}", request=request, response=m
            )
        )
    else:
        m.raise_for_status = MagicMock()
    return m


def _mock_client_ctx(mock_cls):
    mock_client = MagicMock()
    mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


def _repo_meta(default_branch: str = "main") -> dict:
    return {"default_branch": default_branch}


def _make_adapter():
    """Construct adapter with __init__'s repo-meta call mocked."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))
        return GitHubFilesAdapter()


# ---- folder validation ----

@pytest.mark.parametrize("bad", [
    "../etc",
    "manifesto.md",
    "UPPER",
    "with space",
    "trailing/",
    "/leading",
    "with.dot",
    "with/slash",
    "",
])
def test_validate_folder_rejects_bad_names(bad):
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import _validate_folder

    with pytest.raises(NotesAdapterError) as excinfo:
        _validate_folder(bad)
    assert excinfo.value.status == 400
    assert "invalid folder name" in excinfo.value.body


@pytest.mark.parametrize("good", [
    "marketing",
    "sales",
    "executive",
    "architecture",
    "shadow",
    "jaron",
    "customer-success",
    "team_42",
    "a",
    "a-b-c_d_e",
])
def test_validate_folder_accepts_good_names(good):
    from tools.integrations.notes.adapters.github_files import _validate_folder

    # Should not raise.
    _validate_folder(good)


def test_validate_folder_accepts_none():
    from tools.integrations.notes.adapters.github_files import _validate_folder

    # None means "root" — always allowed.
    _validate_folder(None)


def _tree_resp(paths: list[str], truncated: bool = False) -> dict:
    """Build a fake git-trees API response.

    Each path becomes a blob entry. Non-leaf path segments are implicit
    (the real API includes tree entries too, but our code filters by type='blob'
    so we only need the blobs here).
    """
    return {
        "sha": "tree-sha",
        "tree": [
            {
                "path": p,
                "type": "blob",
                "sha": f"blob-{p}",
                "size": 100,
                "url": "https://api.github.com/repos/org/test-notes/git/blobs/x",
            }
            for p in paths
        ],
        "truncated": truncated,
    }


# ---- _tree ----

def test_tree_calls_recursive_git_trees_endpoint():
    adapter = _make_adapter()
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_tree_resp([
            "notes/manifesto.md",
            "notes/marketing/competitor-watch-2026-05-25.md",
        ]))

        tree = adapter._tree()

    assert len(tree) == 2
    assert tree[0]["path"] == "notes/manifesto.md"
    # Verify the URL hit the git/trees endpoint with the branch
    call_url = client.get.call_args[0][0]
    assert "/git/trees/main" in call_url
    assert client.get.call_args[1]["params"] == {"recursive": "1"}


def test_tree_wraps_http_error():
    from tools.integrations.notes.adapter import NotesAdapterError
    adapter = _make_adapter()
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(None, status_code=500, text="boom")

        with pytest.raises(NotesAdapterError) as excinfo:
            adapter._tree()

    assert excinfo.value.status == 500
    assert "boom" in excinfo.value.body


# ---- _parse_path ----

@pytest.mark.parametrize("path,expected", [
    ("notes/manifesto.md", ("manifesto", None)),
    (
        "notes/marketing/competitor-watch-2026-05-25.md",
        ("competitor-watch-2026-05-25", "marketing"),
    ),
    (
        "notes/shadow/shadow-2026-05-24-content-drafts.md",
        ("shadow-2026-05-24-content-drafts", "shadow"),
    ),
    ("notes/a/b/c.md", None),       # 3+ levels: ignored
    ("notes/issues", None),         # not a .md file: ignored
    ("other/file.md", None),        # not under notes/: ignored
    ("notes/", None),               # empty/trailing: ignored
])
def test_parse_path(path, expected):
    from tools.integrations.notes.adapters.github_files import _parse_path
    assert _parse_path(path) == expected


# ---- _find_in_tree ----

def test_find_in_tree_returns_path_when_slug_at_root():
    from tools.integrations.notes.adapters.github_files import _find_in_tree
    tree = [
        {"path": "notes/manifesto.md", "type": "blob", "sha": "s1"},
        {"path": "notes/marketing/competitor-watch-2026-05-25.md", "type": "blob", "sha": "s2"},
    ]
    assert _find_in_tree(tree, "manifesto") == ("notes/manifesto.md", None, "s1")


def test_find_in_tree_returns_path_when_slug_in_folder():
    from tools.integrations.notes.adapters.github_files import _find_in_tree
    tree = [
        {"path": "notes/manifesto.md", "type": "blob", "sha": "s1"},
        {"path": "notes/marketing/competitor-watch-2026-05-25.md", "type": "blob", "sha": "s2"},
    ]
    assert _find_in_tree(tree, "competitor-watch-2026-05-25") == (
        "notes/marketing/competitor-watch-2026-05-25.md", "marketing", "s2"
    )


def test_find_in_tree_returns_none_when_not_found():
    from tools.integrations.notes.adapters.github_files import _find_in_tree
    tree = [{"path": "notes/manifesto.md", "type": "blob", "sha": "s1"}]
    assert _find_in_tree(tree, "ghost") is None


def test_find_in_tree_ignores_non_blob_entries():
    from tools.integrations.notes.adapters.github_files import _find_in_tree
    tree = [
        {"path": "notes/marketing", "type": "tree", "sha": "t1"},
        {"path": "notes/manifesto.md", "type": "blob", "sha": "s1"},
    ]
    assert _find_in_tree(tree, "marketing") is None  # 'marketing' is a tree, not a slug
    assert _find_in_tree(tree, "manifesto") == ("notes/manifesto.md", None, "s1")


# ---- _path_for ----

def test_path_for_root_slug():
    adapter = _make_adapter()
    assert adapter._path_for("manifesto") == "notes/manifesto.md"


def test_path_for_slug_with_folder():
    adapter = _make_adapter()
    assert adapter._path_for("competitor-watch-2026-05-25", folder="marketing") == \
        "notes/marketing/competitor-watch-2026-05-25.md"


def test_path_for_none_folder_same_as_omitting():
    adapter = _make_adapter()
    assert adapter._path_for("foo", folder=None) == "notes/foo.md"
