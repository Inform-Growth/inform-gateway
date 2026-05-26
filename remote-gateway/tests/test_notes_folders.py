"""Tests for folder-aware behavior on GitHubFilesAdapter."""
from __future__ import annotations

import base64
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


# ---- write with folder ----

def _file_create_response(path: str, sha: str) -> dict:
    return {
        "content": {
            "name": path.split("/")[-1],
            "path": path,
            "sha": sha,
            "html_url": f"https://github.com/org/test-notes/blob/main/{path}",
        },
        "commit": {"sha": "commit-x"},
    }


def test_write_with_folder_creates_at_nested_path():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),          # __init__
            _mock_resp(_tree_resp([])),               # write: tree lookup, no collision
        ]
        client.put.return_value = _mock_resp(
            _file_create_response("notes/marketing/comp.md", "new-sha"),
            status_code=201,
        )

        result = GitHubFilesAdapter().write("comp", "x", folder="marketing")

    assert result["status"] == "created"
    assert result["slug"] == "comp"
    assert result["folder"] == "marketing"
    assert result["path"] == "notes/marketing/comp.md"
    assert result["id"] == "new-sha"
    # PUT went to the nested path
    put_url = client.put.call_args[0][0]
    assert put_url.endswith("/contents/notes/marketing/comp.md")
    # No sha on create
    assert "sha" not in client.put.call_args[1]["json"]


def test_write_to_same_folder_takes_update_path():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/marketing/comp.md"])),
        ]
        client.put.return_value = _mock_resp(
            _file_create_response("notes/marketing/comp.md", "updated-sha"),
        )

        result = GitHubFilesAdapter().write("comp", "new content", folder="marketing")

    assert result["status"] == "updated"
    # sha came from tree, included on PUT
    put_body = client.put.call_args[1]["json"]
    assert put_body["sha"] == "blob-notes/marketing/comp.md"


def test_write_collision_in_different_folder_raises_409():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/sales/comp.md"])),  # slug already in sales/
        ]

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().write("comp", "x", folder="marketing")

    assert excinfo.value.status == 409
    assert "sales" in excinfo.value.body  # mentions the folder it's in
    assert "comp" in excinfo.value.body
    client.put.assert_not_called()


def test_write_without_folder_collides_with_folder_slug():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/marketing/comp.md"])),
        ]

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().write("comp", "x")  # no folder

    assert excinfo.value.status == 409
    client.put.assert_not_called()


def test_write_without_folder_to_existing_root_slug_updates():
    """No folder + slug exists at root → update path (no collision)."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/manifesto.md"])),
        ]
        client.put.return_value = _mock_resp(
            _file_create_response("notes/manifesto.md", "new"),
        )

        result = GitHubFilesAdapter().write("manifesto", "v2")

    assert result["status"] == "updated"
    assert result["folder"] is None


def test_write_validates_folder_name():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().write("foo", "x", folder="../etc")

    assert excinfo.value.status == 400
    # No tree call, no put call
    # client.get was called once (in __init__); subsequent should not happen
    assert client.get.call_count == 1
    client.put.assert_not_called()


# ---- read with folder hint ----

def _file_payload(content: str, sha: str = "abc123", path: str = "notes/my-note.md") -> dict:
    return {
        "name": path.split("/")[-1],
        "path": path,
        "sha": sha,
        "content": base64.b64encode(content.encode()).decode(),
        "encoding": "base64",
        "html_url": f"https://github.com/org/test-notes/blob/main/{path}",
    }


def test_read_with_folder_hint_hits_path_directly():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_file_payload("hi", sha="s1", path="notes/marketing/foo.md")),
        ]

        result = GitHubFilesAdapter().read("foo", folder="marketing")

    assert result is not None
    assert result["content"] == "hi"
    assert result["folder"] == "marketing"
    assert result["path"] == "notes/marketing/foo.md"
    # Second GET (after init) went directly to nested path, no tree call
    second_url = client.get.call_args_list[1][0][0]
    assert second_url.endswith("/contents/notes/marketing/foo.md")


def test_read_with_folder_hint_returns_none_on_404_no_fallthrough():
    """Hint is authoritative — 404 returns None, does NOT search the tree."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=404, text="not found"),
        ]

        result = GitHubFilesAdapter().read("foo", folder="marketing")

    assert result is None
    # Only init + one read call, no tree call
    assert client.get.call_count == 2


def test_read_without_folder_uses_tree_to_locate():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/marketing/foo.md"])),
            _mock_resp(_file_payload("hi", sha="s1", path="notes/marketing/foo.md")),
        ]

        result = GitHubFilesAdapter().read("foo")

    assert result is not None
    assert result["folder"] == "marketing"
    assert result["content"] == "hi"
    # Third GET hit the resolved path
    third_url = client.get.call_args_list[2][0][0]
    assert third_url.endswith("/contents/notes/marketing/foo.md")


def test_read_without_folder_returns_none_when_tree_misses():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([])),
        ]

        result = GitHubFilesAdapter().read("ghost")

    assert result is None
    assert client.get.call_count == 2  # init + tree, no contents fetch


def test_read_validates_folder_name():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().read("foo", folder="../etc")

    assert excinfo.value.status == 400


# ---- delete with folder hint ----

def test_delete_with_folder_hint_deletes_at_nested_path():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    existing = _file_payload("bye", sha="del-sha", path="notes/marketing/comp.md")
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(existing),
        ]
        client.request.return_value = _mock_resp({"commit": {"sha": "c1"}})

        result = GitHubFilesAdapter().delete("comp", folder="marketing")

    assert result["status"] == "deleted"
    assert result["path"] == "notes/marketing/comp.md"
    assert client.request.call_args[0][0] == "DELETE"
    assert client.request.call_args[1]["json"]["sha"] == "del-sha"


def test_delete_with_folder_hint_returns_not_found_on_404_no_fallthrough():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(None, status_code=404, text="not found"),
        ]

        result = GitHubFilesAdapter().delete("ghost", folder="marketing")

    assert result["status"] == "not_found"
    client.request.assert_not_called()


def test_delete_without_folder_uses_tree_to_locate():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/marketing/comp.md"])),
        ]
        client.request.return_value = _mock_resp({"commit": {"sha": "c1"}})

        result = GitHubFilesAdapter().delete("comp")

    assert result["status"] == "deleted"
    assert result["path"] == "notes/marketing/comp.md"
    # No content-API GET — tree gave us the sha
    assert client.get.call_count == 2  # init + tree only


def test_delete_without_folder_returns_not_found_when_tree_misses():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([])),
        ]

        result = GitHubFilesAdapter().delete("ghost")

    assert result["status"] == "not_found"
    client.request.assert_not_called()


# ---- list with filters ----

def _commit_resp(date: str, sha: str = "c1") -> dict:
    return {"sha": sha, "commit": {"committer": {"date": date}}}


def test_list_recursive_default_returns_all_md_under_notes():
    """No filters: returns every .md file recursively, including root and folders."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/manifesto.md",
                "notes/marketing/comp.md",
                "notes/sales/lead.md",
                "notes/issues",  # directory entry — ignored even though no .md
                "other/file.md",  # not under notes/ — ignored
                "notes/issues/foo/bar.md",  # too deep — ignored
            ])),
            # One per-file commits call (3 .md files)
            _mock_resp([_commit_resp("2026-05-20T00:00:00Z", sha="cm")]),
            _mock_resp([_commit_resp("2026-05-22T00:00:00Z", sha="cmkt")]),
            _mock_resp([_commit_resp("2026-05-18T00:00:00Z", sha="cs")]),
        ]

        result = GitHubFilesAdapter().list()

    assert len(result) == 3
    slugs = [n["slug"] for n in result]
    # Sorted by updated_at descending
    assert slugs == ["comp", "manifesto", "lead"]
    by_slug = {n["slug"]: n for n in result}
    assert by_slug["manifesto"]["folder"] is None
    assert by_slug["comp"]["folder"] == "marketing"
    assert by_slug["lead"]["folder"] == "sales"


def test_list_folder_filter_returns_only_that_folder():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/manifesto.md",
                "notes/marketing/comp-1.md",
                "notes/marketing/comp-2.md",
                "notes/sales/lead.md",
            ])),
            _mock_resp([_commit_resp("2026-05-22T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-21T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(folder="marketing")

    assert len(result) == 2
    assert all(n["folder"] == "marketing" for n in result)


def test_list_prefix_filter_returns_starts_with_slug():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/marketing/competitor-watch-2026-05-25.md",
                "notes/marketing/competitor-watch-2026-05-24.md",
                "notes/marketing/content-drafts-2026-05-25.md",
            ])),
            _mock_resp([_commit_resp("2026-05-25T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-24T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(prefix="competitor-watch-")

    assert len(result) == 2
    assert all(n["slug"].startswith("competitor-watch-") for n in result)


def test_list_since_until_filters_by_updated_at():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/a.md",  # old
                "notes/b.md",  # in window
                "notes/c.md",  # future
            ])),
            _mock_resp([_commit_resp("2026-05-01T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-15T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-06-01T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(
            since="2026-05-10T00:00:00Z",
            until="2026-05-20T00:00:00Z",
        )

    assert len(result) == 1
    assert result[0]["slug"] == "b"


def test_list_limit_caps_results():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/a.md", "notes/b.md", "notes/c.md"])),
            _mock_resp([_commit_resp("2026-05-01T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-02T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-03T00:00:00Z")]),
        ]

        result = GitHubFilesAdapter().list(limit=2)

    assert len(result) == 2


def test_list_limit_clamped_to_range():
    """limit=0 and limit>100 are clamped to [1, 100]."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    paths = [f"notes/n{i}.md" for i in range(5)]
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(paths)),
            *[_mock_resp([_commit_resp(f"2026-05-0{i+1}T00:00:00Z")]) for i in range(5)],
        ]

        result = GitHubFilesAdapter().list(limit=0)  # clamped up to 1

    assert len(result) == 1


def test_list_combines_filters():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([
                "notes/marketing/competitor-watch-2026-05-25.md",
                "notes/marketing/competitor-watch-2026-05-20.md",  # too old (filtered by since)
                "notes/marketing/content-drafts-2026-05-25.md",    # wrong prefix (pre-filtered)
                "notes/sales/competitor-watch-2026-05-25.md",      # wrong folder (pre-filtered)
            ])),
            # Two entries pass folder+prefix pre-filters; both need commit calls.
            _mock_resp([_commit_resp("2026-05-25T00:00:00Z")]),
            _mock_resp([_commit_resp("2026-05-20T00:00:00Z")]),  # excluded by since
        ]

        result = GitHubFilesAdapter().list(
            folder="marketing",
            prefix="competitor-watch-",
            since="2026-05-24T00:00:00Z",
        )

    assert len(result) == 1
    assert result[0]["slug"] == "competitor-watch-2026-05-25"


def test_list_empty_when_no_matches():
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp([])),
        ]

        result = GitHubFilesAdapter().list(folder="marketing")

    assert result == []


def test_list_invalid_since_raises_400():
    from tools.integrations.notes.adapter import NotesAdapterError
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.return_value = _mock_resp(_repo_meta("main"))

        with pytest.raises(NotesAdapterError) as excinfo:
            GitHubFilesAdapter().list(since="not-a-date")

    assert excinfo.value.status == 400
    assert "invalid date" in excinfo.value.body


def test_list_orphans_sort_last():
    """Files with no commit history get empty timestamps and sort after dated ones."""
    from tools.integrations.notes.adapters.github_files import GitHubFilesAdapter
    with patch("httpx.Client") as mock_cls:
        client = _mock_client_ctx(mock_cls)
        client.get.side_effect = [
            _mock_resp(_repo_meta("main")),
            _mock_resp(_tree_resp(["notes/dated.md", "notes/orphan.md"])),
            _mock_resp([_commit_resp("2026-05-25T00:00:00Z")]),
            _mock_resp([]),  # no commits for orphan
        ]

        result = GitHubFilesAdapter().list()

    assert [n["slug"] for n in result] == ["dated", "orphan"]
    assert result[1]["updated_at"] == ""
