# Notes Adapter: split notes plane from issues plane

**Status:** approved, ready for plan
**Owner:** Jaron
**Closes:** #34, #35
**Relates to:** epic #19 (split storage planes — gateway-internal vs integration-routed)

## Problem

The gateway has two distinct storage needs:

1. **Notes** — durable, human-curated, git-versioned strategic thinking (manifesto, execution-path, track scopes). On Inform Growth's deployment these live as 30 markdown files in `Inform-Growth/inform-notes/notes/`.
2. **Issues** — friction signals filed by `report_issue`. These are GitHub Issues on `ISSUE_DEPLOYMENT_REPO`.

Today both planes share the **same backend**: the `GitHubIssuesAdapter` stores notes as `type:note` GitHub Issues on `NOTES_REPO`. This causes two problems:

- **#34** — agents calling `list_notes` / `read_note` cannot see the 30 markdown files in `notes/`. The human-curated knowledge base is invisible to every agent. Two parallel notes-stores exist (issue-based session shadow notes vs. file-based human notes); agents only see the first, humans only update the second. The institutional-memory loop is broken.
- **#35** — when the GitHub Issues API call fails (auth, rate limit, network), `list_notes` returns `{"notes": [], "count": 0}` silently. The agent treats the empty list as "no notes exist" and the failure mode never surfaces. (Did not reproduce on most recent test, but the silent-fail code path is real.)

## Decision

Split the planes:

| Plane | Backend | Repo | Tools |
|---|---|---|---|
| **Notes** | files under `notes/*.md` | `NOTES_REPO` | `write_note` / `read_note` / `list_notes` / `delete_note` |
| **Issues** | GitHub Issues | `ISSUE_DEPLOYMENT_REPO` | `report_issue` / `list_my_issues` (already correct) |

Replace `GitHubIssuesAdapter` with a new `GitHubFilesAdapter` that reads, writes, and deletes markdown files under `notes/` in `NOTES_REPO` via the GitHub contents API. Migrate the four existing `type:note` issues to files in a one-shot script, then remove the old adapter — no shim, no deprecation period.

Surface adapter failures loudly via a new `NotesAdapterError`. Every adapter call wraps `httpx.HTTPStatusError` and `httpx.RequestError` and re-raises with status, response body, repo, and token fingerprint. No silent empty results.

## Scope (explicitly in)

- New `GitHubFilesAdapter` at `remote-gateway/tools/integrations/notes/adapters/github_files.py`
- `NotesAdapter` Protocol unchanged; default `NOTES_ADAPTER` env var flips from `github-issues` to `github-files`
- Remove `GitHubIssuesAdapter` and its registry entry
- `NotesAdapterError(RuntimeError)` in `adapter.py`; all adapter HTTP calls wrap it
- Migration script `scripts/migrate_notes_issues_to_files.py` (one-shot, idempotent, deleted after run)
- Tests at `remote-gateway/tests/test_notes_files_adapter.py`
- Docs updated: `remote-gateway/CLAUDE.md` (env-var description, token scope), root `CLAUDE.md` (notes-adapter blurb)

## Scope (explicitly out)

- Recursive `notes/**/*.md` enumeration (the existing `notes/issues/` subdir stays invisible)
- PR-based writes (writes go directly to default branch)
- Multiple adapters composed via a comma-list `NOTES_ADAPTER` (epic #19 leaves this open for the future)
- Slug↔filename rewriting (no auto-date prefix; agent's slug becomes `{slug}.md` verbatim)
- Health probe / `health_check` integration for notes (separate ticket if we want it)
- Retained `GitHubIssuesAdapter` as opt-in backend for downstream consumers
- Agent identity in commit trailers (telemetry already attributes by `user_id`)

## Architecture

### `NotesAdapter` Protocol — unchanged

Same `write/read/list/delete` contract, same return shapes (`slug`, `id`, `url`, `status`, plus per-adapter passthroughs). The MCP tool layer at `tools/integrations/notes/tools.py` does not change its public contract — same `html_url`, `slug`, `status`, `content` fields surface to agents.

Adapter-specific passthrough keys swap: today the GH-issues adapter passes `issue_number`. The new files adapter puts the file sha in the Protocol's `id` slot and adds `path` (e.g., `notes/manifesto.md`) as the passthrough. `tools.py` keeps surfacing `issue_number` from the `result.get("issue_number")` call, which simply yields `None` under the new adapter — no MCP-facing breakage, just a deprecated-but-tolerated field. (A follow-up can rename the surfaced field to `path` once we confirm no downstream consumer reads `issue_number`.)

### `GitHubFilesAdapter` — mechanics

```
__init__:
    repo = os.environ["NOTES_REPO"]            # raise RuntimeError if unset
    token = os.environ["NOTES_GITHUB_TOKEN"]   # raise RuntimeError if unset
    branch = repo's default branch (one GET /repos/{repo} at init, cached)

list():
    GET /repos/{repo}/contents/notes
        → 200: filter to .md files, top-level only
        → 404: empty list (notes/ doesn't exist yet)
    GET /repos/{repo}/commits?path=notes&per_page=100
        → match commits to files by path, pick latest commit per file
        → derive created_at (oldest commit touching path) and updated_at (latest)
    return [
        {slug, id=sha, url=html_url, path, created_at, updated_at}
        for each file
    ]

read(slug):
    GET /repos/{repo}/contents/notes/{slug}.md
        → 200: base64-decode .content
            return {slug, content, id=sha, url=html_url, path}
        → 404: return None

write(slug, content):
    GET /repos/{repo}/contents/notes/{slug}.md
        → 200: capture existing sha
        → 404: no existing file
    PUT /repos/{repo}/contents/notes/{slug}.md
        body = {
          message: "notes: {create|update} {slug} via gateway",
          content: base64(content),
          sha: existing_sha,     # only on update
          branch: default_branch,
        }
        → 200/201: return {slug, id=new_sha, url, path, status=created|updated}
        → 409: sha mismatch (concurrent write) — raise NotesAdapterError, do not retry

delete(slug):
    GET /repos/{repo}/contents/notes/{slug}.md
        → 404: return {status=not_found, slug}
        → 200: capture sha
    DELETE /repos/{repo}/contents/notes/{slug}.md
        body = {
          message: "notes: delete {slug} via gateway",
          sha,
          branch: default_branch,
        }
        → 200: return {status=deleted, slug, path}
```

### Error surfacing — `NotesAdapterError`

New exception class in `adapter.py`:

```python
class NotesAdapterError(RuntimeError):
    """Adapter-level failure with enough context to diagnose.

    Attributes:
        status: HTTP status code (or None for network errors)
        body: response body (truncated to 2KB) or exception message
        repo: NOTES_REPO at time of failure
        token_fingerprint: first 4 chars of NOTES_GITHUB_TOKEN + "…"
    """
```

Every method on `GitHubFilesAdapter` wraps its httpx calls:

```python
try:
    resp = client.get(...)
    resp.raise_for_status()
except httpx.HTTPStatusError as e:
    raise NotesAdapterError(...) from e
except httpx.RequestError as e:
    raise NotesAdapterError(status=None, body=str(e), ...) from e
```

The tool layer at `tools.py` does **not** catch this — let it propagate to the MCP framework, which serializes the exception message to the agent. Silent empty lists are no longer possible.

### Migration script — `scripts/migrate_notes_issues_to_files.py`

```
1. GET issues on NOTES_REPO with label=type:note, state=open, per_page=100
2. For each issue:
   a. slug = issue.title
   b. body = issue.body
   c. Check if notes/{slug}.md already exists:
      - exists with same content → skip ("already migrated")
      - exists with different content → log warning, skip (manual review)
      - doesn't exist → continue
   d. PUT notes/{slug}.md with body, commit message:
      "notes: migrate from issue #{n} ({slug})"
   e. POST comment on issue:
      "Migrated to notes/{slug}.md (commit {sha}). Closing — see file-based notes plane."
   f. PATCH issue state=closed
3. Print summary: migrated, skipped, errors
```

Idempotent (step 2c handles re-runs). One-shot — deleted from repo after Inform Growth's deployment runs it.

Uses `NOTES_GITHUB_TOKEN` from env; needs `Contents: read+write` and `Issues: read+write` on `NOTES_REPO` during migration. After migration the token only needs `Contents: read+write`.

## Env vars

| Variable | Before | After |
|---|---|---|
| `NOTES_ADAPTER` | default `github-issues` | default `github-files` |
| `NOTES_REPO` | (unchanged) `owner/repo` | (unchanged) `owner/repo` |
| `NOTES_GITHUB_TOKEN` | scope: `Issues: read+write` | scope: `Contents: read+write` |

Documented in `remote-gateway/CLAUDE.md`. Inform Growth deployment requires:
1. Rotate `NOTES_GITHUB_TOKEN` to a PAT with `Contents: read+write` on `Inform-Growth/inform-notes` (drop the `Issues` scope after migration).
2. Run migration script once.
3. Deploy the new adapter.

## Tests

`remote-gateway/tests/test_notes_files_adapter.py` mocks httpx and covers:

- **write — create path**: file doesn't exist → 404 on GET, PUT succeeds → `status=created`, sha returned
- **write — update path**: file exists → GET returns sha, PUT with sha succeeds → `status=updated`
- **write — sha conflict**: PUT returns 409 → `NotesAdapterError` raised with status=409
- **read — hit**: returns decoded content
- **read — miss**: 404 → returns None (no exception — None is a valid result)
- **list — happy path**: contents API returns 3 files + 1 directory, list filters to `.md` files only, commits API matched to dates
- **list — empty dir**: 404 on contents → returns `[]` (no exception)
- **delete — exists**: returns `status=deleted`
- **delete — missing**: 404 on GET → returns `status=not_found`
- **error surfacing**: each method, when GH returns 500 or 403, raises `NotesAdapterError` with status, body fragment, repo, and token fingerprint

Migration script gets a smoke test (mocked issues API + mocked contents API + idempotency on re-run).

## Risks and mitigations

- **Risk**: agent writes stomp human edits. **Mitigation**: every write goes through GET-then-PUT with `sha` check; concurrent writes 409 cleanly and raise. Branch protection on `notes/manifesto.md` etc. is up to the repo owner — out of scope.
- **Risk**: write contents API rate limit (5000/hr authenticated, plus secondary limits on writes). **Mitigation**: agent write volume is <50/day across all sessions today; no mitigation needed. Revisit if telemetry shows spikes.
- **Risk**: downstream consumers of the template still on `GitHubIssuesAdapter`. **Mitigation**: copier-update will replace the adapter file; consumers need to (1) rotate token scope and (2) run the migration script. Document in template `CHANGELOG` and copier post-update message.
- **Risk**: the four issues to migrate have content the agent might not want overwritten. **Mitigation**: migration script's idempotency check + manual review of any "same slug, different content" warnings before re-running.

## Open questions

None — all three brainstorming questions answered:
1. Write path: direct commit to default branch (option A)
2. Slug ↔ filename: flat, 1:1, top-level only (option A)
3. Existing issues: migrate to files via one-shot script (option A)
