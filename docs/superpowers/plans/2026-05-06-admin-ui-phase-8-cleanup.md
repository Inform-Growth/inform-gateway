# Admin UI — Phase 8: Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the legacy HTML dashboard now that all 8 React pages have feature parity. Delete `admin_dashboard.html`, remove the `/admin/legacy` Starlette route, and audit for any leftover D3 references.

**Architecture:** Pure subtraction. No new files, no behavior changes for the React app — it already serves every page in the IA. The only user-visible change is that `/admin/legacy?token=...` now returns a 404 (or actually goes through the SPA catch-all and shows React's "page not found" — which we'll clean up).

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md` (Phase 8 in the migration plan)

---

## Pre-flight: confirm parity

Before deleting the legacy HTML, walk the React app one more time to be sure every legacy feature has a home. The spec maps cleanly:

| Legacy tab | React page | Path |
|---|---|---|
| Executive | Dashboard | `/admin/dashboard` |
| Ops | Operators | `/admin/operators` |
| Tools | Tools | `/admin/tools` |
| Logs | Tool Calls | `/admin/tool-calls` |
| Tasks | Tasks | `/admin/tasks` |
| Org Profile | Settings | `/admin/settings` |
| Skills | Skills | `/admin/skills` |
| Tool Hints | Tool Hints | `/admin/tool-hints` |

If a human review surfaces a missing piece, fix it BEFORE deleting the legacy HTML. The legacy fallback is the safety net — the whole reason it stayed through migration.

---

## Task 1: Audit for D3 references

We never installed D3 (we went straight to recharts), but `admin_dashboard.html` still loads `d3` and `d3-sankey` from CDN. Confirm nothing else references D3.

- [ ] **Step 1: Search**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
grep -r --include="*.ts" --include="*.tsx" --include="*.json" -l "d3\|sankey" remote-gateway/admin-ui/src/ remote-gateway/admin-ui/package.json 2>/dev/null
```

Expected output: empty (no D3 in TS/TSX/package.json under admin-ui/src or in package.json), confirming the React app is D3-free.

```bash
grep -rn "d3" remote-gateway/admin-ui/index.html remote-gateway/admin-ui/public/ 2>/dev/null
```

Expected: no matches in admin-ui/index.html or public/ either.

```bash
grep -n "d3\|sankey\|jsdelivr" remote-gateway/core/admin_dashboard.html | head -5
```

Expected: matches (this is the legacy file being deleted next; the matches confirm we're targeting the right file).

If any unexpected D3 reference appears in admin-ui code, surface it and stop.

- [ ] **Step 2: No commit needed for audit**

If the audit is clean, proceed to Task 2.

---

## Task 2: Delete the legacy HTML and routes

**Files:**
- Delete: `remote-gateway/core/admin_dashboard.html`
- Modify: `remote-gateway/core/admin_api.py` — remove the `/legacy` route, the `dashboard` handler, and the `_DASHBOARD_HTML` constant
- Modify: `remote-gateway/tests/test_admin_routes.py` — remove the `test_legacy_route_serves_html_dashboard` test

### Step 2.1: Inspect what to remove from `admin_api.py`

The legacy infrastructure currently in `admin_api.py`:
- Constant `_DASHBOARD_HTML = Path(__file__).parent / "admin_dashboard.html"` (near the top, after imports)
- Function `dashboard(request: Request)` that serves the HTML (around line 75 — search for `_DASHBOARD_HTML.read_text`)
- Route `Route("/legacy", dashboard)` in the `routes = [...]` list (added in Phase 0 Task 10)

Read the file first; the exact line numbers may have drifted if anything else changed.

### Step 2.2: Edit admin_api.py

Remove the three pieces above. Result:
- No reference to `admin_dashboard.html` anywhere in the codebase
- No `/legacy` route
- The `routes = [...]` list starts with API routes (no leading legacy line)
- The SPA catch-all `Route("/{path:path}", _serve_spa)` remains LAST

If `dashboard` is the only thing imported by external callers (it's not — it's defined inside `create_admin_app`, so no external imports), this is purely local cleanup.

### Step 2.3: Edit test_admin_routes.py

Remove the test `test_legacy_route_serves_html_dashboard`. Keep the other two:
- `test_spa_fallback_returns_503_when_dist_missing`
- `test_unauthorized_returns_403`

The SPA fallback now serves `/legacy` requests too (returning either index.html if dist exists, or 503 otherwise) — that's fine; legacy was a temporary redirect target, not a contract.

### Step 2.4: Delete the HTML file

```bash
git rm remote-gateway/core/admin_dashboard.html
```

### Step 2.5: Verify

```bash
pytest remote-gateway/tests/test_admin_routes.py -v
```

Expected: 2 tests pass (`test_spa_fallback_returns_503_when_dist_missing`, `test_unauthorized_returns_403`).

Run the full Python suite to be sure nothing else referenced the legacy HTML or `dashboard` handler:

```bash
pytest remote-gateway/tests/ -v --ignore=remote-gateway/tests/test_auth_middleware.py --ignore=remote-gateway/tests/test_delete_note_retry.py
```

(The two ignored files have pre-existing collection errors — see Phase 0 final notes.)

Expected: full suite still passes (no test depended on the legacy HTML).

```bash
cd remote-gateway/admin-ui
npm test
npm run build
npx tsc -b
```

Expected: still green.

### Step 2.6: Commit

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_routes.py
git commit -m "chore(admin): retire legacy HTML dashboard

Phase 8 of the React port. Every legacy tab now has a feature-equivalent
React page (Phases 1-7), so the /admin/legacy fallback and the underlying
admin_dashboard.html are no longer needed.

- Delete remote-gateway/core/admin_dashboard.html (2,231 lines)
- Remove the /legacy Starlette route and the dashboard handler from
  admin_api.py
- Drop the test_legacy_route_serves_html_dashboard test; the other two
  admin route tests still cover SPA fallback and 403 behavior.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Update documentation

The CLAUDE.md and README files reference `/admin/legacy` from Phase 0's docs Task 14. Remove those mentions.

**Files:**
- Modify: `CLAUDE.md` (root)
- Modify: `remote-gateway/CLAUDE.md`
- Modify: `README.md` (root)
- Modify: `remote-gateway/admin-ui/README.md` if it mentions legacy

- [ ] **Step 1: Search for legacy mentions**

```bash
grep -rn "/admin/legacy\|admin_dashboard.html\|legacy HTML" \
  CLAUDE.md remote-gateway/CLAUDE.md README.md remote-gateway/admin-ui/README.md 2>/dev/null
```

- [ ] **Step 2: Remove those paragraphs/lines**

Each occurrence is from the Phase 0 docs work. Delete the "Legacy HTML dashboard" subsections / paragraphs entirely (don't leave a "removed in Phase 8" tombstone — the spec serves as historical context).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md remote-gateway/CLAUDE.md README.md remote-gateway/admin-ui/README.md
git commit -m "docs: drop /admin/legacy mentions now that the legacy HTML is retired"
```

(Skip files that didn't need editing — only stage what changed.)

---

## Task 4: Final verification

- [ ] **Step 1: Full clean build**

```bash
cd remote-gateway/admin-ui
rm -rf node_modules dist
npm install
npm run build
```

Expected: clean install + clean build.

- [ ] **Step 2: Full test sweep**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
pytest remote-gateway/tests/test_admin_routes.py -v
cd remote-gateway/admin-ui
npm test
npx tsc -b
```

Expected: 2 admin-route tests pass, 38 Vitest tests pass, tsc clean.

- [ ] **Step 3: Confirm legacy HTML is truly gone**

```bash
git log --oneline --diff-filter=D --name-only | grep admin_dashboard.html
```

Expected: shows the deletion in the cleanup commit.

```bash
find . -path ./node_modules -prune -o -name "admin_dashboard.html" -print
```

Expected: no output (file gone).

- [ ] **Step 4: Review the diff against pre-Phase 0 state (for the eventual PR)**

```bash
git log --oneline main..HEAD | wc -l
```

Should be ~30+ commits across the 9 plans.

---

## Out of Scope (real follow-ups)

The cleanup phase is intentionally narrow. These are real items but don't belong here:

- **Bundle size**: the JS bundle is now ~1.1MB (gzip ~320kB) due to recharts + TanStack Query/Table + react-hook-form/zod. Code-splitting routes via `React.lazy()` would carve this into ~50-100kB initial + lazy chunks. Worth doing soon; out of Phase 8 scope.
- **Code-quality concerns from Batch B review**: scoping `package.json` `overrides` under `jsdom`, using typed `MockedFunction<typeof fetch>` instead of `unknown as ReturnType<typeof vi.fn>`, moving `captureTokenFromUrl()` out of module-import time. Polish, not blocking.
- **The two pre-existing pytest collection errors** (`test_auth_middleware.py`, `test_delete_note_retry.py`) — predate this work, unrelated to admin UI.
- **Updating Plan 1's text** to reflect Tailwind 4 / shadcn/base-ui / React 19 / Vitest 4 / TS 6 (the as-built versions, not the as-planned). Plan 1 stays as historical context; future plans inherit the as-built reality.
- **Manual UAT pass** (open every page in the browser, click everything). Defers to the human; the test suite catches automated regressions.
- **A short `docs/superpowers/specs/...` retro** documenting what changed vs the spec (Tailwind 3 → 4, shadcn/Radix → shadcn/base-ui, etc.). Nice-to-have.

---

## Acceptance Criteria

- [ ] `remote-gateway/core/admin_dashboard.html` no longer exists in git or on disk.
- [ ] `admin_api.py` has no `dashboard` handler, no `_DASHBOARD_HTML` constant, no `/legacy` route.
- [ ] `test_admin_routes.py` no longer contains `test_legacy_route_serves_html_dashboard`.
- [ ] No CLAUDE.md / README references to `/admin/legacy` or `admin_dashboard.html`.
- [ ] `pytest remote-gateway/tests/test_admin_routes.py` passes (2 tests).
- [ ] `npm test`, `npx tsc -b`, `npm run build` all clean.
- [ ] `grep -r "d3\|sankey" remote-gateway/admin-ui/src/` returns no matches.
