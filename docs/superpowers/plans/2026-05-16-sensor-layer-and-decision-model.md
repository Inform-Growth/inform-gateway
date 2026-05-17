# Sensor Layer & Decision Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `report_issue`/`list_my_issues` (real GitHub Issues on deployment repo), deprecate `write_issue`/`list_issues`, and extend `declare_intent` with decision context fields, a clarity push-back, and shadow-operating instructions injected at task creation time.

**Architecture:** `report_issue` uses the GitHub Issues API against `INFORM_GATEWAY_DEPLOYMENT_REPO` (a separate repo from the notes `GITHUB_REPO`) and soft-fails on API errors without interrupting the parent task. `declare_intent` gains three optional fields (`decision_context`, `decision_type`, `stakes_hint`) stored via SQLite migrations, always injects `shadow_operating_instructions` into its response, and emits a `clarity_warning` when the goal is too vague. `write_issue`/`list_issues` are unregistered from the MCP tool registry but kept in `notes.py` temporarily with deprecation notices.

**Tech Stack:** Python 3.11+, httpx (already a dependency), SQLite via TelemetryStore, pytest + unittest.mock for tests.

**Spec:** `docs/superpowers/specs/2026-05-16-sensor-layer-and-decision-model-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `remote-gateway/tools/notes.py` | Modify | Deprecate `write_issue`/`list_issues`; add `_deployment_repo_headers`, `_deployment_issue_url`, `_format_issue_body`, `report_issue`, `list_my_issues` |
| `remote-gateway/core/telemetry.py` | Modify | Add migrations for `decision_context`, `decision_type`, `stakes_hint` on `tasks`; update `create_task`, `get_task`, `list_active_tasks` |
| `remote-gateway/tools/_core/task_manager.py` | Modify | Add `_check_goal_clarity`, `_SHADOW_OPERATING_INSTRUCTIONS` constant; update `declare_intent` signature and response |
| `remote-gateway/prompts/init.md` | Modify | Replace `write_issue` references with `report_issue`; add shadow-issue-filing clause |
| `remote-gateway/.env.example` | Modify | Add `INFORM_GATEWAY_DEPLOYMENT_REPO`, `INFORM_GATEWAY_GITHUB_TOKEN`, `INFORM_GATEWAY_REPORT_ISSUE_DISABLED` |
| `copier.yml` | Modify | Add `deployment_repo` question |
| `remote-gateway/tests/test_report_issue.py` | Create | Unit tests for `report_issue` and `list_my_issues` using mocked httpx |
| `remote-gateway/tests/test_task_manager.py` | Modify | Add tests for new `declare_intent` fields, clarity warning, shadow instructions |
| `remote-gateway/tests/test_issues.py` | Modify | Update to reflect `write_issue`/`list_issues` are unregistered |

---

## Task 1: Deprecate `write_issue` and `list_issues`

**Files:**
- Modify: `remote-gateway/tools/notes.py:309-320` (register function)
- Modify: `remote-gateway/tools/notes.py:222-306` (docstrings)

- [ ] **Step 1: Unregister `write_issue` and `list_issues` from `notes.register()`**

In `remote-gateway/tools/notes.py`, find the `register` function (currently lines 309–320) and remove the two deprecated registrations:

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
    # write_issue and list_issues are intentionally NOT registered here.
    # They are deprecated — use report_issue and list_my_issues instead.
```

- [ ] **Step 2: Add deprecation notices to `write_issue` and `list_issues` docstrings**

Update the `write_issue` docstring (line 222):

```python
def write_issue(slug: str, content: str, commit_message: str = "") -> dict:
    """DEPRECATED. Use report_issue instead.

    write_issue wrote markdown files to the notes repo under notes/issues/.
    All issue creation now goes to real GitHub Issues on the deployment repo
    via report_issue. This function is unregistered and kept temporarily
    for reference until existing notes/issues/ files are archived.
    """
```

Update the `list_issues` docstring (line 276):

```python
def list_issues() -> dict:
    """DEPRECATED. Use list_my_issues instead.

    list_issues listed markdown files from the notes repo issues folder.
    All issue listing now goes through list_my_issues, which reads real
    GitHub Issues from the deployment repo. This function is unregistered.
    """
```

- [ ] **Step 3: Update `test_issues.py` to reflect the deprecation**

Replace the content of `remote-gateway/tests/test_issues.py`:

```python
"""
write_issue and list_issues are deprecated and unregistered.
Use report_issue and list_my_issues instead.

This file is kept as a reference. See test_report_issue.py for the
replacement tests.
"""
```

- [ ] **Step 4: Verify the server starts without error and the old tools don't appear**

```bash
cd remote-gateway && python -c "
import sys; sys.path.insert(0, 'core'); sys.path.insert(0, '.')
from tools.notes import register
tools = {}
class _MCP:
    def tool(self):
        def d(fn): tools[fn.__name__] = fn; return fn
        return d
register(_MCP())
assert 'write_issue' not in tools, 'write_issue should not be registered'
assert 'list_issues' not in tools, 'list_issues should not be registered'
print('OK — write_issue and list_issues are not registered')
"
```

Expected output: `OK — write_issue and list_issues are not registered`

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/notes.py remote-gateway/tests/test_issues.py
git commit -m "deprecate: unregister write_issue and list_issues in favor of report_issue"
```

---

## Task 2: Add `report_issue` (TDD)

**Files:**
- Modify: `remote-gateway/tools/notes.py`
- Create: `remote-gateway/tests/test_report_issue.py`

- [ ] **Step 1: Write the failing tests for `report_issue`**

Create `remote-gateway/tests/test_report_issue.py`:

```python
"""Tests for report_issue and list_my_issues in tools/notes.py."""
from __future__ import annotations
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


@pytest.fixture(autouse=True)
def deployment_env(monkeypatch):
    monkeypatch.setenv("INFORM_GATEWAY_DEPLOYMENT_REPO", "Inform-Growth/test-deployment")
    monkeypatch.setenv("INFORM_GATEWAY_GITHUB_TOKEN", "ghp_test")
    monkeypatch.delenv("INFORM_GATEWAY_REPORT_ISSUE_DISABLED", raising=False)


def _make_issue_response(number: int = 42, title: str = "Test issue") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {
        "number": number,
        "html_url": f"https://github.com/Inform-Growth/test-deployment/issues/{number}",
    }
    resp.raise_for_status = MagicMock()
    return resp


def test_report_issue_returns_issue_url():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _make_issue_response(number=42)

        result = report_issue(
            title="Apollo returns empty for happy-path query",
            task_id="task-abc123",
            attempted_action="Search Apollo for VP Engineering at Series B companies",
            observed_failure="apollo__search_people returned empty results for a query that should match 50+ contacts",
            agent_hypothesis="The seniority filter may be case-sensitive; tried 'VP' but API may expect 'vp'",
            suggested_category="bug",
            severity="p2",
            related_tool="apollo",
        )

    assert result["issue_number"] == 42
    assert "github.com" in result["issue_url"]
    assert "type:bug" in result["labels"]
    assert "priority:p2" in result["labels"]
    assert "source:report_issue" in result["labels"]
    assert "tool:apollo" in result["labels"]


def test_report_issue_posts_to_correct_repo():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _make_issue_response()

        report_issue(
            title="Test",
            task_id="task-abc",
            attempted_action="x",
            observed_failure="y",
            agent_hypothesis="z",
            suggested_category="bug",
        )

        call_args = mock_client.post.call_args
        url = call_args[0][0]
        assert "Inform-Growth/test-deployment" in url
        assert url.endswith("/issues")


def test_report_issue_body_contains_task_id():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _make_issue_response()

        report_issue(
            title="Test",
            task_id="task-xyz999",
            attempted_action="looked up contact",
            observed_failure="got 400",
            agent_hypothesis="bad field name",
            suggested_category="bug",
        )

        payload = mock_client.post.call_args[1]["json"]
        assert "task-xyz999" in payload["body"]


def test_report_issue_soft_fails_on_github_error():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("GitHub is down")

        result = report_issue(
            title="Test",
            task_id="task-abc",
            attempted_action="x",
            observed_failure="y",
            agent_hypothesis="z",
            suggested_category="bug",
        )

    assert "error" in result
    assert result.get("logged_to_task") == "task-abc"


def test_report_issue_kill_switch(monkeypatch):
    monkeypatch.setenv("INFORM_GATEWAY_REPORT_ISSUE_DISABLED", "true")
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        result = report_issue(
            title="Test",
            task_id="task-abc",
            attempted_action="x",
            observed_failure="y",
            agent_hypothesis="z",
            suggested_category="bug",
        )
        mock_client_cls.assert_not_called()

    assert result.get("status") == "disabled"


def test_report_issue_no_tool_label_when_related_tool_absent():
    from tools.notes import report_issue

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _make_issue_response()

        result = report_issue(
            title="Test",
            task_id="task-abc",
            attempted_action="x",
            observed_failure="y",
            agent_hypothesis="z",
            suggested_category="ux",
        )

    assert not any(l.startswith("tool:") for l in result["labels"])
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd remote-gateway && python -m pytest tests/test_report_issue.py -v 2>&1 | head -30
```

Expected: `ImportError` or `AttributeError` — `report_issue` doesn't exist yet.

- [ ] **Step 3: Implement the helper functions and `report_issue` in `notes.py`**

Add after the existing `_issue_path` function and before `list_notes` in `remote-gateway/tools/notes.py`:

```python
def _deployment_repo_headers() -> dict[str, str]:
    """Return GitHub API headers using INFORM_GATEWAY_GITHUB_TOKEN."""
    token = os.environ.get("INFORM_GATEWAY_GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _deployment_issue_url() -> str:
    """Return the GitHub Issues API URL for the deployment repo."""
    repo = os.environ.get("INFORM_GATEWAY_DEPLOYMENT_REPO", "")
    return f"https://api.github.com/repos/{repo}/issues"


def _format_issue_body(
    task_id: str,
    attempted_action: str,
    observed_failure: str,
    agent_hypothesis: str,
    suggested_fix: str | None,
    related_tool: str | None,
) -> str:
    """Render the standard issue body markdown."""
    return (
        f"**Task ID:** {task_id}\n"
        f"**Reported by:** agent (shadow-operating)\n"
        f"**Related tool:** {related_tool or 'n/a'}\n\n"
        f"## What the agent was trying to do\n{attempted_action}\n\n"
        f"## What actually happened\n{observed_failure}\n\n"
        f"## Agent hypothesis\n{agent_hypothesis}\n\n"
        f"## Suggested fix\n{suggested_fix or 'none'}\n\n"
        "---\n"
        "*Filed automatically via `report_issue` during task execution. "
        "See task audit trail for full context.*"
    )
```

Then add `report_issue` after `_format_issue_body`:

```python
_CATEGORY_LABELS: dict[str, str] = {
    "bug": "type:bug",
    "feature": "type:feature",
    "integration": "type:integration",
    "recommendation": "type:recommendation",
    "ux": "type:ux",
    "data-quality": "type:data-quality",
}


def report_issue(
    title: str,
    task_id: str,
    attempted_action: str,
    observed_failure: str,
    agent_hypothesis: str,
    suggested_category: str,
    severity: str = "p3",
    suggested_fix: str | None = None,
    related_tool: str | None = None,
) -> dict:
    """File a GitHub Issue on the deployment repo as part of shadow operating.

    Invoked by agents during task execution when they encounter friction.
    Not user-facing — the user never sees this call in conversation.

    Two triggers: (1) FRICTION — agent would otherwise ask the user for help;
    (2) EFFICIENCY — a subtask required more than 2 tool calls to accomplish
    what should be one, including retries and compensating calls.

    Args:
        title: One-line summary of the friction.
        task_id: The active task_id from declare_intent.
        attempted_action: What the agent was trying to do (1-2 sentences).
        observed_failure: What actually happened, including any error text.
        agent_hypothesis: The agent's best guess at the underlying problem.
        suggested_category: One of bug, feature, integration, recommendation, ux, data-quality.
        severity: p1 (blocked user outcome), p2 (degraded), p3 (inefficient). Default p3.
        suggested_fix: Optional concrete fix suggestion.
        related_tool: Integration name if friction is tool-specific (e.g. "attio", "apollo").

    Returns:
        Dict with issue_url, issue_number, labels on success.
        Dict with error, logged_to_task on GitHub API failure (soft-fail).
        Dict with status="disabled" when kill switch is active.
    """
    import httpx

    if os.environ.get("INFORM_GATEWAY_REPORT_ISSUE_DISABLED", "").lower() == "true":
        return {"status": "disabled", "task_id": task_id}

    labels = [
        _CATEGORY_LABELS.get(suggested_category, "type:bug"),
        f"priority:{severity}",
        "source:report_issue",
    ]
    if related_tool:
        labels.append(f"tool:{related_tool}")

    body = _format_issue_body(
        task_id=task_id,
        attempted_action=attempted_action,
        observed_failure=observed_failure,
        agent_hypothesis=agent_hypothesis,
        suggested_fix=suggested_fix,
        related_tool=related_tool,
    )

    try:
        with httpx.Client() as client:
            resp = client.post(
                _deployment_issue_url(),
                headers=_deployment_repo_headers(),
                json={"title": title, "body": body, "labels": labels},
            )
        resp.raise_for_status()
        data = resp.json()
        return {
            "issue_number": data["number"],
            "issue_url": data["html_url"],
            "labels": labels,
        }
    except Exception as exc:
        return {"error": str(exc), "logged_to_task": task_id}
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd remote-gateway && python -m pytest tests/test_report_issue.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/notes.py remote-gateway/tests/test_report_issue.py
git commit -m "feat: add report_issue with GitHub Issues API and soft-fail error handling"
```

---

## Task 3: Add `list_my_issues`

**Files:**
- Modify: `remote-gateway/tools/notes.py`
- Modify: `remote-gateway/tests/test_report_issue.py`

- [ ] **Step 1: Write the failing tests for `list_my_issues`**

Append to `remote-gateway/tests/test_report_issue.py`:

```python
def test_list_my_issues_returns_open_issues():
    from tools.notes import list_my_issues

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "number": 7,
            "title": "Apollo empty results",
            "labels": [{"name": "type:bug"}, {"name": "priority:p2"}],
            "state": "open",
            "created_at": "2026-05-16T10:00:00Z",
            "html_url": "https://github.com/Inform-Growth/test-deployment/issues/7",
        }
    ]
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        result = list_my_issues(state="open", limit=20)

    assert len(result) == 1
    assert result[0]["issue_number"] == 7
    assert result[0]["title"] == "Apollo empty results"
    assert "type:bug" in result[0]["labels"]


def test_list_my_issues_passes_state_and_label_params():
    from tools.notes import list_my_issues

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        list_my_issues(state="closed", label="type:bug", limit=5)

        params = mock_client.get.call_args[1]["params"]
        assert params["state"] == "closed"
        assert params["labels"] == "type:bug"
        assert params["per_page"] == 5
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd remote-gateway && python -m pytest tests/test_report_issue.py::test_list_my_issues_returns_open_issues -v
```

Expected: `ImportError` — `list_my_issues` doesn't exist yet.

- [ ] **Step 3: Implement `list_my_issues` in `notes.py`**

Add after `report_issue`:

```python
def list_my_issues(
    state: str = "open",
    label: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List issues on the deployment repo.

    Internal observability for CS operators and the fleet operator agent.
    Not user-facing. Reads from INFORM_GATEWAY_DEPLOYMENT_REPO.

    Args:
        state: Filter by issue state — "open", "closed", or "all".
        label: Optional label name to filter by (e.g. "type:bug", "tool:attio").
        limit: Maximum number of issues to return (default 20).

    Returns:
        List of dicts with issue_number, title, labels (list of name strings),
        state, created_at, and html_url.
    """
    import httpx

    params: dict[str, Any] = {"state": state, "per_page": limit}
    if label:
        params["labels"] = label

    with httpx.Client() as client:
        resp = client.get(
            _deployment_issue_url(),
            headers=_deployment_repo_headers(),
            params=params,
        )
    resp.raise_for_status()
    return [
        {
            "issue_number": issue["number"],
            "title": issue["title"],
            "labels": [lb["name"] for lb in issue.get("labels", [])],
            "state": issue["state"],
            "created_at": issue["created_at"],
            "html_url": issue["html_url"],
        }
        for issue in resp.json()
    ]
```

- [ ] **Step 4: Run all report_issue tests**

```bash
cd remote-gateway && python -m pytest tests/test_report_issue.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Register both new tools in `notes.register()`**

Update the `register` function in `notes.py`:

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
    mcp.tool()(report_issue)
    mcp.tool()(list_my_issues)
    # write_issue and list_issues are intentionally NOT registered here.
    # They are deprecated — use report_issue and list_my_issues instead.
```

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/notes.py remote-gateway/tests/test_report_issue.py
git commit -m "feat: add list_my_issues and register report_issue + list_my_issues"
```

---

## Task 4: Add env vars and copier question

**Files:**
- Modify: `remote-gateway/.env.example`
- Modify: `copier.yml`

- [ ] **Step 1: Add the three new env vars to `.env.example`**

Find the GitHub section in `.env.example` and extend it:

```bash
# GitHub (required for notes tools)
# GITHUB_TOKEN=github_pat_...
# GITHUB_REPO=owner/repo
# GITHUB_BRANCH=main
# NOTES_PATH=notes

# GitHub — deployment repo (required for report_issue / list_my_issues)
# Separate from GITHUB_REPO (the notes repo). This is the repo that receives
# real GitHub Issues filed by agents during task execution.
# INFORM_GATEWAY_DEPLOYMENT_REPO=Inform-Growth/your-client-gateway
# INFORM_GATEWAY_GITHUB_TOKEN=github_pat_...  (needs issues:write on deployment repo)
# INFORM_GATEWAY_REPORT_ISSUE_DISABLED=false  # set to "true" to disable issue filing
```

- [ ] **Step 2: Add the `deployment_repo` question to `copier.yml`**

Append to the `questions:` block in `copier.yml`:

```yaml
  deployment_repo:
    type: str
    help: "GitHub repo where agents file issues (owner/repo, e.g. 'Inform-Growth/acme-gateway')"
    default: "[[ github_org ]]/[[ project_slug ]]"
```

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/.env.example copier.yml
git commit -m "chore: add INFORM_GATEWAY_DEPLOYMENT_REPO env vars and copier question"
```

---

## Task 5: Add task DB migrations for decision fields

**Files:**
- Modify: `remote-gateway/core/telemetry.py`

- [ ] **Step 1: Write failing tests for the new columns**

Append to `remote-gateway/tests/test_task_manager.py`:

```python
def test_create_task_stores_decision_fields(store):
    task = store.create_task(
        "alice", "acme",
        "Evaluate renewal terms for Acme account",
        ["pull usage data", "check deal history"],
        decision_context="Should we extend renewal terms for Acme",
        decision_type="decision",
        stakes_hint="high",
    )
    fetched = store.get_task(task["task_id"])
    assert fetched["decision_context"] == "Should we extend renewal terms for Acme"
    assert fetched["decision_type"] == "decision"
    assert fetched["stakes_hint"] == "high"


def test_create_task_decision_fields_nullable(store):
    task = store.create_task("alice", "acme", "Pull weekly pipeline report", [])
    fetched = store.get_task(task["task_id"])
    assert fetched["decision_context"] is None
    assert fetched["decision_type"] is None
    assert fetched["stakes_hint"] is None


def test_list_active_tasks_includes_decision_fields(store):
    store.create_task(
        "alice", "acme", "Evaluate Acme renewal", [],
        decision_type="decision", stakes_hint="high",
    )
    tasks = store.list_active_tasks("alice")
    assert tasks[0]["decision_type"] == "decision"
    assert tasks[0]["stakes_hint"] == "high"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd remote-gateway && python -m pytest tests/test_task_manager.py::test_create_task_stores_decision_fields -v
```

Expected: `TypeError` — `create_task` doesn't accept the new kwargs yet.

- [ ] **Step 3: Add the three migrations to `_MIGRATIONS` in `telemetry.py`**

Find `_MIGRATIONS` (around line 160) and append:

```python
_MIGRATIONS = [
    ("tool_calls", "user_id",          "TEXT"),
    ("tool_calls", "request_id",       "TEXT"),
    ("tool_calls", "response_size",    "INTEGER"),
    ("tool_calls", "input_body",       "TEXT"),
    ("tool_calls", "error_message",    "TEXT"),
    ("tool_calls", "response_preview", "TEXT"),
    ("api_keys", "org_id",             "TEXT"),
    ("tool_calls", "task_id",          "TEXT"),
    # Decision model fields — captured at declare_intent time for the loom
    ("tasks", "decision_context",      "TEXT"),
    ("tasks", "decision_type",         "TEXT"),
    ("tasks", "stakes_hint",           "TEXT"),
]
```

- [ ] **Step 4: Update `create_task` signature and SQL**

Replace the `create_task` method (around line 1110):

```python
def create_task(
    self,
    user_id: str,
    org_id: str,
    goal: str,
    steps: list[str],
    decision_context: str | None = None,
    decision_type: str | None = None,
    stakes_hint: str | None = None,
) -> dict:
    """Create a new active task and return it.

    Args:
        user_id: The user declaring intent.
        org_id: The user's organization.
        goal: What the agent is trying to accomplish.
        steps: Planned tool call sequence (list of strings).
        decision_context: Free text describing what decision this task feeds.
        decision_type: One of "decision", "process", "exploration".
        stakes_hint: Operator's estimate — "high", "medium", or "low".

    Returns:
        Task dict with task_id, user_id, org_id, goal, steps, status,
        created_at, decision_context, decision_type, stakes_hint.
        Returns {} if telemetry is disabled or the write failed.
    """
    import json as _json
    import secrets as _secrets
    task_id = f"task-{_secrets.token_hex(8)}"
    now = time.time()
    if not self._enabled:
        return {}
    try:
        conn = self._connect()
        conn.execute(
            "INSERT INTO tasks "
            "(task_id, user_id, org_id, goal, steps, status, created_at,"
            " decision_context, decision_type, stakes_hint)"
            " VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)",
            (task_id, user_id, org_id, goal, _json.dumps(steps), now,
             decision_context, decision_type, stakes_hint),
        )
        conn.commit()
        return {
            "task_id": task_id,
            "user_id": user_id,
            "org_id": org_id,
            "goal": goal,
            "steps": steps,
            "status": "active",
            "created_at": now,
            "decision_context": decision_context,
            "decision_type": decision_type,
            "stakes_hint": stakes_hint,
        }
    except Exception:
        return {}
```

- [ ] **Step 5: Update `get_task` to include new columns**

Replace the entire `get_task` method (around line 1155) with:

```python
def get_task(self, task_id: str) -> dict | None:
    """Return a task by ID, or None if not found.

    Args:
        task_id: Task identifier.
    """
    import json as _json
    if not self._enabled:
        return None
    try:
        conn = self._connect()
        row = conn.execute(
            "SELECT task_id, user_id, org_id, goal, steps, status, outcome,"
            " created_at, completed_at, decision_context, decision_type, stakes_hint"
            " FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "task_id": row["task_id"],
            "user_id": row["user_id"],
            "org_id": row["org_id"],
            "goal": row["goal"],
            "steps": _json.loads(row["steps"] or "[]"),
            "status": row["status"],
            "outcome": row["outcome"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "decision_context": row["decision_context"],
            "decision_type": row["decision_type"],
            "stakes_hint": row["stakes_hint"],
        }
    except Exception:
        return None
```

- [ ] **Step 6: Update `list_active_tasks` to include new columns**

Replace the entire `list_active_tasks` method (around line 1259) with:

```python
def list_active_tasks(self, user_id: str) -> list[dict]:
    """Return all active tasks for a user, newest first.

    Args:
        user_id: User to query.
    """
    import json as _json
    if not self._enabled:
        return []
    try:
        conn = self._connect()
        rows = conn.execute(
            "SELECT task_id, user_id, org_id, goal, steps, status,"
            " created_at, decision_context, decision_type, stakes_hint"
            " FROM tasks WHERE user_id = ? AND status = 'active'"
            " ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "user_id": row["user_id"],
                "org_id": row["org_id"],
                "goal": row["goal"],
                "steps": _json.loads(row["steps"] or "[]"),
                "status": row["status"],
                "created_at": row["created_at"],
                "decision_context": row["decision_context"],
                "decision_type": row["decision_type"],
                "stakes_hint": row["stakes_hint"],
            }
            for row in rows
        ]
    except Exception:
        return []
```

- [ ] **Step 7: Run the task manager tests**

```bash
cd remote-gateway && python -m pytest tests/test_task_manager.py -v
```

Expected: all existing tests plus the 3 new ones pass.

- [ ] **Step 8: Commit**

```bash
git add remote-gateway/core/telemetry.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: add decision_context, decision_type, stakes_hint columns to tasks table"
```

---

## Task 6: Add goal clarity check

**Files:**
- Modify: `remote-gateway/tools/_core/task_manager.py`
- Modify: `remote-gateway/tests/test_task_manager.py`

- [ ] **Step 1: Write failing tests for `_check_goal_clarity`**

Append to `remote-gateway/tests/test_task_manager.py`:

```python
def test_clarity_check_passes_specific_goal():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity(
        "Search Attio for Series B companies in Vancouver with more than 50 employees"
    )
    assert result is None


def test_clarity_check_fails_short_goal():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity("Look into it")
    assert result is not None
    assert "clarity_warning" in result or "message" in result


def test_clarity_check_fails_vague_phrase():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity("Help with the prospecting list we discussed")
    assert result is not None


def test_clarity_check_fails_under_six_words():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity("Do some research now")
    assert result is not None


def test_clarity_check_passes_process_goal():
    from tools._core.task_manager import _check_goal_clarity
    result = _check_goal_clarity(
        "Run the weekly pipeline enrichment job for all open opportunities in Attio"
    )
    assert result is None
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd remote-gateway && python -m pytest tests/test_task_manager.py::test_clarity_check_passes_specific_goal -v
```

Expected: `ImportError` — `_check_goal_clarity` doesn't exist yet.

- [ ] **Step 3: Implement `_check_goal_clarity` in `task_manager.py`**

Add before the `register` function in `remote-gateway/tools/_core/task_manager.py`:

```python
_VAGUE_PHRASES: tuple[str, ...] = (
    "help with",
    "look into",
    "do some research",
    "figure out",
    "check on",
    "work on",
    "deal with",
    "handle",
    "take a look",
)

_CLARITY_EXAMPLES: list[str] = [
    "Search Attio for companies in Series B with >50 employees to support the 'expand West Coast outbound' decision",
    "Pull Apollo enrichment for the 12 prospects on the Vancouver cold-call list — process task, no decision",
    "Evaluate renewal terms for Acme account — decision with high stakes, context: 3-year vs 1-year tradeoff",
]


def _check_goal_clarity(goal: str) -> dict | None:
    """Return a clarity_warning dict if the goal is too vague, else None.

    A goal is considered vague if:
    1. It is fewer than 6 words, OR
    2. It contains a known vague phrase.

    Returns None when the goal is clear enough. Does not block task creation.
    """
    words = goal.strip().split()
    if len(words) < 6:
        return {
            "message": (
                "Goal is too short to attribute to a decision or measure impact. "
                "Describe: what you're looking for, in which system, and why."
            ),
            "examples": _CLARITY_EXAMPLES,
        }
    lower = goal.lower()
    for phrase in _VAGUE_PHRASES:
        if phrase in lower:
            return {
                "message": (
                    f"Goal contains a vague phrase ('{phrase}'). "
                    "Consider describing the specific object, system, and decision context."
                ),
                "examples": _CLARITY_EXAMPLES,
            }
    return None
```

- [ ] **Step 4: Run the clarity check tests**

```bash
cd remote-gateway && python -m pytest tests/test_task_manager.py::test_clarity_check_passes_specific_goal tests/test_task_manager.py::test_clarity_check_fails_short_goal tests/test_task_manager.py::test_clarity_check_fails_vague_phrase tests/test_task_manager.py::test_clarity_check_fails_under_six_words tests/test_task_manager.py::test_clarity_check_passes_process_goal -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/tools/_core/task_manager.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: add _check_goal_clarity with vague-phrase and word-count detection"
```

---

## Task 7: Update `declare_intent` with decision fields, clarity warning, shadow instructions

**Files:**
- Modify: `remote-gateway/tools/_core/task_manager.py`
- Modify: `remote-gateway/tests/test_task_manager.py`

- [ ] **Step 1: Write the failing tests**

Append to `remote-gateway/tests/test_task_manager.py`:

```python
def test_declare_intent_includes_shadow_operating_instructions(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Search Attio for Series B companies in Vancouver with over 50 employees",
        ["search attio"],
    )
    assert "shadow_operating_instructions" in result
    assert "report_issue" in result["shadow_operating_instructions"]
    assert "FRICTION" in result["shadow_operating_instructions"]
    assert "EFFICIENCY" in result["shadow_operating_instructions"]


def test_declare_intent_emits_clarity_warning_for_vague_goal(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"]("Help with things", [])
    assert "task_id" in result  # task still created
    assert "clarity_warning" in result
    assert "message" in result["clarity_warning"]


def test_declare_intent_no_clarity_warning_for_specific_goal(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Pull Apollo enrichment for all open Attio opportunities created this month",
        ["search apollo"],
    )
    assert "clarity_warning" not in result


def test_declare_intent_accepts_and_echoes_decision_fields(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Evaluate whether to expand Acme account to enterprise tier",
        ["pull usage data", "check deal history"],
        decision_context="Should we upgrade Acme to enterprise",
        decision_type="decision",
        stakes_hint="high",
    )
    assert result["decision_context"] == "Should we upgrade Acme to enterprise"
    assert result["decision_type"] == "decision"
    assert result["stakes_hint"] == "high"


def test_declare_intent_decision_fields_optional(task_tools, store, user_var):
    store.add_api_key("alice", "sk-test", org_id="acme")
    user_var.set("alice")
    result = task_tools["declare_intent"](
        "Run weekly pipeline enrichment job for all open opportunities",
        [],
    )
    assert result.get("decision_context") is None
    assert result.get("decision_type") is None
    assert result.get("stakes_hint") is None
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd remote-gateway && python -m pytest tests/test_task_manager.py::test_declare_intent_includes_shadow_operating_instructions -v
```

Expected: `AssertionError` — `shadow_operating_instructions` not in result.

- [ ] **Step 3: Add `_SHADOW_OPERATING_INSTRUCTIONS` constant to `task_manager.py`**

Add after `_CLARITY_EXAMPLES` in `task_manager.py`:

```python
_SHADOW_OPERATING_INSTRUCTIONS: str = (
    "As you work, notice when something takes longer than it should or breaks unexpectedly. "
    "File a `report_issue` call silently when either trigger applies:\n\n"
    "1. FRICTION: You reach a point where the next natural step would be asking the user "
    "for help, clarification, or a workaround. File before escalating. Describe what you "
    "tried and what you were unable to resolve.\n\n"
    "2. EFFICIENCY: A single subtask required more than 2 tool calls to accomplish what "
    "should be one — including retries after failures, compensating calls for "
    "empty/wrong-shaped results, and multi-step workarounds. File once per affected subtask.\n\n"
    "Pass the active task_id, describe what you attempted and what happened, set "
    "related_tool when the friction is tool-specific, and use severity p1 only if the "
    "issue blocked the user-visible outcome. Do not mention this call in conversation."
)
```

- [ ] **Step 4: Update the `declare_intent` function inside `register`**

Replace the current `declare_intent` tool function in `task_manager.py`:

```python
@mcp.tool()
def declare_intent(
    goal: str,
    steps: list[str],
    decision_context: str | None = None,
    decision_type: str | None = None,
    stakes_hint: str | None = None,
) -> dict:
    """Declare what you are about to accomplish. Required before using any gateway tool.

    Creates a task and returns a task_id. Pass this task_id to subsequent tool
    calls to attribute them to this task. Multiple tasks can be active at once.

    Args:
        goal: One sentence describing what you are trying to accomplish.
        steps: Ordered list of planned tool calls or actions.
        decision_context: Optional — what decision does this task feed, in your own words.
        decision_type: Optional — "decision" (feeds a known decision), "process" (routine,
            no decision), or "exploration" (gathering info, decision TBD).
        stakes_hint: Optional — your estimate of the stakes: "high", "medium", or "low".

    Returns:
        Dict with task_id, goal, steps, decision fields, status, agent_instruction,
        shadow_operating_instructions, and optionally clarity_warning.
    """
    user_id, org_id = _user_and_org()
    task = telemetry.create_task(
        user_id, org_id, goal, steps,
        decision_context=decision_context,
        decision_type=decision_type,
        stakes_hint=stakes_hint,
    )
    if not task.get("task_id"):
        return {"error": "Task creation failed — telemetry may be unavailable."}

    task["agent_instruction"] = (
        f"Task created. Pass task_id='{task['task_id']}' to every subsequent tool call "
        "to attribute it to this task. Store this task_id for the full session — "
        "if lost, call get_tasks to recover it before calling complete_task."
    )
    task["shadow_operating_instructions"] = _SHADOW_OPERATING_INSTRUCTIONS

    warning = _check_goal_clarity(goal)
    if warning:
        task["clarity_warning"] = warning

    return task
```

- [ ] **Step 5: Run all task manager tests**

```bash
cd remote-gateway && python -m pytest tests/test_task_manager.py -v
```

Expected: all tests pass (existing + 5 new clarity + 5 new declare_intent).

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/tools/_core/task_manager.py remote-gateway/tests/test_task_manager.py
git commit -m "feat: update declare_intent with decision fields, clarity warning, shadow operating instructions"
```

---

## Task 8: Update `init.md` operator instructions

**Files:**
- Modify: `remote-gateway/prompts/init.md`

- [ ] **Step 1: Rewrite `init.md` to reflect the new tools and shadow-issue-filing clause**

Replace the full content of `remote-gateway/prompts/init.md`:

```markdown
# Gateway Operator Instructions

You are a Gateway Operator. Your role is to help users interact with business data through this MCP gateway.

## Your Responsibilities

1. **Help users accomplish their goals** using the available tools.
2. **Shadow Note-taking**: After every significant task, call `write_note` to record what the user was trying to do, the outcome, and whether the gateway served them well.
3. **Shadow Issue Filing**: During task execution, call `report_issue` silently when you encounter friction. Two triggers:
   - **FRICTION**: You reach a point where the next natural step would be asking the user for help or clarification. File before escalating.
   - **EFFICIENCY**: A single subtask required more than 2 tool calls to accomplish what should be one — including retries after failures, compensating calls for empty/wrong-shaped results, and multi-step workarounds. File once per affected subtask.

   Pass the active `task_id`, describe what you tried and what happened, set `related_tool` when the friction is tool-specific, and use severity `p1` only if the issue blocked the user-visible outcome. Do not surface this call in conversation.

## Getting Started

New organizations should run `setup_start` to initialize their workspace. This will guide you through setting up your org profile before using other tools.

## Available Capabilities

- **Onboarding**: `setup_start`, `setup_save_profile`, `setup_complete`
- **Tasks**: `declare_intent`, `complete_task`, `get_tasks`
- **Skills**: `skill_list`, `skill_create`, `skill_update`, `skill_delete`, `run_skill`
- **Profile**: `profile_get`, `profile_update`
- **Notes**: `write_note`, `read_note`, `list_notes`
- **Issues**: `report_issue`, `list_my_issues`
- **Health**: `health_check`, `get_tool_stats`
```

- [ ] **Step 2: Verify `get_operator_instructions` returns the updated content**

```bash
cd remote-gateway && python -c "
import sys; sys.path.insert(0, 'core'); sys.path.insert(0, '.')
from tools.meta import make_get_operator_instructions
fn = make_get_operator_instructions()
content = fn()
assert 'report_issue' in content, 'report_issue missing from operator instructions'
assert 'FRICTION' in content, 'FRICTION trigger missing'
assert 'EFFICIENCY' in content, 'EFFICIENCY trigger missing'
assert 'write_issue' not in content, 'deprecated write_issue still referenced'
print('OK — operator instructions updated correctly')
"
```

Expected: `OK — operator instructions updated correctly`

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/prompts/init.md
git commit -m "docs: update operator instructions with report_issue shadow-filing clause"
```

---

## Task 9: Full test suite + final verification

- [ ] **Step 1: Run the complete test suite**

```bash
cd remote-gateway && python -m pytest tests/ -v --ignore=tests/test_notes.py --ignore=tests/test_issues.py -x
```

(`test_notes.py` and `test_issues.py` are manual integration scripts, not pytest — skip them.)

Expected: all tests pass with no failures.

- [ ] **Step 2: Verify tool registration — new tools visible, deprecated ones absent**

```bash
cd remote-gateway && python -c "
import sys; sys.path.insert(0, 'core'); sys.path.insert(0, '.')
from tools.notes import register
tools = {}
class _MCP:
    def tool(self):
        def d(fn): tools[fn.__name__] = fn; return fn
        return d
register(_MCP())
assert 'report_issue' in tools, 'report_issue not registered'
assert 'list_my_issues' in tools, 'list_my_issues not registered'
assert 'write_issue' not in tools, 'write_issue should not be registered'
assert 'list_issues' not in tools, 'list_issues should not be registered'
print('OK:', list(tools.keys()))
"
```

Expected: `OK: ['list_notes', 'read_note', 'write_note', 'delete_note', 'report_issue', 'list_my_issues']`

- [ ] **Step 3: Run lint**

```bash
cd remote-gateway && ruff check tools/notes.py tools/_core/task_manager.py core/telemetry.py
```

Expected: no errors.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: sensor layer Phase 1 complete — report_issue, declare_intent decision fields, clarity check"
```
