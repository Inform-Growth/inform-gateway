"""
Manual integration test for GitHub Issues-backed notes tools.

Reads ISSUE_DEPLOYMENT_REPO and ISSUE_DEPLOYMENT_GITHUB_TOKEN from the environment.
Run with:
    ISSUE_DEPLOYMENT_REPO=owner/repo ISSUE_DEPLOYMENT_GITHUB_TOKEN=ghp_... \
        .venv/bin/python remote-gateway/tests/test_notes.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


def run():
    from tools.notes import delete_note, list_notes, read_note, write_note

    print(f"Repo: {os.environ['ISSUE_DEPLOYMENT_REPO']}")
    print()

    test_slug = "_test_integration_note"

    # ---- 0. cleanup any leftover from a previous run ----
    cleanup = read_note(test_slug)
    if cleanup.get("issue_number"):
        delete_note(test_slug)

    # ---- 1. list (before) ----
    print("=== list_notes() ===")
    before = list_notes()
    print(before)
    print()

    # ---- 2. write (create) ----
    print("=== write_note() — create ===")
    created = write_note(test_slug, "# Test Note\n\nHello from the integration test.")
    print(created)
    assert created["status"] == "created", f"Expected 'created', got {created['status']}"
    print()

    # ---- 3. read ----
    print("=== read_note() ===")
    fetched = read_note(test_slug)
    print(fetched)
    assert "# Test Note" in fetched["content"], "Content mismatch"
    print()

    # ---- 4. write (update) ----
    print("=== write_note() — update ===")
    updated = write_note(test_slug, "# Updated\n\nSecond write.")
    print(updated)
    assert updated["status"] == "updated", f"Expected 'updated', got {updated['status']}"
    print()

    # ---- 5. list (after write) ----
    print("=== list_notes() — after write ===")
    after = list_notes()
    slugs = [n["slug"] for n in after["notes"]]
    print(slugs)
    assert test_slug in slugs, f"{test_slug} not found in list after write"
    print()

    # ---- 6. delete ----
    print("=== delete_note() ===")
    deleted = delete_note(test_slug)
    print(deleted)
    assert deleted["status"] == "deleted"
    print()

    # ---- 7. read after delete ----
    print("=== read_note() — after delete ===")
    gone = read_note(test_slug)
    print(gone)
    assert gone["status"] == "not_found"
    print()

    print("All assertions passed.")


if __name__ == "__main__":
    from dotenv import load_dotenv

    _repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
    load_dotenv(os.path.join(_repo_root, ".env"))

    for var in ("ISSUE_DEPLOYMENT_REPO", "ISSUE_DEPLOYMENT_GITHUB_TOKEN"):
        if not os.environ.get(var):
            print(f"ERROR: {var} is not set. Add it to .env or export it.")
            sys.exit(1)

    run()
