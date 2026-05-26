# Notes Coordination Primitives: folders + server-side filters

**Status:** approved, ready for plan
**Owner:** Jaron
**Closes:** epic #43 (phases 1 + 2)
**Relates to:** #19 (split storage planes — notes plane), #34/#35 (file-based adapter shipped via PR #40)

## Problem

Six active agents (4 marketing + head_of_sales + chief_of_staff) coordinate today through the notes store using slug naming convention as the sole discovery contract. Three structural problems compound as agent count grows:

1. **`list_notes` returns the full catalog every call.** 38 notes today; with 6 daily/weekly writers plus shadow notes plus Jaron's working notes, steady-state in a quarter is ~200, in a year ~700. Chief-of-staff scans the whole list every morning to find ~6 dated notes from the last 24h. Pure token waste, scales linearly.

2. **No write-side scoping.** Convention-only namespaces. Nothing structural prevents content_writer from writing a `competitor-watch-2026-06-01` slug and polluting the read path the marketing researcher depends on.

3. **Mixed concerns in one flat space.** Agent daily outputs, Jaron's strategy docs, gateway architecture notes, shadow audits, and test notes all share one flat list. No way to scope reads by department, cadence, or author.

The convention-only model worked at 2 active writers. At 6 it's strained. At 10+ (when sales Phase 5 + executive layer fully active) it breaks.

## Decision

Ship folder structure + server-side filters in one PR. **Defer** Phase 3 (write-prefix enforcement) and Phase 4 (daily manifests) — both are conditional on observed pollution and Phase-2-insufficiency respectively, neither of which we've seen.

| Phase | Status | Why |
|---|---|---|
| 1 — folder structure + `write_note(folder=...)` | This PR | Foundation for filters |
| 2 — `list_notes(folder=, prefix=, since=, until=, limit=)` | This PR | The actual token-cost win |
| 3 — per-user write-prefix enforcement | **Deferred** (separate issue) | 0 observed pollution; YAGNI |
| 4 — daily manifest notes | **Deferred** (separate issue) | Conditional on Phase 2 not being enough |

## Scope (explicitly in)

- New folder structure on `Inform-Growth/inform-notes` — folders are **dynamic**, not enumerated; any folder string passed to `write_note(folder=...)` materializes on first write. No `.gitkeep` placeholders.
- Folder name validation: `^[a-z0-9_-]+$`.
- `write_note(slug, content, folder=None)` — optional folder param; preserves backward compat at root.
- `read_note(slug, folder=None)` — optional folder hint to skip tree lookup.
- `delete_note(slug, folder=None)` — same hint pattern.
- `list_notes(folder=None, prefix=None, since=None, until=None, limit=None)` — all server-side filters.
- Globally unique slugs across all folders. `write_note` rejects collisions with a 409.
- Tree-API based discovery (`GET /git/trees/{branch}?recursive=1`) — single call gets all paths.
- One-shot migration script applying slug-prefix rules; ambiguous notes stay at root.
- Docs updates: `remote-gateway/CLAUDE.md` documents conventional folder names; `CLAUDE.md` mentions the filter params.

## Scope (explicitly out)

- Phase 3 write-prefix enforcement (per-user `note_write_prefixes` field) — separate follow-up issue.
- Phase 4 daily manifest auto-appended on `write_note` — separate follow-up issue.
- In-process tree cache — add later if write-call API cost matters.
- Truncated-tree handling — current scale is 33+ notes, well below GH's 100K-entry / 7MB tree limits.
- Folder-scoped slugs (the same slug in different folders) — explicitly rejected for backward compat.
- Static-site read view, vendor migration to Notion/Google Docs — out of scope (the issue ruled them out).

## API design

### `write_note(slug, content, folder=None) -> dict`

Behavior:
1. Validate `folder` (if provided) against `^[a-z0-9_-]+$`. Bad → `NotesAdapterError(status=400)`.
2. Fetch the recursive git tree once.
3. Look up `<slug>.md` across all folders.
4. Decide outcome:
   - No existing file → write to `notes/{folder}/{slug}.md` (or `notes/{slug}.md` if `folder=None`).
   - Existing file in *same* folder → update via sha (current behavior).
   - Existing file in *different* folder → `NotesAdapterError(status=409, body="slug exists in folder X; folder param mismatch")`.

Returned dict adds `folder` (the resolved folder, `None` if root). Existing fields preserved: `slug`, `id`, `url`, `path`, `status`.

### `read_note(slug, folder=None) -> dict | None`

Behavior:
- With `folder=X`: `GET contents/notes/{folder}/{slug}.md` directly. 404 → `None`. **Hint is authoritative** — does NOT fall back to tree search.
- Without `folder`: tree lookup finds the unique path, then contents fetch. If no match in tree → `None`.

Returned dict adds `folder` to the existing shape (`slug`, `content`, `id`, `url`, `path`).

### `delete_note(slug, folder=None) -> dict`

Same hint pattern as `read_note`. Same authoritativeness — `folder=X` doesn't fall back.

### `list_notes(folder=None, prefix=None, since=None, until=None, limit=None) -> dict`

Behavior:
1. Fetch the recursive git tree once.
2. Filter tree entries to `.md` files under `notes/`.
3. Apply server-side filters:
   - `folder=X` → only paths under `notes/X/`.
   - `prefix=Y` → only basenames (without `.md`) starting with `Y`. Case-sensitive.
   - `since=ISO8601` / `until=ISO8601` → applied to commit-derived `updated_at` (requires per-file commits query for filtered set only).
4. Sort by `updated_at` descending. Notes with empty `updated_at` (orphans with no commit history) sort last.
5. Apply `limit` (clamped to `[1, 100]`).

Returned dict shape unchanged: `{"notes": [...], "count": N}`. Each note adds a `folder` field (`null` for root-level notes).

**Cost model:** 1 tree call + N commit calls, where N is the post-filter count. Chief-of-staff's daily morning query (`folder="executive", since=<yesterday>`) drops from 1 + 33 calls today to roughly 1 + 1 — Phase 2's promise.

### Filter param specifics

- `since`, `until`: ISO-8601 timestamp (`"2026-05-24T00:00:00Z"`). Date-only callers use UTC midnight. Invalid format → `NotesAdapterError(status=400, body="invalid date: <val>")`.
- `prefix`: case-sensitive slug starts-with.
- `folder`: exact match against the folder segment of the path. Same `^[a-z0-9_-]+$` validation.
- `limit`: positive int. Out-of-range values clamped to `[1, 100]` rather than rejected.

## Architecture

### New helpers on `GitHubFilesAdapter`

- `_tree() -> list[dict]` — single `GET /git/trees/{branch}?recursive=1`. Returns the raw tree entries (each has `path`, `sha`, `type`, `size`). Wrapped in `_wrap` for error surfacing. **Not cached** in v1.
- `_validate_folder(folder)` — regex check; raises `NotesAdapterError(400)` on invalid.
- `_path_for(slug, folder)` — `notes/{folder}/{slug}.md` or `notes/{slug}.md`.
- `_find_in_tree(tree, slug)` — returns `(path, folder)` tuple for any `.md` file whose basename matches `{slug}.md`. Returns `None` if not found. Raises a defensive error if duplicates found (should never happen given write-time enforcement).

### Existing methods change minimally

- `__init__` unchanged.
- `read`, `write`, `delete` add an optional `folder` parameter (default `None`). Internal flow updated per the data flow above.
- `list` is rewritten to use `_tree()` + filters. The old contents-API + commits-API flow is removed.

### Tool-layer changes

`tools.py` updates:
- `write_note(slug, content, folder=None)`, `read_note(slug, folder=None)`, `delete_note(slug, folder=None)` — pass folder through to adapter.
- `list_notes(folder=None, prefix=None, since=None, until=None, limit=None)` — pass all filters through.
- Tool docstrings (MCP descriptions) explicitly document the folder convention (e.g. "use `folder='marketing'` for marketing-team writes"). Lists the recommended conventional folder names from #43.
- Return shapes add `folder` field where applicable.

### MCP description

`list_notes`'s docstring includes:
```
Args:
    folder: Filter to a specific folder (e.g. "marketing", "sales", "executive").
            Conventional names — folders are dynamic; new folders materialize
            on first write_note(folder=X) call.
    prefix: Slug starts-with filter (e.g. "competitor-watch-").
    since:  Return only notes updated at or after this ISO-8601 timestamp.
    until:  Return only notes updated at or before this ISO-8601 timestamp.
    limit:  Cap results (clamped to [1, 100]).
```

This is what enables agents to drop their token cost — they see the filter shape in the tool description and start using it.

## Migration

**One-shot script** at `scripts/migrate_notes_to_folders.py`:

| Slug pattern | Target folder |
|---|---|
| `competitor-watch-*`, `content-drafts-*`, `marketing-research-*`, `marketing-weekly-*` | `marketing/` |
| `signal-scout-*`, `lead-research-*`, `sales-weekly-*`, `sales-strategy-*` | `sales/` |
| `shadow-*` | `shadow/` |
| (everything else) | stay at root |

For each match:
1. GET file content + sha at the old root path.
2. PUT new path `notes/{folder}/{slug}.md` with commit message `notes: move {slug} to {folder}/`.
3. DELETE old path with the captured sha.
4. Print progress.

Idempotent: if the target already exists with matching content, skip. If exists with different content, warn and skip.

GitHub's contents API doesn't support atomic rename — so the migration creates and deletes as two operations per file. Git's similarity detection will recover the rename for `git log --follow` and PR review.

Total ~24 API calls for the ~12 slugs that match. Script is removed in the same PR before merge (the issue-migration cleanup pattern from PR #40).

## Tests

New file `remote-gateway/tests/test_notes_folders.py`:

**Folder param validation:**
- bad folder names raise 400 (e.g. `"../etc"`, `"manifesto.md"`, `"UPPER"`, `"with space"`)
- good folder names accepted (e.g. `"marketing"`, `"customer-success"`, `"team_42"`)

**`write_note` with folder:**
- writes to nested path `notes/{folder}/{slug}.md`
- collision in different folder raises 409
- collision in same folder takes update path
- no collision → create

**`write_note` without folder:**
- writes to root `notes/{slug}.md` (backward compat preserved)
- collision with file at any folder raises 409 (root vs folder is still a collision)

**`read_note` with folder hint:**
- hits `contents/notes/{folder}/{slug}.md` directly (assert no tree call made)
- 404 → returns `None` (does not fall through)

**`read_note` without folder hint:**
- tree lookup finds the file regardless of folder
- empty tree → `None`

**`delete_note`:**
- with folder hint: deletes directly, no tree call
- without folder hint: tree lookup + delete
- file not found → `{status: "not_found", slug}`

**`list_notes` filters:**
- `folder=X` returns only that folder
- `prefix=Y` returns slugs starting with Y
- `since`/`until` filter by `updated_at`
- `limit=N` caps results
- combined filters AND together
- no args = recursive, all `.md` under `notes/`, sorted by `updated_at` desc
- limit clamped to `[1, 100]`
- invalid `since`/`until` raises 400

**`list_notes` ordering:**
- results sorted by `updated_at` descending

**Migration script smoke tests** in `test_migrate_notes_to_folders.py`:
- moves a matching slug
- idempotency: re-run skips already-moved files
- collision: same slug at new path with different content → warn + skip
- root-only slug (no pattern match) → not touched

**Existing tests in `test_notes_files_adapter.py`** are updated where the changes break them:
- `list` tests rewritten for tree-API based discovery.
- `write` tests updated to expect a tree-lookup call before PUT.
- The error-surfacing regression tests (T7 from the prior plan) still apply.

## Backward compatibility

- `write_note(slug, content)` (no folder) still works, still writes to root.
- `read_note(slug)` (no folder) still works, now uses tree to find the file regardless of where it lives.
- `delete_note(slug)` (no folder) same.
- `list_notes()` (no filters) returns ALL notes recursively, replacing today's "all 33 root-level notes" with "all 33 notes across all folders, same count, same data."
- Slug remains the unique identifier. Collisions across folders are rejected at write time.

The only observable change for callers that don't update: `list_notes()` results may be in a different order (now sorted by `updated_at` desc). If any consumer relied on the old alphabetical-by-name order, they need to either sort or switch to filters.

## Cost model

| Operation | Before | After | Delta |
|---|---|---|---|
| `write_note` | 1 GET + 1 PUT | 1 tree + 1 PUT | unchanged (tree returns the blob sha needed for update PUT, replacing the prior GET) |
| `read_note(slug)` | 1 GET | 1 tree + 1 GET (or 1 GET if folder hint provided) | +1 GET when no hint |
| `read_note(slug, folder=X)` | n/a | 1 GET | unchanged |
| `delete_note(slug)` | 1 GET + 1 DELETE | 1 tree + 1 GET + 1 DELETE (or 1 GET + 1 DELETE with hint) | +1 GET when no hint |
| `list_notes()` | 1 contents + N commits | 1 tree + N commits | -N (was N+1, now 1+N) — wash |
| `list_notes(folder=X, since=...)` | n/a (client-side filter) | 1 tree + M commits (M < N) | -N+M — major win for filtered reads |

Writes are roughly unchanged in API-call count (tree replaces the per-path GET). Read-without-hint and delete-without-hint pay +1 GET for the tree lookup; callers that pass `folder=X` avoid that cost. Filtered list reads — the new common case — drop from O(N) commit lookups to O(filtered subset). Phase 2's win is the chief-of-staff morning query going from O(38) to O(handful).

## Deployment

After merge:
1. Run `scripts/migrate_notes_to_folders.py` once against `Inform-Growth/inform-notes` with the existing `NOTES_GITHUB_TOKEN` (already has Contents: read+write).
2. Verify via `gh api repos/Inform-Growth/inform-notes/contents/notes` that the conventional folders exist and contain the expected files.
3. Deploy (Railway auto-deploys on merge to main).
4. Smoke-test on the live gateway: `list_notes(folder="marketing", since="2026-05-24T00:00:00Z")` should return ~6 marketing notes; `list_notes()` should return all 38 with `folder` populated.
5. Update agent role prompts (separate PR / configuration change, not in this PR's scope) to call `write_note(slug, content, folder="marketing")` instead of just `write_note(slug, content)`. Existing agent code keeps working until they're updated.

## Open questions

None — all design questions resolved in brainstorming:
1. Slug uniqueness: globally unique, optional `folder=` read hint for cheap path (option C)
2. `list_notes()` default scope: recursive (option A)
3. Phase 3 + 4: deferred
4. Migration handling for ambiguous notes: stay at root (option C)
5. Folders: dynamic (no pre-seeded structure)
