"""
Manual integration test for the GitHub-backed notes tools.

Reads GITHUB_TOKEN, GITHUB_REPO, and GITHUB_BRANCH from the environment.
Run with:
    GITHUB_TOKEN=... GITHUB_REPO=owner/repo .venv/bin/python remote-gateway/tests/test_notes.py
"""

import os
import sys

# Ensure remote-gateway is on the path so tools.notes imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Also add core for any mcp_server imports if needed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


def run():
    from tools.notes import delete_note, list_notes, read_note, write_note

    print(f"Repo : {os.environ['GITHUB_REPO']}")
    print(f"Branch: {os.environ.get('GITHUB_BRANCH', 'main')}")
    print()

    test_file = "_test_note"

    # ---- 0. cleanup any leftover from a previous run ----
    if any(n["name"] == "_test_note.md" for n in list_notes().get("notes", [])):
        delete_note(test_file, "test: pre-run cleanup")

    # ---- 1. list (before) ----
    print("=== list_notes() ===")
    before = list_notes()
    print(before)
    print()

    # ---- 2. write (create) ----
    print("=== write_note() — create ===")
    created = write_note(
        test_file, "# Test Note\n\nHello from the test script.", "test: create note"
    )
    print(created)
    assert created["action"] == "created", f"Expected 'created', got {created['action']}"
    print()

    # ---- 3. read ----
    print("=== read_note() ===")
    fetched = read_note(test_file)
    print(fetched)
    assert "# Test Note" in fetched["content"], "Content mismatch"
    print()

    # ---- 4. write (update) ----
    print("=== write_note() — update ===")
    updated = write_note(test_file, "# Updated\n\nSecond write.", "test: update note")
    print(updated)
    assert updated["action"] == "updated", f"Expected 'updated', got {updated['action']}"
    print()

    # ---- 5. list (after write) ----
    print("=== list_notes() — after write ===")
    after = list_notes()
    names = [n["name"] for n in after["notes"]]
    print(names)
    assert "_test_note.md" in names, "_test_note.md not found in list after write"
    print()

    # ---- 6. delete ----
    print("=== delete_note() ===")
    deleted = delete_note(test_file, "test: cleanup")
    print(deleted)
    assert deleted["status"] == "deleted"
    print()

    # ---- 7. read after delete ----
    print("=== read_note() — after delete ===")
    gone = read_note(test_file)
    print(gone)
    assert gone["status"] == "not_found"
    print()

    print("All assertions passed.")


if __name__ == "__main__":
    from dotenv import load_dotenv

    # Load .env from repo root (two levels up from this file)
    _repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
    load_dotenv(os.path.join(_repo_root, ".env"))

    # Validate required env vars before running
    for var in ("GITHUB_TOKEN", "GITHUB_REPO"):
        if not os.environ.get(var):
            print(f"ERROR: {var} is not set. Add it to .env or export it.")
            sys.exit(1)

    run()
