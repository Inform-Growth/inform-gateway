# Notes Storage Adapter — Design

**Date:** 2026-05-23
**Status:** Approved
**Epic:** [#19 — Storage planes split](https://github.com/Inform-Growth/inform-gateway/issues/19) (this work is the first slice)
**Closes:** [#18 — Notes routing to gateway repo](https://github.com/Inform-Growth/inform-gateway/issues/18)
**Unblocks:** [#22 — Marketing trio rollout](https://github.com/Inform-Growth/inform-gateway/issues/22)
**Design source:** gateway notes [`gateway-thesis-v1`](https://github.com/Inform-Growth/inform-gateway/issues/17) (layer 1 framing) and the epic body of #19.

## Goal

Refactor the notes tools (`write_note`, `read_note`, `list_notes`, `delete_note`) from a single hardcoded GitHub-issues backend into a pluggable adapter pattern, with one adapter (`github-issues`) shipping in this work. Route notes to the existing `Inform-Growth/inform-notes` repo. Keep friction issues (`report_issue`, `list_my_issues`) on the gateway repo unchanged.

## Why

The current `notes.py` writes both client documentation (notes) and gateway bug reports (friction issues) to the same GitHub repo via one env var (`ISSUE_DEPLOYMENT_REPO`). This conflates two storage planes:

- **Gateway-internal storage** — telemetry, tasks, friction issues, sessions, skills, profile, users. Owned by the gateway. Belongs in gateway-controlled storage.
- **Integration-routed storage** — notes, drafts, weekly digests, content. Belongs in the client's documentation system (Notion, Drive, GitHub Issues on a notes repo, etc.).

The first concrete consequence: foundational architecture notes that should live in `inform-notes` instead pile up in `inform-gateway` issues, polluting the friction-tracking signal and putting Inform Growth's operational IP in the wrong repo. The forthcoming Marketing trio rollout (#22) would amplify the problem with daily competitor-watch and content-draft notes.

This work establishes the adapter pattern so the storage backend is per-deployment configuration, not gateway code.

## Non-goals

- **Building a second adapter** (e.g. `SqliteAdapter`, `NotionAdapter`). The interface is designed to support them; only `github-issues` ships in this work.
- **Migrating existing notes** (#16, #17, #20). They stay as legacy in this repo per Question 3-A. A one-line comment on each points forward to the new repo.
- **Closing epic #19.** That closes when a second adapter is added, proving the abstraction.
- **Changing tool signatures.** All four MCP tools keep their current input/output contracts so no agent prompts break.
- **Promoting the notes package to `[core]`** (synced via `distribute.yml`). Stays `[custom]` until a second adapter exists for downstream clients.

## Architecture

### File layout

Move notes into `tools/integrations/notes/` as a package; split friction tools into their own top-level file.

```
remote-gateway/tools/
├── friction.py                        NEW. report_issue + list_my_issues.
│                                       Reads ISSUE_DEPLOYMENT_REPO / ISSUE_DEPLOYMENT_GITHUB_TOKEN. ~120 lines.
├── integrations/
│   └── notes/                         NEW package. ~250 lines total.
│       ├── __init__.py                register(mcp) — wires MCP tools to the configured adapter
│       ├── tools.py                   write_note / read_note / list_notes / delete_note — delegate to adapter
│       ├── adapter.py                 NotesAdapter Protocol + get_adapter() factory + ADAPTERS registry
│       └── adapters/
│           ├── __init__.py
│           └── github_issues.py       GitHubIssuesAdapter — reads NOTES_REPO / NOTES_GITHUB_TOKEN
└── notes.py                           DELETED
```

`mcp_server.py` updates from `from tools import notes as _notes_tools` to `from tools.integrations import notes as _notes_tools` and adds `from tools import friction as _friction_tools` + `_friction_tools.register(mcp)`.

### Sync status

`tools/integrations/notes/` and `tools/friction.py` both stay `[custom]` (Inform-Growth dogfood only) — excluded from `distribute.yml`'s `CORE_FILES`. The adapter pattern is established but only this deployment uses it. Downstream client deployments retain their existing notes implementations until a second adapter (`SqliteAdapter`) is added in a future work item, at which point the notes package promotes to `[core]`.

## Adapter interface

```python
from typing import Protocol

class NotesAdapter(Protocol):
    """Storage backend for notes. Implementations plug into write_note/read_note/list_notes/delete_note."""

    def write(self, slug: str, content: str) -> dict:
        """Create or update a note.

        Returns: {"slug": str, "id": str, "url": str, "status": "created" | "updated"}
        Adapter-specific fields (e.g., "issue_number" for github-issues) MAY be included.
        """

    def read(self, slug: str) -> dict | None:
        """Read a note by slug.

        Returns: {"slug": str, "content": str, "id": str, "url": str, ...} or None.
        """

    def list(self) -> list[dict]:
        """List all notes.

        Returns: [{"slug": str, "id": str, "url": str, "created_at": str, "updated_at": str}, ...]
        Ordering is adapter-defined; github-issues sorts by updated_at desc.
        """

    def delete(self, slug: str) -> dict:
        """Delete (or close, for issue-based backends).

        Returns: {"slug": str, "status": "deleted" | "not_found"}
        """
```

### Factory

```python
ADAPTERS: dict[str, type[NotesAdapter]] = {"github-issues": GitHubIssuesAdapter}

def get_adapter() -> NotesAdapter:
    name = os.environ.get("NOTES_ADAPTER", "github-issues")
    if name not in ADAPTERS:
        raise RuntimeError(
            f"Unknown NOTES_ADAPTER={name!r}. Known adapters: {sorted(ADAPTERS)}"
        )
    return ADAPTERS[name]()
```

The factory is called per-tool-invocation (not cached) so env-var changes during local dev are picked up without restart. Adapter `__init__` reads its required env vars and raises `RuntimeError` with the missing-var name if any are absent.

### GitHubIssuesAdapter — env-var contract

| Env var | Required | Description |
|---|---|---|
| `NOTES_REPO` | Yes | `owner/repo` slug (e.g. `Inform-Growth/inform-notes`) |
| `NOTES_GITHUB_TOKEN` | Yes | Fine-grained PAT with `Issues: read+write` on `NOTES_REPO` |

The adapter creates issues with the `type:note` label (auto-created if missing), uses the slug as the issue title, the note content as the issue body, and treats issue close as note deletion. Behavior is byte-identical to the current `notes.py` implementation, just pointed at a different repo.

## Configuration changes

### Env vars added

```
NOTES_ADAPTER=github-issues          # optional; this is the default
NOTES_REPO=Inform-Growth/inform-notes
NOTES_GITHUB_TOKEN=<PAT>
```

### Env vars unchanged

```
ISSUE_DEPLOYMENT_REPO=Inform-Growth/inform-gateway
ISSUE_DEPLOYMENT_GITHUB_TOKEN=<existing PAT>
```

Friction issues continue going here — they're bugs about the gateway, which belongs in the gateway repo.

### Env vars removed

```
GITHUB_REPO       # file-based-notes-era leftover, no code reads it
GITHUB_TOKEN      # ditto; also dangerous as a generic name (collision with gh, gitpython, etc.)
GITHUB_BRANCH     # only meaningful for the deleted file-based adapter
```

Delete from `.env` (root + remote-gateway) and from Railway after the new vars are in.

## Backward compatibility

### Tool signatures

`write_note(slug, content)`, `read_note(slug)`, `list_notes()`, `delete_note(slug)` keep their current inputs and return shapes. Agents see no change.

### Return-field guarantees

The MCP tools return the adapter's result dict directly. The github-issues adapter preserves the current fields exactly:

- `write_note` returns: `{slug, html_url, status, issue_number}` — same as today.
- `read_note` returns: `{slug, content, issue_number, html_url}` — same as today.
- `list_notes` returns: `{notes: [{slug, issue_number, created_at, updated_at, html_url}, ...], count}` — same as today.
- `delete_note` returns: `{slug, status, issue_number?}` — same as today.

The Protocol declares a normalized `{slug, id, url, ...}` shape going forward; the github-issues adapter includes `issue_number` as an adapter-specific passthrough so existing consumers don't break. Future adapters return their native identifier (e.g. Notion `page_id`) without `issue_number`.

### Agent skills and prompts

No skill or prompt changes required. The note tools are invoked by name; nothing references the implementation path or env vars.

## Migration

Existing notes #16, #17, #20 on this repo stay where they are (per design Q3-A). After the new adapter is live, add a one-comment cutover marker to each:

> _As of 2026-05-23, new notes route to `Inform-Growth/inform-notes`. This note remains here as a pre-cutover legacy artifact._

No content is moved or duplicated. Tests we just closed (#10, #12, #13) need no action.

## Error handling

- **Missing env var** — `GitHubIssuesAdapter.__init__` raises `RuntimeError(f"NOTES_GITHUB_TOKEN is not set...")` with the install-instruction string. Same shape as today's `_headers()`.
- **Unknown adapter name** — `get_adapter()` raises `RuntimeError` listing the registered adapters.
- **GitHub API failure** — adapter raises `httpx.HTTPStatusError` (unchanged from today). The MCP tool layer does not catch — failures propagate as MCP errors.
- **Slug not found on `read_note` / `delete_note`** — returns `{"status": "not_found", ...}`, does not raise. Same as today.

## Testing

| File | What it tests | Notes |
|---|---|---|
| `tests/test_notes_adapter.py` | NEW. `get_adapter()` factory: default, override, unknown name. | Pure-Python; no HTTP. |
| `tests/test_github_issues_adapter.py` | NEW. CRUD against mocked HTTP. Covers: write-creates, write-updates-existing, read-hit, read-miss, list-ordering, delete-closes, delete-not-found, missing-env-raises. | Use `httpx.MockTransport` for deterministic responses. |
| `tests/test_delete_note_retry.py` | UPDATE. Switch envvars from `ISSUE_DEPLOYMENT_*` to `NOTES_REPO` / `NOTES_GITHUB_TOKEN`. Logic identical. | Retry-on-409/422 behavior preserved in the adapter. |
| `tests/test_report_issue.py` | UNCHANGED. Still uses `ISSUE_DEPLOYMENT_*`. | `report_issue` now lives in `tools/friction.py` — adjust import path only. |
| `tests/test_notes.py` | DELETE. This is an integration test that hits a real GitHub repo; the new `test_github_issues_adapter.py` covers the same surface deterministically with mocked HTTP. The Definition-of-Done smoke test against a live gateway covers the real-API path manually post-deploy. | |

## Documentation

| File | Change |
|---|---|
| `remote-gateway/CLAUDE.md` | Env-vars table: add `NOTES_*` rows. Annotate `ISSUE_DEPLOYMENT_*` as "friction issues only". |
| `CLAUDE.md` (root) | Tool inventory: notes section mentions pluggable adapter. Repository Structure: replace `notes.py` with `integrations/notes/` package; add `friction.py`. |
| `.env.example` (root) | Add `NOTES_REPO`, `NOTES_GITHUB_TOKEN` (and optional `NOTES_ADAPTER`). Remove `GITHUB_REPO`, `GITHUB_TOKEN`, `GITHUB_BRANCH`. |
| `remote-gateway/.env.example` | Mirror root changes. |

## Definition of done

- [ ] All four notes tools route through the configured adapter; no direct GitHub calls remain in `tools.py`.
- [ ] `friction.py` exists and `report_issue` / `list_my_issues` work unchanged against `ISSUE_DEPLOYMENT_REPO`.
- [ ] `ruff check .` and `pytest` pass.
- [ ] Smoke test from a live gateway: `write_note("adapter-smoke-test-2026-05-23", "hello")` creates an issue in `Inform-Growth/inform-notes`, `read_note` finds it, `delete_note` closes it.
- [ ] `.env` cleanup applied locally and in Railway: `NOTES_*` set, `GITHUB_REPO`/`GITHUB_TOKEN`/`GITHUB_BRANCH` removed.
- [ ] Cutover comments added to legacy notes #16, #17, #20.
- [ ] Issue #18 closed with a comment pointing at the merge commit. Issue #19 gets a progress comment noting the adapter pattern is in.

## Open questions

None. All scope, config, migration, and adapter-shape questions resolved during brainstorm.
