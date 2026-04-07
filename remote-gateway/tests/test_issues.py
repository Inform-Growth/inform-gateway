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
