# Gateway Health Check Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `gateway-health-check` skill that guides a connected AI agent through probing every tool on the remote gateway — built-in and proxied — checking authentication, running smoke calls against field documentation, and writing structured issues to the GitHub notes repo.

**Architecture:** Add two new tools to `notes.py` (`write_issue`, `list_issues`) that target a `{NOTES_PATH}/issues/` subfolder. The skill itself is a `SKILL.md` in `remote-gateway/skills/gateway-health-check/` — a structured runbook the AI agent reads and executes step by step using live gateway tools.

**Tech Stack:** Python 3.14, FastMCP, httpx, PyYAML, GitHub Contents API; SKILL.md is Markdown read by the AI agent at runtime.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `remote-gateway/tools/notes.py` | Add `_issue_path`, `write_issue`, `list_issues`; update `register()` |
| Create | `remote-gateway/tests/test_issues.py` | Manual integration test for `write_issue` / `list_issues` |
| Create | `remote-gateway/skills/gateway-health-check/SKILL.md` | AI-agent runbook for health checking |

No changes to `mcp_server.py` — `notes.register(mcp)` already picks up everything added to `notes.py`.

---

## Task 1: Add `_issue_path` helper to `notes.py`

**Files:**
- Modify: `remote-gateway/tools/notes.py`

- [ ] **Step 1: Read the current file**

Open `remote-gateway/tools/notes.py`. Understand `_notes_path` — it uses `os.path.basename()` which strips directory prefixes. This is intentional for `write_note` (flat notes store). Issues need a subfolder, so we need a separate helper.

- [ ] **Step 2: Add `_issue_path` after `_notes_path`**

Insert after the `_notes_path` function (after line ~42):

```python
def _issue_path(slug: str) -> str:
    """Resolve a slug to its full repo path under the issues subfolder.

    Unlike _notes_path, this preserves the issues/ directory level.
    """
    notes_base = os.environ.get("NOTES_PATH", "notes")
    safe = os.path.basename(slug)
    if not safe.endswith(".md"):
        safe = safe + ".md"
    return f"{notes_base}/issues/{safe}"
```

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tools/notes.py
git commit -m "feat(notes): add _issue_path helper for issues subfolder"
```

---

## Task 2: Implement `write_issue` in `notes.py`

**Files:**
- Modify: `remote-gateway/tools/notes.py`

- [ ] **Step 1: Add `write_issue` after `delete_note`**

Insert before the `register()` function. The implementation mirrors `write_note` exactly but uses `_issue_path` instead of `_notes_path`:

```python
def write_issue(slug: str, content: str, commit_message: str = "") -> dict:
    """Create or update an issue note in the gateway's issues folder.

    Use this during gateway health checks to record problems found: authentication
    failures, missing field documentation, schema drift, or tool errors. Issues
    persist in {NOTES_PATH}/issues/ across redeployments.

    Args:
        slug: Short kebab-case identifier for the issue, without .md extension
            (e.g., "attio-auth-failure-2026-04-07", "exa-missing-docs").
        content: Full markdown content describing the issue, including context
            and recommended action.
        commit_message: Optional git commit message. Defaults to
            "chore: record issue <slug>".

    Returns:
        Dict confirming the commit with 'sha', 'slug', 'path', and 'commit_url'.
    """
    import httpx

    branch = os.environ.get("GITHUB_BRANCH", "main")
    path = _issue_path(slug)
    url = _github_file_url(path)
    base_name = os.path.basename(path)
    message = commit_message or f"chore: record issue {base_name}"

    sha: str | None = None
    with httpx.Client() as client:
        check = client.get(url, headers=_github_headers(), params={"ref": branch})
        if check.status_code == 200:
            sha = check.json()["sha"]

        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        resp = client.put(url, headers=_github_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    commit = result.get("commit", {})
    return {
        "status": "ok",
        "slug": slug,
        "path": path,
        "sha": commit.get("sha", ""),
        "commit_url": commit.get("html_url", ""),
        "action": "updated" if sha else "created",
    }
```

- [ ] **Step 2: Commit**

```bash
git add remote-gateway/tools/notes.py
git commit -m "feat(notes): add write_issue tool for issues subfolder"
```

---

## Task 3: Implement `list_issues` in `notes.py`

**Files:**
- Modify: `remote-gateway/tools/notes.py`

- [ ] **Step 1: Add `list_issues` after `write_issue`**

```python
def list_issues() -> dict:
    """List all open issue notes in the gateway's issues folder.

    Issues are written by the gateway-health-check skill when problems are
    found (auth failures, missing documentation, schema drift, tool errors).
    Use this to audit the current open issue backlog.

    Returns:
        Dict with 'issues' list (each entry has name, path, sha) and 'count'.
    """
    import httpx

    notes_base = os.environ.get("NOTES_PATH", "notes")
    repo = os.environ.get("GITHUB_REPO", "")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    url = _github_file_url(f"{notes_base}/issues")

    with httpx.Client() as client:
        resp = client.get(url, headers=_github_headers(), params={"ref": branch})

    if resp.status_code == 404:
        return {"issues": [], "count": 0, "message": "No issues folder yet — none recorded."}

    resp.raise_for_status()
    entries = resp.json()
    issues = [
        {"name": e["name"], "path": e["path"], "sha": e["sha"]}
        for e in entries
        if e["type"] == "file" and e["name"].endswith(".md")
    ]
    return {"issues": issues, "count": len(issues), "repo": repo, "branch": branch}
```

- [ ] **Step 2: Commit**

```bash
git add remote-gateway/tools/notes.py
git commit -m "feat(notes): add list_issues tool"
```

---

## Task 4: Register `write_issue` and `list_issues` in `notes.register()`

**Files:**
- Modify: `remote-gateway/tools/notes.py`

- [ ] **Step 1: Update `register()`**

Find the `register()` function (currently last in the file). Add the two new tools:

```python
def register(mcp: Any) -> None:
    """Register all notes tools on the given FastMCP server instance.

    Args:
        mcp: The FastMCP server instance (with telemetry patch already applied).
    """
    mcp.tool()(list_notes)
    mcp.tool()(read_note)
    mcp.tool()(write_note)
    mcp.tool()(delete_note)
    mcp.tool()(write_issue)
    mcp.tool()(list_issues)
```

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile remote-gateway/tools/notes.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tools/notes.py
git commit -m "feat(notes): register write_issue and list_issues on gateway"
```

---

## Task 5: Write integration test for `write_issue` / `list_issues`

**Files:**
- Create: `remote-gateway/tests/test_issues.py`

- [ ] **Step 1: Create the test file**

Model after `remote-gateway/tests/test_notes.py`. Tests run manually with live GitHub credentials:

```python
"""
Manual integration test for the issues subfolder tools.

Run with:
    GITHUB_TOKEN=... GITHUB_REPO=owner/repo .venv/bin/python remote-gateway/tests/test_issues.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


def run():
    from tools.notes import list_issues, write_issue

    print(f"Repo  : {os.environ['GITHUB_REPO']}")
    print(f"Branch: {os.environ.get('GITHUB_BRANCH', 'main')}")
    print()

    test_slug = "_test-issue"

    # ---- 1. write (create) ----
    print("=== write_issue() — create ===")
    content = "# Test Issue\n\n**Type:** test\n\n## Description\nCreated by test script."
    created = write_issue(test_slug, content, "test: create issue")
    print(created)
    assert created["action"] == "created", f"Expected 'created', got {created['action']}"
    assert "issues/" in created["path"], f"Expected issues/ in path, got {created['path']}"
    print()

    # ---- 2. list ----
    print("=== list_issues() ===")
    listed = list_issues()
    print(listed)
    names = [i["name"] for i in listed["issues"]]
    assert "_test-issue.md" in names, f"_test-issue.md not in {names}"
    print()

    # ---- 3. write (update) ----
    print("=== write_issue() — update ===")
    updated_content = "# Test Issue\n\n**Type:** test\n\n## Description\nUpdated by test script."
    updated = write_issue(test_slug, updated_content, "test: update issue")
    print(updated)
    assert updated["action"] == "updated", f"Expected 'updated', got {updated['action']}"
    print()

    # ---- 4. cleanup: overwrite with resolved marker ----
    print("=== write_issue() — mark resolved ===")
    resolved = write_issue(
        test_slug,
        "# Test Issue\n\n**Status:** RESOLVED\n\nTest complete.",
        "test: resolve test issue",
    )
    print(resolved)
    assert resolved["status"] == "ok"
    print()

    print("All assertions passed.")


if __name__ == "__main__":
    from dotenv import load_dotenv

    _repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
    load_dotenv(os.path.join(_repo_root, ".env"))

    for var in ("GITHUB_TOKEN", "GITHUB_REPO"):
        if not os.environ.get(var):
            print(f"ERROR: {var} is not set. Add it to .env or export it.")
            sys.exit(1)

    run()
```

- [ ] **Step 2: Run the integration test**

```bash
cd /path/to/repo
GITHUB_TOKEN=... GITHUB_REPO=owner/repo remote-gateway/.venv/bin/python remote-gateway/tests/test_issues.py
```

Expected: All assertions passed.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/tests/test_issues.py
git commit -m "test(notes): add integration test for write_issue and list_issues"
```

---

## Task 6: Write `SKILL.md` for gateway-health-check

**Files:**
- Create: `remote-gateway/skills/gateway-health-check/SKILL.md`

- [ ] **Step 1: Create the skill directory and file**

```bash
mkdir -p remote-gateway/skills/gateway-health-check
```

- [ ] **Step 2: Write the SKILL.md**

```markdown
---
name: gateway-health-check
description: Systematic probe of every tool on the remote gateway — built-in and proxied. Tests authentication, runs smoke calls, cross-checks responses against field documentation, and writes structured issues to the GitHub notes repo. Run this periodically or after any infrastructure change.
---

# Gateway Health Check

Run this skill whenever you need to verify the gateway is healthy: after a redeploy,
after adding new proxied integrations, or on a scheduled basis. Each finding is written
as a structured issue note to `{NOTES_PATH}/issues/`. A summary note goes to
`{NOTES_PATH}/gateway-health-{date}.md`.

---

## Phase 1 — Gateway Connectivity

**Goal:** Confirm the gateway itself is up and report the registered tool inventory.

1. Call `health_check()`. If it errors, stop — the gateway is not reachable.
   Record the error for manual investigation; do not proceed.

2. Call `get_tool_stats()` with no arguments. Save the returned `tools` list.
   This is your master inventory. You will work through it systematically in Phase 3.

3. Note which tools appear in the inventory. Proxied tools follow the pattern
   `{integration}__{tool_name}`. Extract unique integration prefixes
   (e.g., `attio`, `exa`, `apollo`, `github`) — these are your probe targets.

---

## Phase 2 — Field Documentation Audit

**Goal:** Confirm every proxied integration has field definitions in the registry.
Missing documentation is itself an issue — it means responses cannot be validated.

For each integration prefix identified in Phase 1:

1. Call `get_field_definitions(integration)`. A non-empty `fields` dict means
   docs exist. An empty dict means they are missing.

2. Call `list_field_integrations()` to see all registered integration slugs.
   Note: field docs may use compound slugs (e.g., `attio-companies`, `attio-deals`)
   rather than just the integration prefix. Check whether any slug starts with the
   integration prefix.

3. If **no field docs exist** for an integration, record it:
   - Slug: `{integration}-missing-docs-{YYYY-MM-DD}`
   - Write with `write_issue(slug, content)` using the template:

```
# Issue: {integration} — Missing Field Documentation

**Detected:** {YYYY-MM-DD}
**Integration:** {integration}
**Type:** missing_docs

## Description
No field definitions found in the registry for the `{integration}` integration.
Responses from `{integration}__*` tools cannot be validated for schema drift.

## Recommended Action
1. Make a representative smoke call to a `{integration}__*` tool.
2. Call `discover_fields("{integration}", response)` to auto-generate definitions.
3. Edit `remote-gateway/context/fields/{integration}.yaml` to fill in business descriptions.
4. Redeploy so the updated registry is active.
```

---

## Phase 3 — Proxied Integration Smoke Calls

**Goal:** Confirm each proxied integration authenticates and returns data.
Use the lightest available call — 1 result, minimal params.

Work through each integration prefix. For each one:

### 3a. Select the smoke call

Use the tool from the inventory that is most likely to succeed with minimal parameters.
Guidance by integration type:

**attio** → `attio__list_records` with `{"object_type": "companies", "limit": 1}`
  - If that tool is not in the inventory, use the first `attio__*` tool listed.

**exa** → Look for a `exa__search` or `exa__web_search` tool.
  Use `{"query": "gateway health check", "numResults": 1}` or equivalent.
  Check the tool's description for the exact parameter names.

**apollo** → Look for a `apollo__search_people` or `apollo__people_search` tool.
  Use `{"q_organization_domains": ["apollo.io"], "page": 1, "per_page": 1}`
  or the minimal params shown in the tool description.

**github** → `github__search_repositories` with `{"query": "stars:>1000", "page": 1}`
  or `github__list_files_in_repo` with `{"repo": repo_slug, "path": "/"}`.

**Unknown integration** → Use the first tool listed for that prefix with no required
  parameters (check the tool description), or the simplest read operation.

### 3b. Make the call and evaluate

Call the smoke tool. Then:

**If the call raises an error or returns an error field:**

- Determine if it is an auth error (contains "401", "403", "unauthorized", "invalid key",
  "token", "credentials") or a connectivity/config error.
- Write an issue:
  - Slug: `{integration}-{auth|error}-{YYYY-MM-DD}`
  - Template:

```
# Issue: {integration} — {Auth Failure | Tool Error}

**Detected:** {YYYY-MM-DD}
**Integration:** {integration}
**Type:** {auth_failure | tool_error}

## Tool Call
- Tool: `{tool_name}`
- Args: `{args_as_json}`

## Error
```
{full error message}
```

## Recommended Action
{For auth: Check that the relevant env var is set on the gateway and not expired.
 For tool_error: Check the integration's upstream service status.
 Include the specific env var names from mcp_connections.json if known.}
```

**If the call succeeds:**

- You have a live response. Proceed to 3c.

### 3c. Validate against field documentation

Take the response dict. For each field doc slug that starts with the integration prefix
(e.g., `attio-companies` for the `attio` integration):

1. Call `check_field_drift("{doc_slug}", response)`.
   - If `has_drift` is true: write a drift issue (slug: `{integration}-schema-drift-{date}`):

```
# Issue: {integration} — Schema Drift Detected

**Detected:** {YYYY-MM-DD}
**Integration:** {integration}
**Type:** schema_drift
**Field Doc:** {doc_slug}

## Drift Report
- New fields (not in registry): {new_fields}
- Removed fields (in registry but absent from response): {removed_fields}

## Tool Call Used for Sample
- Tool: `{tool_name}`
- Args: `{args}`

## Recommended Action
1. Call `discover_fields("{doc_slug}", response)` to add new fields to the registry.
2. Review removed fields — remove from YAML if the integration no longer returns them.
3. Redeploy to sync the registry.
```

   - If `has_drift` is false: note "no drift" in the summary (no issue written).

2. If no field doc exists for this integration (confirmed in Phase 2): call
   `discover_fields("{integration}", response)` to auto-generate a skeleton YAML.
   Note in the summary that docs were auto-generated and need human enrichment.

---

## Phase 4 — Built-In Tool Spot Checks

**Goal:** Verify the internal gateway tools are functional.

1. **Notes tool** — Call `list_notes()`. If it returns an error (not a 404/empty list),
   write an issue: `notes-tool-error-{date}` with the error message and note that
   `GITHUB_TOKEN` and `GITHUB_REPO` env vars should be checked.

2. **Registry tool** — Call `list_field_integrations()`. If it errors, write an issue:
   `registry-tool-error-{date}`. If it returns an empty list but Phase 1 showed proxied
   integrations, note that the field registry may not have been populated.

3. **Telemetry** — From the `get_tool_stats()` result saved in Phase 1, check
   `summary.high_error_rate`. If any tools appear there, write a single issue:
   `high-error-rate-tools-{date}` listing each tool, its error rate, and call count.

---

## Phase 5 — Write Summary Report

After all phases are complete, write a summary note (not an issue) using `write_note`:

- Filename: `gateway-health-{YYYY-MM-DD}`
- Content template:

```markdown
# Gateway Health Check — {YYYY-MM-DD}

## Result: {PASS | PASS WITH WARNINGS | FAIL}

**Gateway status:** {ok | unreachable}
**Integrations tested:** {N}
**Issues written:** {N}

## Integration Status

| Integration | Smoke Call | Auth | Field Docs | Schema Drift |
|-------------|-----------|------|------------|--------------|
| attio       | {ok|fail} | {ok|fail} | {ok|missing} | {none|drift} |
| exa         | ...       | ...  | ...        | ...          |
| apollo      | ...       | ...  | ...        | ...          |
| github      | ...       | ...  | ...        | ...          |

## Issues Written

{List each issue slug and one-line description, or "None" if clean.}

## Built-In Tools

- Notes: {ok | error}
- Registry: {ok | error}
- Telemetry high-error tools: {none | list}
```

---

## Issue Slug Naming Convention

| Problem | Slug format |
|---------|-------------|
| Auth/credential failure | `{integration}-auth-failure-{YYYY-MM-DD}` |
| Tool call error (non-auth) | `{integration}-tool-error-{YYYY-MM-DD}` |
| Missing field docs | `{integration}-missing-docs-{YYYY-MM-DD}` |
| Schema drift detected | `{integration}-schema-drift-{YYYY-MM-DD}` |
| High error rate tools | `high-error-rate-tools-{YYYY-MM-DD}` |
| Built-in tool failure | `{tool_name}-error-{YYYY-MM-DD}` |

If two issues of the same type exist for one date, append `-2`, `-3`, etc.

---

## When to Stop Early

- If `health_check()` fails → stop, write no issues (gateway is unreachable, not individual tool failures)
- If `write_issue` itself fails → record issues in your response text; note that the notes repo may be misconfigured
- If an integration has zero tools in the inventory → skip it; the proxy failed at startup (will show in gateway logs)
```

- [ ] **Step 3: Verify the file was created**

```bash
cat remote-gateway/skills/gateway-health-check/SKILL.md | head -5
```

Expected: first 5 lines of the frontmatter.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/skills/gateway-health-check/SKILL.md
git commit -m "feat(skills): add gateway-health-check skill"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task(s) |
|-------------|---------|
| Test proxied MCP connections | Phase 3 (SKILL.md) |
| Test authentication | Phase 3b (SKILL.md) |
| Write issues to GitHub notes issues folder | Tasks 1–4 (`write_issue` tool) + Phase 3b/3c |
| Pull in field documentation per tool | Phase 2 + 3c (SKILL.md) |
| Flag missing documentation as an issue | Phase 2 (SKILL.md) |
| Flag errors vs documentation as an issue | Phase 3c — drift check (SKILL.md) |
| Field context (context/fields/*.yaml) as documentation | Explicit in Phase 2/3c |
| Tool call info / telemetry | Phase 4 (high_error_rate check) |

**Placeholder scan:** No TBDs found. All issue templates are fully written out.

**Type consistency:** `write_issue(slug, content, commit_message)` signature used consistently in SKILL.md and Task 2 implementation. `list_issues()` return shape matches `list_notes()` pattern.
