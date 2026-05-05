# Template Branch Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get `template/clean-gateway` ready for two client forks: synced with main's gateway-core improvements, fully de-Inform'd, with a pre-baked skill-creator system skill, agent-facing extension docs, and one example connector per transport type.

**Architecture:** Stay on `template/clean-gateway` as a branch (no standalone repo extraction this round). Cherry-pick gateway-core improvements from main, skip Apollo/Attio/Wiza work. Replace Inform-specific strings with neutral defaults (`agent-gateway`) or Copier placeholders (`[[ project_slug ]]`) where the value is per-deployment. Build a startup auto-seeder for system skills in SQLite (skills are SQLite rows, not files) and ship a `skill-creator` system skill in the seed set. Add agent-facing extension docs and an example `mcp_connections.example.json`.

**Tech Stack:** Python 3.11, FastMCP, SQLite (telemetry/skills DB), Copier (template scaffolding), Starlette (admin API routes), pytest, ruff.

---

## Critical findings from re-audit (post-unshallow)

These shape the plan. Flagging for your review before execution.

### 1. Skills are SQLite rows, not SKILL.md files
The runtime skill loader (`tools/_core/skill_manager.py` + `core/telemetry.py`) reads/writes a `skills` SQLite table with `(name, description, prompt_template, is_system, ...)`. It never touches `remote-gateway/skills/`.

The `remote-gateway/skills/{conference-contact,gateway-health-check,mcp-builder}/SKILL.md` folders are **orphaned documentation** — no loader reads them. They're Anthropic SKILL.md format but nothing in the gateway code paths consumes that format.

**Implication:** Pre-baking the skill-creator skill means writing a row into the SQLite `skills` table with `is_system=1`. There is currently **no seeding mechanism** in the codebase — the `is_system` flag exists, but nothing inserts system skills at startup. We need to build one.

**Decision baked into the plan:** auto-seed at server startup from a JSON file (`remote-gateway/system_skills.json`). Idempotent. Hot-reload happens because every gateway boot reconciles the file against the DB. This matches your "if it shows up in SQLite it's available" mental model and avoids requiring operators to run a separate bootstrap step.

### 2. Main has 27 gateway-core commits since the merge base (2026-04-26)
Of those, ~13 are Apollo-specific (do not port). The rest are template-relevant:

**Cherry-pick into template:**
- `91d56f4` fix: unwrap ExceptionGroup in streamable-http proxy error log (`mcp_proxy.py`, +5/-1)
- `2cb0719` docs: add recovery hints to declare_intent and complete_task (`task_manager.py`, +5/-1)
- `958890c` fix: add missing tool stubs to test_auth_middleware isolated loader (test reliability)
- `d6e7fed` docs: add inline descriptions to Executive tab
- `a40bbbf` docs: add inline descriptions to Ops tab
- `aa848ec` docs: add inline descriptions to Tools, Logs, and Tasks tabs
- `513842f` docs: add field helper text and richer placeholders to Org Profile tab
- `aa1d032` docs: add inline descriptions to Skills tab and modal
- `2dad28f` docs: add full explainer and field help to Tool Hints tab
- From `bcdf3f1` (mixed): port the `.gitignore` additions for `.mcp.json` + `*.csv` and the rename of `.mcp.json` → `.mcp.json.example` pattern. **Skip** the apollo.py and test_apollo_tools.py changes.
- From `d5ac457` + `d309a4c`: skip (Inform-specific frontend planning docs).

**Skip (Inform-only):**
- All `feat: …apollo…`, `feat: add attio__upsert_record`, `fix: resolve ruff violations in apollo.py`, `feat: wire Apollo tools…`, etc.

### 3. Auto-assign org fix is duplicated across branches
`7b3ed66` (main, 2026-05-04) and `9ffc5fd` (template, 2026-05-04) are independently committed at the same minute. Same intent, same content (the diff is dominated by the strip noise). **Do not cherry-pick `7b3ed66`** — template already has it as `9ffc5fd`. Will need to be aware of this when eventually merging template back to main.

### 4. `remote-gateway/proxy_server.py` exists alongside `core/mcp_proxy.py`
`proxy_server.py` is a separate process-spawning script that hardcodes `"inform-gateway"` as a config key. Worth checking whether it's still used or can be deleted. Plan includes an investigation step.

### 5. Dockerfile installs `attio-mcp` and `mcp-server-github` Node deps that aren't wired in `mcp_connections.json`
Dead weight on the clean template. Plan removes both from `package.json` and the Dockerfile RUN line, and tells operators how to add them back via the integration recipes (Phase 6).

---

## File map

**Will be created:**
- `AGENTS.md` (root)
- `remote-gateway/docs/integrations/stdio.md`
- `remote-gateway/docs/integrations/sse-passthrough.md`
- `remote-gateway/docs/integrations/streamable-http.md`
- `remote-gateway/docs/custom-tools.md`
- `remote-gateway/docs/custom-prompts.md`
- `remote-gateway/mcp_connections.example.json`
- `remote-gateway/system_skills.json`
- `remote-gateway/core/system_skills.py` (seeder module)
- `remote-gateway/tests/test_system_skills.py`

**Will be modified:**
- `pyproject.toml` (project name)
- `package.json` (project name; remove Node MCP deps)
- `Dockerfile` (remove `npm install --prefix remote-gateway/vendor attio-mcp @modelcontextprotocol/server-github` line)
- `.mcp.json` → rename to `.mcp.json.example`; neutralize URL/server name
- `.gitignore` (add `.mcp.json` and `*.csv` lines from `bcdf3f1`)
- `.env.example` (root) — drop `inform-notes` example
- `README.md` (rewrite)
- `CLAUDE.md` (root, fix repo-name + field-registry/proxies sections)
- `remote-gateway/.env.example` (drop Apollo/Attio/Stripe/Snowflake commented examples)
- `remote-gateway/CLAUDE.md` (drop Gmail env vars; fix example name)
- `remote-gateway/core/admin_api.py` (default token)
- `remote-gateway/core/mcp_server.py` (WWW-Authenticate realm; call seeder on startup)
- `remote-gateway/core/mcp_proxy.py` (cherry-pick `91d56f4`)
- `remote-gateway/core/telemetry.py` (add `create_system_skill` helper that sets `is_system=1`)
- `remote-gateway/proxy_server.py` (config key) — or delete if unused
- `remote-gateway/tools/_core/task_manager.py` (cherry-pick `2cb0719`)
- `remote-gateway/tools/notes.py` (docstring example)
- `remote-gateway/core/admin_dashboard.html` (cherry-pick the inline-docs commits)
- `remote-gateway/tests/test_auth_middleware.py` (cherry-pick `958890c`)
- `copier.yml` (expand questions to cover new templated values)
- `.github/workflows/auto_pr.yml`, `auto_promote.yml`, `qa_agent_review.yml` (audit + de-Inform)

**Will be deleted:**
- `remote-gateway/skills/conference-contact/` (Inform-specific, depends on Apollo/Attio/Gmail)
- `remote-gateway/skills/gateway-health-check/` (orphaned doc, no runtime loader)
- `remote-gateway/skills/mcp-builder/` (orphaned doc, no runtime loader; if still useful, contents can be migrated into `remote-gateway/docs/` or seeded as a system skill row instead)

**Branches affected:**
- All work on `template/clean-gateway`
- `template/hubspot-gateway` flagged for deletion after Phase 6 ships the example config (HubSpot pre-wire becomes one entry in `mcp_connections.example.json`)

---

## Phase 0 — Setup & branch prep

### Task 0.1: Create implementation branch off template/clean-gateway

**Files:** none (branch op)

- [ ] **Step 1: Switch to the template branch and create a working branch**

```bash
git checkout template/clean-gateway
git checkout -b chore/template-prep
```

- [ ] **Step 2: Confirm clean working tree**

Run: `git status`
Expected: `nothing to commit, working tree clean`

---

## Phase 1 — Cherry-pick gateway-core improvements from main

Each cherry-pick is its own commit so they're easy to revert individually if conflicts arise.

### Task 1.1: Cherry-pick proxy ExceptionGroup unwrap fix

**Files:**
- Modify: `remote-gateway/core/mcp_proxy.py`

- [ ] **Step 1: Cherry-pick the commit**

```bash
git cherry-pick 91d56f4
```

- [ ] **Step 2: Verify diff is small and clean**

Run: `git show HEAD --stat`
Expected: `remote-gateway/core/mcp_proxy.py | 6 +++++-`

- [ ] **Step 3: Run tests**

Run: `pytest remote-gateway/tests/ -x -q`
Expected: all pass

### Task 1.2: Cherry-pick declare_intent / complete_task recovery hints

- [ ] **Step 1: Cherry-pick**

```bash
git cherry-pick 2cb0719
```

- [ ] **Step 2: Verify**

Run: `git show HEAD --stat`
Expected: `remote-gateway/tools/_core/task_manager.py | 6 +++++-`

### Task 1.3: Cherry-pick test_auth_middleware tool stubs fix

- [ ] **Step 1: Cherry-pick**

```bash
git cherry-pick 958890c
```

- [ ] **Step 2: Verify and run tests**

Run: `pytest remote-gateway/tests/test_auth_middleware.py -v`
Expected: all pass (this commit fixes a flake)

### Task 1.4: Cherry-pick admin dashboard inline docs (six commits, one chain)

- [ ] **Step 1: Cherry-pick the chain in chronological order**

```bash
git cherry-pick d6e7fed a40bbbf aa848ec 513842f aa1d032 2dad28f
```

- [ ] **Step 2: If any cherry-pick conflicts, resolve, `git cherry-pick --continue`, and continue**

- [ ] **Step 3: Manually open the admin dashboard and verify it renders**

Run:
```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py &
SERVER_PID=$!
sleep 3
curl -s http://localhost:8000/admin?token=inform-admin-2026 | head -20
kill $SERVER_PID
```
Expected: HTML body returns; tabs visible; no JS errors when loaded in a browser.

### Task 1.5: Port `.mcp.json` → `.mcp.json.example` rename + .gitignore additions from bcdf3f1 (skip apollo bits)

**Files:**
- Modify: `.gitignore` (append the 7 lines stripped earlier)
- Rename: `.mcp.json` → `.mcp.json.example`

- [ ] **Step 1: Append the missing .gitignore lines**

Add to `.gitignore`:

```
# Local MCP config — contains API keys; copy .mcp.json.example to .mcp.json
.mcp.json

# Data exports and one-off scripts
*.csv
```

(Drop the `enrich_phones.py` line — that's Inform-specific.)

- [ ] **Step 2: Rename `.mcp.json` to `.mcp.json.example`**

```bash
git mv .mcp.json .mcp.json.example
```

- [ ] **Step 3: Verify and commit**

Run: `git status && git diff --staged .gitignore`
Expected: `.mcp.json` renamed; `.gitignore` shows added lines.

```bash
git commit -m "chore: gitignore local .mcp.json and rename committed copy to .example"
```

### Task 1.6: Run full test suite + ruff before moving on

- [ ] **Step 1: Run tests**

Run: `pytest -q`
Expected: all pass

- [ ] **Step 2: Run ruff**

Run: `ruff check .`
Expected: no errors

---

## Phase 2 — Delete orphaned/Inform-specific skills folder

### Task 2.1: Confirm no loader reads `remote-gateway/skills/`

- [ ] **Step 1: Search the codebase**

Run: `grep -rn "remote-gateway/skills\|skills/SKILL\|read_text.*skills/" remote-gateway/ --include='*.py'`
Expected: no hits (the folder is orphaned).

If hits exist, surface to user before proceeding with deletion.

### Task 2.2: Delete the skills folder

**Files:**
- Delete: `remote-gateway/skills/`

- [ ] **Step 1: Remove the directory**

```bash
git rm -r remote-gateway/skills/
```

- [ ] **Step 2: Verify and commit**

Run: `git status`
Expected: deletion of `conference-contact/`, `gateway-health-check/`, `mcp-builder/` subtrees.

```bash
git commit -m "chore: remove orphaned remote-gateway/skills/ folder

Skills are SQLite rows; the SKILL.md folders had no runtime loader.
conference-contact was Inform-specific (Apollo/Attio/Gmail/Calendly)
and would not work on the template anyway."
```

---

## Phase 3 — De-Inform string sweep

### Task 3.1: Choose templating strategy per file

Decision: **Hybrid.** Use Copier placeholders only for values a client deployment legitimately needs to differ on (project name, project slug, gateway URL, github org). For everything else, use the neutral default `agent-gateway`. Avoid templating realm strings, default tokens, and config keys — those should just be neutral.

### Task 3.2: Update `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Replace project name**

Change line 2:
- From: `name = "inform-gateway"`
- To: `name = "[[ project_slug ]]"`

- [ ] **Step 2: Verify and commit**

Run: `git diff pyproject.toml`

```bash
git add pyproject.toml
git commit -m "chore: templatize pyproject.toml project name"
```

### Task 3.3: Update `package.json`

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Replace project name and prep for Phase 9 dep cleanup**

Change line 2:
- From: `"name": "inform-gateway-mcp-tools"`
- To: `"name": "[[ project_slug ]]-mcp-tools"`

- [ ] **Step 2: Commit**

```bash
git commit -am "chore: templatize package.json project name"
```

### Task 3.4: Neutralize `.mcp.json.example`

**Files:**
- Modify: `.mcp.json.example`

- [ ] **Step 1: Replace server key and URL**

Replace contents with:

```json
{
  "mcpServers": {
    "[[ project_slug ]]": {
      "url": "[[ gateway_url ]]/sse",
      "headers": {
        "Authorization": "Bearer ${GATEWAY_USER_API_KEY}"
      }
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
git commit -am "chore: templatize .mcp.json.example"
```

### Task 3.5: Update `remote-gateway/core/admin_api.py` default token

**Files:**
- Modify: `remote-gateway/core/admin_api.py`

- [ ] **Step 1: Replace the hardcoded default**

Change:
- From: `_DEFAULT_TOKEN = "inform-admin-2026"`
- To: `_DEFAULT_TOKEN = "change-me-admin-token"`

Also update the docstring on line 5 to drop "inform-admin-2026".

- [ ] **Step 2: Search for other places that reference the old token**

Run: `grep -rn "inform-admin" .`
Expected: should now only appear in CLAUDE.md / README.md, which Phase 7 rewrites.

- [ ] **Step 3: Commit**

```bash
git commit -am "chore: replace hardcoded admin token default with neutral placeholder"
```

### Task 3.6: Update `remote-gateway/core/mcp_server.py` WWW-Authenticate realm

**Files:**
- Modify: `remote-gateway/core/mcp_server.py:329`

- [ ] **Step 1: Replace realm**

Change:
- From: `(b"www-authenticate", b'Bearer realm="inform-gateway"'),`
- To: `(b"www-authenticate", b'Bearer realm="agent-gateway"'),`

- [ ] **Step 2: Commit**

```bash
git commit -am "chore: neutralize WWW-Authenticate realm"
```

### Task 3.7: Decide fate of `remote-gateway/proxy_server.py`

- [ ] **Step 1: Confirm whether anything imports or runs proxy_server.py**

Run: `grep -rn "proxy_server" --include='*.py' --include='*.sh' --include='*.toml' --include='Dockerfile' .`
Expected: identify whether it's still wired up.

- [ ] **Step 2: If unused, delete it**

```bash
git rm remote-gateway/proxy_server.py
git commit -m "chore: remove unused proxy_server.py"
```

If used, just neutralize the `inform-gateway` config key on line 11 (replace with `agent-gateway`) and commit instead.

### Task 3.8: Update `remote-gateway/tools/notes.py` docstring

**Files:**
- Modify: `remote-gateway/tools/notes.py:9`

- [ ] **Step 1: Replace example**

Change:
- From: `GITHUB_REPO   — owner/repo slug, e.g. "acme/inform-notes"`
- To: `GITHUB_REPO   — owner/repo slug, e.g. "acme/agent-notes"`

- [ ] **Step 2: Commit**

```bash
git commit -am "chore: neutralize notes.py docstring example"
```

### Task 3.9: Strip Inform-only commented-in env vars from `remote-gateway/.env.example`

**Files:**
- Modify: `remote-gateway/.env.example`

- [ ] **Step 1: Remove the Stripe/Snowflake/CRM/OpenAI commented blocks**

Delete the lines:
```
# STRIPE_API_KEY=sk_live_...
# SNOWFLAKE_ACCOUNT=...
# SNOWFLAKE_USER=...
# SNOWFLAKE_PASSWORD=...
# CRM_API_KEY=...
# CRM_BASE_URL=https://api.example.com
```

These are speculative — clients add what they need. Keep `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_BRANCH`, `NOTES_PATH` (used by notes.py), and `OPENAI_API_KEY` (used by CI workflows).

- [ ] **Step 2: Commit**

```bash
git commit -am "chore: trim speculative env vars from .env.example"
```

### Task 3.10: Update root `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Replace `inform-notes` example**

Change:
- From: `GITHUB_REPO=owner/inform-notes`
- To: `GITHUB_REPO=owner/agent-notes`

- [ ] **Step 2: Commit**

```bash
git commit -am "chore: neutralize root .env.example"
```

### Task 3.11: Final sweep for "inform" strings

- [ ] **Step 1: Search**

Run: `grep -rn -i "inform" --include='*.py' --include='*.json' --include='*.toml' --include='*.html' --include='*.yml' --include='*.yaml' . | grep -v -E "(node_modules|vendor|docs/|\.venv|test_|inform[a-z]?ation|inform[a-z]?al)"`
Expected: only README.md / CLAUDE.md hits remain (handled in Phase 7).

If unexpected hits appear, address them in this commit.

- [ ] **Step 2: Run tests + ruff**

```bash
pytest -q && ruff check .
```

---

## Phase 4 — System-skill seeder (the missing infra)

### Task 4.1: Add `create_system_skill` helper to `telemetry.py`

**Files:**
- Modify: `remote-gateway/core/telemetry.py`
- Test: `remote-gateway/tests/test_system_skills.py`

- [ ] **Step 1: Write the failing test**

Create `remote-gateway/tests/test_system_skills.py`:

```python
"""Tests for system skill seeding."""
from __future__ import annotations

import pytest

from telemetry import TelemetryStore


@pytest.fixture
def store(tmp_path):
    return TelemetryStore(db_path=str(tmp_path / "test.db"))


def test_create_system_skill_sets_is_system_flag(store):
    skill = store.create_system_skill(
        org_id="default",
        name="test-skill",
        description="A test skill",
        prompt_template="Do the thing.",
    )
    assert skill["is_system"] == 1
    assert skill["name"] == "test-skill"


def test_create_system_skill_is_idempotent(store):
    a = store.create_system_skill("default", "dup", "desc", "template")
    b = store.create_system_skill("default", "dup", "desc", "template")
    assert a["id"] == b["id"]


def test_create_system_skill_updates_template_on_change(store):
    store.create_system_skill("default", "ev", "v1", "template v1")
    updated = store.create_system_skill("default", "ev", "v2", "template v2")
    assert updated["description"] == "v2"
    assert updated["prompt_template"] == "template v2"
    assert updated["is_system"] == 1


def test_system_skills_cannot_be_user_deleted(store):
    store.create_system_skill("default", "protected", "desc", "template")
    deleted = store.delete_skill("default", "protected")
    assert deleted is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest remote-gateway/tests/test_system_skills.py -v`
Expected: FAIL — `AttributeError: 'TelemetryStore' object has no attribute 'create_system_skill'`

- [ ] **Step 3: Implement `create_system_skill`**

In `remote-gateway/core/telemetry.py`, add (placing it directly under the existing `create_skill` method):

```python
    def create_system_skill(
        self,
        org_id: str,
        name: str,
        description: str,
        prompt_template: str,
    ) -> dict | None:
        """Insert or update a system skill (is_system=1).

        Idempotent — re-running with the same name updates description and
        prompt_template in place. Used by the startup seeder to keep system
        skills in sync with the JSON seed file across deployments.
        """
        if not self._enabled:
            return None
        import time as _t
        import uuid as _uuid
        now = int(_t.time())
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM skills WHERE org_id = ? AND name = ? AND is_active = 1",
                    (org_id, name),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE skills SET description = ?, prompt_template = ?, "
                        "is_system = 1, updated_at = ? WHERE id = ?",
                        (description, prompt_template, now, row["id"]),
                    )
                    sid = row["id"]
                else:
                    sid = _uuid.uuid4().hex
                    conn.execute(
                        "INSERT INTO skills (id, org_id, name, description, prompt_template, "
                        "is_active, is_system, created_by, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?, ?)",
                        (sid, org_id, name, description, prompt_template, "system", now, now),
                    )
                conn.commit()
                return self.get_skill(org_id, name)
        except Exception:
            return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest remote-gateway/tests/test_system_skills.py -v`
Expected: all 4 PASS

- [ ] **Step 5: Run ruff**

Run: `ruff check remote-gateway/core/telemetry.py remote-gateway/tests/test_system_skills.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_system_skills.py
git commit -m "feat: add create_system_skill helper for startup seeding

Idempotent insert-or-update for skills with is_system=1, used by the
seeder in the next commit. System skills cannot be user-deleted (the
existing skill_delete already enforces this)."
```

### Task 4.2: Add the seeder module

**Files:**
- Create: `remote-gateway/system_skills.json`
- Create: `remote-gateway/core/system_skills.py`
- Modify: `remote-gateway/tests/test_system_skills.py` (extend)

- [ ] **Step 1: Create the seed file (initially with one placeholder; the real skill-creator template comes in Task 5)**

Create `remote-gateway/system_skills.json`:

```json
{
  "_comment": "System skills seeded into the SQLite skills table on every gateway startup. is_system=1 means users cannot edit or delete them via the admin UI or skill_update/skill_delete tools. Hot-reload happens because every boot reconciles this file against the DB.",
  "skills": []
}
```

- [ ] **Step 2: Write the failing test for the seeder**

Append to `remote-gateway/tests/test_system_skills.py`:

```python
import json

from system_skills import seed_system_skills


def test_seeder_loads_skills_from_json(store, tmp_path):
    seed_file = tmp_path / "skills.json"
    seed_file.write_text(json.dumps({
        "skills": [
            {"name": "alpha", "description": "first", "prompt_template": "Do alpha."},
            {"name": "beta", "description": "second", "prompt_template": "Do {x}."},
        ]
    }))
    count = seed_system_skills(store, org_id="default", seed_file=str(seed_file))
    assert count == 2
    assert store.get_skill("default", "alpha")["is_system"] == 1
    assert store.get_skill("default", "beta")["prompt_template"] == "Do {x}."


def test_seeder_is_idempotent(store, tmp_path):
    seed_file = tmp_path / "skills.json"
    seed_file.write_text(json.dumps({
        "skills": [{"name": "alpha", "description": "first", "prompt_template": "Do alpha."}]
    }))
    seed_system_skills(store, org_id="default", seed_file=str(seed_file))
    seed_system_skills(store, org_id="default", seed_file=str(seed_file))
    skills = [s for s in store.list_skills("default") if s["name"] == "alpha"]
    assert len(skills) == 1


def test_seeder_skips_when_file_missing(store, tmp_path):
    count = seed_system_skills(store, org_id="default", seed_file=str(tmp_path / "missing.json"))
    assert count == 0


def test_seeder_handles_empty_skills_list(store, tmp_path):
    seed_file = tmp_path / "skills.json"
    seed_file.write_text('{"skills": []}')
    count = seed_system_skills(store, org_id="default", seed_file=str(seed_file))
    assert count == 0
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pytest remote-gateway/tests/test_system_skills.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'system_skills'`

- [ ] **Step 4: Implement the seeder**

Create `remote-gateway/core/system_skills.py`:

```python
"""Seed system skills into SQLite at gateway startup.

Reads remote-gateway/system_skills.json and upserts each entry as a
system skill (is_system=1) for the given org. Idempotent — safe to
call on every boot. Missing file is a no-op so dev environments
without the file still start cleanly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def seed_system_skills(
    telemetry: Any,
    org_id: str = "default",
    seed_file: str | None = None,
) -> int:
    """Upsert system skills from the seed JSON file.

    Args:
        telemetry: TelemetryStore instance.
        org_id: Org to seed into. Defaults to "default" (matches the
            fallback used by skill_manager when no user is set).
        seed_file: Path to the JSON seed file. Defaults to
            ``remote-gateway/system_skills.json`` relative to repo root.

    Returns:
        Count of skills upserted. 0 if file is missing or empty.
    """
    if seed_file is None:
        seed_file = str(Path(__file__).resolve().parent.parent / "system_skills.json")
    path = Path(seed_file)
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"[system_skills] failed to parse {path}: {exc}")
        return 0
    skills = data.get("skills", [])
    seeded = 0
    for entry in skills:
        result = telemetry.create_system_skill(
            org_id=org_id,
            name=entry["name"],
            description=entry["description"],
            prompt_template=entry["prompt_template"],
        )
        if result is not None:
            seeded += 1
    if seeded:
        print(f"[system_skills] seeded {seeded} system skill(s) for org '{org_id}'")
    return seeded
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest remote-gateway/tests/test_system_skills.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/system_skills.py remote-gateway/system_skills.json remote-gateway/tests/test_system_skills.py
git commit -m "feat: add system skill seeder

Reads remote-gateway/system_skills.json on startup and upserts each
entry as is_system=1. Idempotent. Missing file is a no-op. Skill
authors edit the JSON file; redeploy reconciles into SQLite."
```

### Task 4.3: Wire the seeder into mcp_server.py startup

**Files:**
- Modify: `remote-gateway/core/mcp_server.py`

- [ ] **Step 1: Add seeder call to the lifespan startup**

Find the `lifespan` async context manager (near top of file). Replace with:

```python
@asynccontextmanager
async def lifespan(server: FastMCP):
    """Start upstream MCP proxy connections on startup; clean up on shutdown."""
    from system_skills import seed_system_skills
    seed_system_skills(_telemetry)
    proxy_tasks = await mount_all_proxies(server)
    yield
    for task in proxy_tasks:
        task.cancel()
    if proxy_tasks:
        await asyncio.gather(*proxy_tasks, return_exceptions=True)
```

- [ ] **Step 2: Start the server and confirm seeder runs**

```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py &
SERVER_PID=$!
sleep 3
kill $SERVER_PID
```
Expected: stderr shows `[system_skills] seeded 0 system skill(s)` (the seed file is empty until Task 5).

If the line doesn't appear, the seeder isn't being called — debug before proceeding.

- [ ] **Step 3: Commit**

```bash
git commit -am "feat: call system_skills seeder in mcp_server lifespan"
```

---

## Phase 5 — Author the skill-creator system skill

### Task 5.1: Draft the skill-creator prompt template

**Files:**
- Modify: `remote-gateway/system_skills.json`

- [ ] **Step 1: Reference the canonical Anthropic skill-creator pattern**

Read the available `anthropic-skills:skill-creator` skill description in this session for inspiration. The gateway version differs in one critical way: skills are stored as SQLite rows via the `skill_create` MCP tool, not as files on disk. The skill-creator skill must guide the agent to call `skill_create(name, description, prompt_template)` at the end.

- [ ] **Step 2: Update `system_skills.json` with the skill-creator entry**

Replace the contents of `remote-gateway/system_skills.json`:

```json
{
  "_comment": "System skills seeded into the SQLite skills table on every gateway startup. is_system=1 means users cannot edit or delete them via the admin UI or skill_update/skill_delete tools. Hot-reload happens because every boot reconciles this file against the DB.",
  "skills": [
    {
      "name": "skill-creator",
      "description": "Guides the agent through designing and registering a new gateway skill. Use when an operator wants to package a repeatable workflow as a reusable skill that other agents can invoke via run_skill.",
      "prompt_template": "You are creating a new gateway skill. A skill is a prompt template stored in SQLite that other agents can render and execute via the run_skill tool.\n\n## What the operator gave you\n\nGoal: {goal}\nExpected inputs (variables): {variables}\n\n## Your job\n\n1. Confirm you understand the goal. If anything is unclear, ask the operator one focused clarifying question and stop. Do not guess.\n\n2. Design the skill:\n   - Pick a snake_case name. Keep it short and discoverable.\n   - Write a one-paragraph description for skill_list. Describe what it does and when to use it. This is the agent-facing trigger text.\n   - Draft the prompt_template. Use {placeholder} syntax for runtime variables. The template renders via Python str.format(), so any literal curly braces in the prompt must be doubled ({{ and }}).\n\n3. Show the operator the proposed name, description, and prompt_template. Ask: \"Register this as-is, or revise?\" Wait for explicit approval before the next step.\n\n4. On approval, call skill_create with the three values. The skill is now live for this org and discoverable via skill_list.\n\n5. Do not write SKILL.md files or modify the repo. Skills are SQLite rows; the skill_create tool is the only persistence path.\n\n## Quality bar\n\n- The description is the agent's only signal for when to invoke the skill. Make it specific.\n- Prompt templates should be self-contained: don't assume context the calling agent won't have.\n- Test the skill yourself by calling run_skill with sample variables before reporting success."
    }
  ]
}
```

- [ ] **Step 3: Restart the server and verify the skill is seeded**

```bash
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py &
SERVER_PID=$!
sleep 3
sqlite3 data/telemetry.db "SELECT name, is_system FROM skills WHERE name='skill-creator';"
kill $SERVER_PID
```
Expected: `skill-creator|1`

- [ ] **Step 4: Verify the skill is callable**

Run the gateway and use any MCP client to call `run_skill("skill-creator", {"goal": "send weekly stand-up reminder", "variables": "team_name"})`.
Expected: returns the rendered prompt template with `{goal}` and `{variables}` substituted.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/system_skills.json
git commit -m "feat: ship skill-creator as a default system skill

Operators can call run_skill('skill-creator', {goal, variables}) to be
walked through designing and registering a new SQLite-backed skill.
Lives in system_skills.json; reconciled into SQLite on startup."
```

---

## Phase 6 — Agent-facing extension docs + example connectors

### Task 6.1: Create the docs directory

**Files:**
- Create: `remote-gateway/docs/integrations/stdio.md`
- Create: `remote-gateway/docs/integrations/sse-passthrough.md`
- Create: `remote-gateway/docs/integrations/streamable-http.md`
- Create: `remote-gateway/docs/custom-tools.md`
- Create: `remote-gateway/docs/custom-prompts.md`

- [ ] **Step 1: Read existing reference material**

Run:
```bash
cat remote-gateway/core/mcp_proxy.py | head -100
cat remote-gateway/mcp_connections.json
```
Note the three transport types supported by `mount_all_proxies`: `stdio`, `sse`, `streamable-http`.

- [ ] **Step 2: Write `remote-gateway/docs/integrations/stdio.md`**

Cover: when to use stdio (local Node CLI MCP servers like `@hubspot/mcp-server`, `@modelcontextprotocol/server-github`), how to add an entry to `mcp_connections.json`, env var pattern (`${VAR_NAME}` substitution), and reference the HubSpot block from `mcp_connections.example.json` as the canonical example. Include a "verify" section: restart the gateway and check `tools/list` for `<integration>__<tool>` entries.

- [ ] **Step 3: Write `remote-gateway/docs/integrations/sse-passthrough.md`**

Cover: when to use SSE (legacy remote MCP servers using the older transport), config shape, auth header pattern. Reference `mcp_connections.example.json`.

- [ ] **Step 4: Write `remote-gateway/docs/integrations/streamable-http.md`**

Cover: streamable-http (newer remote MCP servers — most modern third-party servers like Apollo's hosted MCP). Config shape, auth header / OAuth token handling. Reference `mcp_connections.example.json`.

- [ ] **Step 5: Write `remote-gateway/docs/custom-tools.md`**

Cover: how to add a Python tool. Pattern: create `remote-gateway/tools/<name>.py` with `register(mcp, telemetry, current_user_var)`, register it from `mcp_server.py`, wrap responses with `validated("<integration>", result)` if a field schema exists, write tests in `remote-gateway/tests/`.

Show a 30-line skeleton example with a fake `weather__forecast` tool.

- [ ] **Step 6: Write `remote-gateway/docs/custom-prompts.md`**

Cover: how to add a `@mcp.prompt(...)` function in `mcp_server.py` (or a separate module). Reference `prompts/init.md` as the existing pattern.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/docs/
git commit -m "docs: add agent-facing integration and extension recipes

Per-transport-type docs (stdio, sse, streamable-http) with one
canonical example each, plus how-to docs for adding custom Python
tools and MCP prompts. Recipe-style for agents extending the gateway."
```

### Task 6.2: Create `mcp_connections.example.json`

**Files:**
- Create: `remote-gateway/mcp_connections.example.json`

- [ ] **Step 1: Pick one example per transport type**

stdio: HubSpot (port from `template/hubspot-gateway` — the existing pre-wired block).
SSE: a generic example (the gateway can proxy any SSE MCP server; use a placeholder config showing the shape).
streamable-HTTP: a generic example (Apollo's hosted MCP is one real-world option; use a placeholder showing the shape — do not include any Inform-specific tokens).

- [ ] **Step 2: Write the file**

Create `remote-gateway/mcp_connections.example.json`:

```json
{
  "_comment": "Example MCP server connections — one per transport type. Copy entries from here into mcp_connections.json and uncomment the env vars in .env to enable. Tools appear at runtime as <integration>__<tool_name>.",
  "connections": {
    "hubspot": {
      "_transport_type": "stdio (local Node CLI MCP server)",
      "_docs": "remote-gateway/docs/integrations/stdio.md",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@hubspot/mcp-server"],
      "env": {
        "PRIVATE_APP_ACCESS_TOKEN": "${HUBSPOT_PRIVATE_APP_ACCESS_TOKEN}"
      }
    },
    "example_sse": {
      "_transport_type": "sse (older remote MCP servers)",
      "_docs": "remote-gateway/docs/integrations/sse-passthrough.md",
      "transport": "sse",
      "url": "https://mcp.example.com/sse",
      "headers": {
        "Authorization": "Bearer ${EXAMPLE_SSE_TOKEN}"
      }
    },
    "example_http": {
      "_transport_type": "streamable-http (newer remote MCP servers)",
      "_docs": "remote-gateway/docs/integrations/streamable-http.md",
      "transport": "streamable-http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${EXAMPLE_HTTP_TOKEN}"
      }
    }
  }
}
```

- [ ] **Step 3: Verify the existing mcp_connections.json stays empty**

Confirm `remote-gateway/mcp_connections.json` is still `{"connections": {}}`. Clients add entries themselves.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/mcp_connections.example.json
git commit -m "feat: add mcp_connections.example.json with one entry per transport"
```

---

## Phase 7 — README, CLAUDE.md, AGENTS.md rewrites

### Task 7.1: Rewrite root `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Audit current state**

Run: `git diff template/clean-gateway -- README.md` (no diff yet — it's still the old one).

- [ ] **Step 2: Replace contents**

Drop sections that reference removed tools and prompts. New structure:
- Title + tagline (neutral, no Inform branding)
- Core mandates (Shadow Note-taking, Proactive Maintenance, Context Efficiency — keep but generalize)
- Getting started: connect to the gateway via `.mcp.json.example` snippet (uses `[[ project_slug ]]` and `[[ gateway_url ]]`)
- Initialize session via `/operator_init`
- Features: list ONLY the prompts that exist on this branch (`operator_init`, `qa_agent_instructions`, `how_to_use_prompts`)
- Local development: install, configure env (link to `.env.example`), start server, verify health, open admin dashboard at `http://localhost:8000/admin?token=<your ADMIN_TOKEN>` (no hardcoded value), connect Claude Code, run tests
- Administration: deployment, tool promotion (link to `remote-gateway/docs/custom-tools.md` and `custom-prompts.md`)
- Adding integrations: link to `remote-gateway/docs/integrations/`
- Repository structure: align with what actually exists
- License

Use Copier placeholders `[[ project_name ]]`, `[[ project_slug ]]`, `[[ gateway_url ]]` where appropriate.

- [ ] **Step 3: Sanity check**

Run: `grep -in "apollo\|attio\|wiza\|inform-admin\|inform-gateway\|morning_briefing\|weekly_pipeline_review\|research_prospect\|add_prospect" README.md`
Expected: no hits

- [ ] **Step 4: Commit**

```bash
git commit -am "docs: rewrite README to match stripped template state"
```

### Task 7.2: Rewrite root `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update repo name reference, field-registry bullet, and admin-guardrails proxy list**

Specific edits:
- Line 3 area: change `inform-gateway` → `[[ project_slug ]]`
- "Field Registry" / "context/fields/" bullet: drop the apollo/attio-companies/attio-deals/attio-people/exa names; replace with "YAML field schemas live in `context/fields/`. None ship by default."
- "Admin Guardrails" / "All proxied integrations (exa, apollo, attio, github)": change to "All proxied integrations defined in `mcp_connections.json`"
- Tool inventory table: drop the Apollo/Attio rows. Keep built-in tools and field-registry tools. Drop the proxied-integrations table or replace with "No integrations configured by default — see `remote-gateway/docs/integrations/` to add yours."
- Available Prompts table: prune to `operator_init`, `qa_agent_instructions`, `how_to_use_prompts`

- [ ] **Step 2: Sanity check**

Run: `grep -in "apollo\|attio\|wiza\|exa.yaml\|inform" CLAUDE.md`
Expected: no hits except the project_slug placeholder.

- [ ] **Step 3: Commit**

```bash
git commit -am "docs: align root CLAUDE.md with stripped template state"
```

### Task 7.3: Rewrite `remote-gateway/CLAUDE.md`

**Files:**
- Modify: `remote-gateway/CLAUDE.md`

- [ ] **Step 1: Drop Gmail env vars, fix example name**

Specific edits:
- Env-var table: remove `GMAIL_OAUTH_KEYS_JSON`, `GMAIL_CREDENTIALS_JSON`, `GMAIL_OAUTH_PATH`, `GMAIL_CREDENTIALS_PATH` rows
- `MCP_SERVER_NAME` example: change `inform-gateway` → `agent-gateway`
- Drop any other Inform-specific examples surfaced by grep

- [ ] **Step 2: Sanity check**

Run: `grep -in "gmail\|inform" remote-gateway/CLAUDE.md`
Expected: no hits

- [ ] **Step 3: Commit**

```bash
git commit -am "docs: drop Gmail env vars from remote-gateway/CLAUDE.md"
```

### Task 7.4: Create root `AGENTS.md`

**Files:**
- Create: `AGENTS.md`

- [ ] **Step 1: Write the file**

Create `AGENTS.md` as the top-level guide for any agent working in or with this repo. Sections:
- Purpose: agents extending the gateway, agents calling the gateway
- For agents calling the gateway: initialize with `operator_init`; shadow-note + issue-log mandates; available prompt templates and tools
- For agents extending the gateway:
  - Adding an integration: link to `remote-gateway/docs/integrations/`
  - Adding a custom tool: link to `remote-gateway/docs/custom-tools.md`
  - Adding a custom prompt: link to `remote-gateway/docs/custom-prompts.md`
  - Creating a system skill: edit `remote-gateway/system_skills.json` and redeploy
  - Creating a user skill: call `skill_create` via the gateway
- House style: Read-Only by Default; field registry; tests required; ruff clean

Keep it short — link out to the focused docs rather than restating them.

- [ ] **Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: add AGENTS.md as the entry point for agents extending the gateway"
```

---

## Phase 8 — GitHub Actions audit

### Task 8.1: Audit each workflow

**Files:**
- Read: `.github/workflows/auto_pr.yml`
- Read: `.github/workflows/auto_promote.yml`
- Read: `.github/workflows/qa_agent_review.yml`

- [ ] **Step 1: Read each workflow file and inventory Inform-specific concerns**

Run: `grep -n -i "inform\|jaron\|apollo\|attio\|wiza" .github/workflows/*.yml`

For each hit, decide:
- **Templatize via Copier**: if the value is per-deployment (org name, repo name, secret name)
- **Replace with neutral default**: if the value is incidental (`agent-gateway` instead of `inform-gateway`)
- **Drop**: if the workflow assumes Inform-specific tooling (e.g., apollo promotion checks)
- **Document**: if the workflow needs additional setup the operator must do (e.g., setting `OPENAI_API_KEY` secret)

- [ ] **Step 2: Apply edits**

For each workflow, make the targeted change and commit individually:

```bash
git commit -am "ci: de-Inform <workflow_name>.yml"
```

If a workflow has no template-relevant logic (e.g., `auto_promote.yml` triggers on `operator/` branches that may not exist for clients), document this in the PR description rather than deleting — the workflow is harmless if its trigger never fires.

- [ ] **Step 3: Run any workflow-validation tooling if available**

Run: `npx -y action-validator .github/workflows/*.yml 2>/dev/null || true`
(Best-effort lint; don't block on it.)

---

## Phase 9 — Node deps cleanup

### Task 9.1: Remove unused Node MCP deps from package.json and Dockerfile

**Files:**
- Modify: `package.json`
- Modify: `Dockerfile`

- [ ] **Step 1: Drop the deps from `package.json`**

Replace `dependencies` block with:

```json
"dependencies": {}
```

Update the description line as well to drop "Vendored MCP tools" if appropriate, or keep it minimal:

```json
"description": "Vendored MCP tools — add per-integration packages here as needed (see remote-gateway/docs/integrations/)"
```

- [ ] **Step 2: Drop the install line from `Dockerfile`**

Find:
```
RUN npm install --prefix remote-gateway/vendor attio-mcp @modelcontextprotocol/server-github
```
Delete it. Also evaluate the parent `RUN pip install ... && npm install` — `npm install` with empty deps will still succeed and is harmless; leave it for when clients add deps.

- [ ] **Step 3: Verify the Docker build still completes**

Run: `docker build -t agent-gateway-test .`
Expected: build succeeds.

If build fails, note the failure and either fix or skip the docker test (mark as todo for the smoke test phase).

- [ ] **Step 4: Commit**

```bash
git commit -am "chore: drop unused attio-mcp and mcp-server-github Node deps

Clients add per-integration packages themselves following the recipes
in remote-gateway/docs/integrations/. The example HubSpot entry in
mcp_connections.example.json shows the npx pattern."
```

---

## Phase 10 — Copier scaffold expansion

### Task 10.1: Add new Copier questions

**Files:**
- Modify: `copier.yml`

- [ ] **Step 1: Inventory all `[[ ... ]]` placeholders introduced in Phases 3–7**

Run: `grep -rn "\[\[" --include='*.json' --include='*.toml' --include='*.md' --include='*.example' .`
Expected: list of all placeholder uses. Expected variables: `project_name`, `project_slug`, `gateway_url`, `github_org` (already in copier.yml). Possibly add: `admin_token` (defaulted), `notes_repo` (defaulted to `<github_org>/agent-notes`).

- [ ] **Step 2: Update `copier.yml` to cover any new variables**

Add any missing question blocks, following the existing pattern. Example for `admin_token`:

```yaml
  admin_token:
    type: str
    help: "Initial admin dashboard token. Override via ADMIN_TOKEN env var in production."
    default: change-me-admin-token
    secret: true
```

- [ ] **Step 3: Smoke test the Copier scaffold**

```bash
pip install copier
mkdir /tmp/copier-test
copier copy . /tmp/copier-test --vcs-ref HEAD --trust
cd /tmp/copier-test && grep -rn "\[\[" .
```
Expected: no remaining `[[ ... ]]` placeholders in the rendered output. If any remain, add the matching question to `copier.yml`.

- [ ] **Step 4: Commit**

```bash
git commit -am "chore: expand copier.yml to cover all template placeholders"
```

---

## Phase 11 — Local smoke test

### Task 11.1: Fresh-clone walkthrough

- [ ] **Step 1: Clone into a sibling directory and follow the README path verbatim**

```bash
cd /tmp
git clone -b chore/template-prep <path-to-this-repo> agent-gateway-smoke
cd agent-gateway-smoke
copier copy . . --vcs-ref HEAD --trust  # accept defaults
pip install -e .
pip install -e ".[dev]"
cp remote-gateway/.env.example remote-gateway/.env
# Fill in GITHUB_TOKEN + GITHUB_REPO with a throwaway test repo
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py &
SERVER_PID=$!
sleep 3
curl -s http://localhost:8000/health
kill $SERVER_PID
```

- [ ] **Step 2: Verify the seeded skill-creator skill is present**

```bash
sqlite3 remote-gateway/data/telemetry.db "SELECT name, is_system FROM skills;"
```
Expected: `skill-creator|1`

- [ ] **Step 3: Run the test suite**

```bash
pytest -q && ruff check .
```
Expected: all pass.

- [ ] **Step 4: Open the admin dashboard**

Open `http://localhost:8000/admin?token=change-me-admin-token` in a browser. Confirm tabs render, skill-creator appears in the Skills tab, no JS errors.

- [ ] **Step 5: Document any gaps in a follow-up file**

If anything is broken or unclear, write `docs/superpowers/notes/<date>-template-smoke-test.md` listing the gaps and stop. Do not push the branch until smoke test is clean.

---

## Phase 12 — Cleanup loose ends

### Task 12.1: Update CLAUDE.md memory file

This isn't a repo file — it's the auto-memory for the agent. After execution, save a memory note that template/clean-gateway is the active template branch and HubSpot is now an example entry rather than a separate variant.

- [ ] **Step 1: Skip until execution is approved.** This step is a reminder for post-execution.

### Task 12.2: Flag template/hubspot-gateway for deletion

- [ ] **Step 1: After the smoke test passes, surface to user**

Recommend deleting `template/hubspot-gateway` (both local and origin) since the HubSpot pre-wire now lives in `mcp_connections.example.json`. Do **not** delete unilaterally — confirm with user.

### Task 12.3: Note future work — n8n template variant

- [ ] **Step 1: Add a stub line to `AGENTS.md` or a TODO list**

Mention: "Future: a separate `template/n8n-gateway` variant is planned once the n8n integration on `feat/n8n-batch-integration` reaches MVP. It will be a sibling of `template/clean-gateway`, not the default."

---

## Self-review

**Spec coverage:** Each locked decision (1–12 in the brief) maps to a phase or task:
- Stay on branch (decision 1) → Phase 0 + Phase 12
- Drop hubspot template (decision 2) → Phase 6.2 (port to example) + Phase 12.2 (flag for deletion)
- n8n stays out (decision 3) → Phase 12.3
- Skill-creator implementation (decision 4) → Phases 4 + 5; verify endpoint covered in critical findings preamble
- Agent docs structure (decision 5) → Phase 6.1
- Light example config (decision 6) → Phase 6.2
- De-Inform (decision 7) → Phase 3
- README rewrite (decision 8) → Phase 7.1
- CLAUDE.md updates (decision 9) → Phases 7.2 + 7.3
- Delete conference-contact (decision 10) → Phase 2 (deletes the whole orphaned skills folder, which includes conference-contact)
- Audit GH Actions (decision 11) → Phase 8
- Node deps decision (decision 12) → Phase 9
- Unshallow + re-audit (first action) → completed before plan was written; findings in preamble

**Type consistency:** `seed_system_skills(telemetry, org_id, seed_file)` signature is consistent in Tasks 4.2 and 4.3. `create_system_skill(org_id, name, description, prompt_template)` consistent in Tasks 4.1 and `system_skills.py`. JSON schema `{name, description, prompt_template}` consistent across `system_skills.json` and the seeder.

**Placeholder scan:** No "TBD" / "TODO" / "implement later" — all steps are concrete. Code blocks present where code changes are made.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-05-template-branch-prep.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
