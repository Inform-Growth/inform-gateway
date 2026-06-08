# write_note Conventions Contract — Design Spec

**Date:** 2026-06-08
**Issue:** [#60 — write_note has no discoverable convention contract](https://github.com/Inform-Growth/inform-gateway/issues/60)
**Approach:** B — passive `_conventions` reserved slug + `has_conventions` flag in `list_notes`

---

## Problem

Agents writing to structured folders (e.g. `marketing/`) have no way to discover per-folder contracts (slug patterns, required frontmatter, handshake format) from the tooling. Conventions live only inside skill bodies. Agents that haven't read the right skill write malformed notes; the human has to correct them mid-session.

---

## Convention Standard

`_conventions` is a reserved slug in any notes folder. It is a plain note — no special adapter handling — that defines the contract for that folder:
- Slug patterns (e.g. `content-draft-{date}-{angle-slug}`)
- Required YAML frontmatter keys
- Format rules (aggregate vs per-item)
- Handshake rules for downstream agents

Agents discover the contract by calling `read_note("_conventions", folder=X)` before writing. This is passive — no enforcement, no blocking.

---

## Code Changes

### `list_notes` — `has_conventions` flag

When `folder` is provided, `list_notes` does a `read` lookup for `_conventions` in that folder and adds `has_conventions: bool` to the response. Agents listing a folder before writing see immediately whether a contract exists.

```python
# New response shape (folder provided)
{"notes": [...], "count": N, "has_conventions": True}

# Unchanged (no folder)
{"notes": [...], "count": N}
```

Implementation: after `get_adapter().list(...)`, call `get_adapter().read("_conventions", folder=folder)`. Set `has_conventions = result is not None`. One extra adapter read per `list_notes(folder=X)` call.

### Docstring updates

- **`write_note`**: add "Before writing to a folder, call `read_note('_conventions', folder=X)` to discover slug patterns, frontmatter requirements, and format contracts for that folder."
- **`list_notes`**: add "`has_conventions: true` in the response means a `_conventions` note defines this folder's schema contract — call `read_note('_conventions', folder=X)` to read it."

### `CLAUDE.md` admin reference update

Add to the notes folder convention section:

> **`_conventions` reserved slug**: Create `write_note(slug="_conventions", folder=X, content=<schema doc>)` when setting up a new folder with structured note requirements. Agents call `read_note("_conventions", folder=X)` before writing to discover the contract. `list_notes(folder=X)` surfaces `has_conventions: true` when one exists.

---

## Seed: `marketing/_conventions.md`

Written via `write_note` at deploy time. Content documents the content-draft note schema:

```markdown
# Marketing Folder — Note Conventions

## content-draft notes

**Slug pattern:** `content-draft-{YYYY-MM-DD}-{angle-slug}`
- `angle-slug`: kebab-case label for the angle (e.g. `cold-outbound-roi`, `operator-story`)
- One note per draft angle. Do not aggregate multiple drafts into one note.

**Required YAML frontmatter** (at the top of every content-draft note):
```yaml
angle_slug: <string>
assets_requested: <int>     # total assets requested for this angle
assets_approved: <int>      # approved by Jaron (0 until reviewed)
assets_processed: <int>     # picked up and published by Asset Creator (0 until actioned)
```

**Body:** draft content follows the frontmatter block.

## Aggregate note

**Slug:** `content-drafts-{YYYY-MM-DD}` (one per session, written by Content Writer)
Lists all draft angles from the session with their slugs. The Asset Creator reads
this note to discover the per-draft notes to action.

## Asset Creator handshake

The Asset Creator reads `content-drafts-{date}` to get the session's draft list,
then reads each `content-draft-{date}-{angle-slug}` note. It increments
`assets_processed` on each note it actions and `assets_approved` after Jaron's review.
```

---

## Testing

One test added to `remote-gateway/tests/test_notes_tools.py` (or equivalent):

- `list_notes(folder="marketing")` returns `has_conventions: True` when a `_conventions` note exists in that folder
- `list_notes(folder="marketing")` returns `has_conventions: False` when no `_conventions` note exists
- `list_notes()` (no folder) does not include `has_conventions` in the response

**Friction-to-test note:** Issue #60 was an agent-contract gap — no discoverable convention at write time. The `has_conventions` flag test directly covers the discovery path that would have prevented the mid-session correction loop.
