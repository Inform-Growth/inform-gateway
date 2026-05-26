"""One-shot migration: move root-level notes/*.md into folder by prefix rule.

Prefix → folder:
  competitor-watch-*, content-drafts-*, marketing-research-*, marketing-weekly-* → marketing/
  signal-scout-*, lead-research-*, sales-weekly-*, sales-strategy-*              → sales/
  shadow-*                                                                       → shadow/
  (everything else)                                                              → stays at root

For each match:
  1. GET source file from notes/{slug}.md.
  2. Check if target exists; if same content, skip; if different, warn + skip.
  3. PUT target file at notes/{folder}/{slug}.md.
  4. DELETE source file.

Idempotent. Delete this script after Inform-Growth's deployment has run it once.

Required env vars:
    NOTES_REPO          — owner/repo (e.g. "Inform-Growth/inform-notes")
    NOTES_GITHUB_TOKEN  — fine-grained PAT with Contents: read+write on NOTES_REPO.
"""
from __future__ import annotations

import base64
import os
import sys

import httpx

_PREFIX_RULES: list[tuple[str, str]] = [
    ("competitor-watch-", "marketing"),
    ("content-drafts-", "marketing"),
    ("marketing-research-", "marketing"),
    ("marketing-weekly-", "marketing"),
    ("signal-scout-", "sales"),
    ("lead-research-", "sales"),
    ("sales-weekly-", "sales"),
    ("sales-strategy-", "sales"),
    ("shadow-", "shadow"),
]


def target_folder(slug: str) -> str | None:
    """Return the folder this slug should live in, or None if it stays at root."""
    for prefix, folder in _PREFIX_RULES:
        if slug.startswith(prefix):
            return folder
    return None


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _list_root_md(client: httpx.Client, repo: str, token: str) -> list[dict]:
    resp = client.get(
        f"https://api.github.com/repos/{repo}/contents/notes",
        headers=_headers(token),
    )
    resp.raise_for_status()
    return [
        e for e in resp.json()
        if e.get("type") == "file" and e["name"].endswith(".md")
    ]


def _get_file(client: httpx.Client, repo: str, token: str, path: str) -> dict | None:
    resp = client.get(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=_headers(token),
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _put_file(
    client: httpx.Client, repo: str, token: str,
    path: str, content: str, slug: str, folder: str,
) -> dict:
    resp = client.put(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=_headers(token),
        json={
            "message": f"notes: move {slug} to {folder}/",
            "content": base64.b64encode(content.encode()).decode(),
        },
    )
    resp.raise_for_status()
    return resp.json()


def _delete_file(client: httpx.Client, repo: str, token: str, path: str, sha: str) -> None:
    resp = client.request(
        "DELETE",
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=_headers(token),
        json={"message": f"notes: remove {path} after move", "sha": sha},
    )
    resp.raise_for_status()


def run() -> dict:
    repo = os.environ.get("NOTES_REPO", "")
    token = os.environ.get("NOTES_GITHUB_TOKEN", "")
    if not repo or not token:
        raise RuntimeError("NOTES_REPO and NOTES_GITHUB_TOKEN must be set.")

    summary = {"migrated": 0, "skipped": 0, "warnings": 0, "errors": 0}
    with httpx.Client(timeout=30) as client:
        root_files = _list_root_md(client, repo, token)
        for entry in root_files:
            slug = entry["name"][: -len(".md")]
            folder = target_folder(slug)
            if folder is None:
                print(f"skip (no rule match): {slug}")
                summary["skipped"] += 1
                continue

            target_path = f"notes/{folder}/{slug}.md"
            source_path = entry["path"]
            try:
                source = _get_file(client, repo, token, source_path)
                if source is None:
                    print(f"ERROR source disappeared: {source_path}", file=sys.stderr)
                    summary["errors"] += 1
                    continue
                body = base64.b64decode(source["content"]).decode()

                existing = _get_file(client, repo, token, target_path)
                if existing is not None:
                    existing_body = base64.b64decode(existing["content"]).decode()
                    if existing_body == body:
                        print(f"skip (already migrated): {slug} → {folder}/")
                    else:
                        print(
                            f"WARNING skip (target diverges): {slug} → {folder}/",
                            file=sys.stderr,
                        )
                        summary["warnings"] += 1
                    summary["skipped"] += 1
                    continue

                _put_file(client, repo, token, target_path, body, slug, folder)
                _delete_file(client, repo, token, source_path, entry["sha"])
                print(f"migrated: {slug} → {folder}/")
                summary["migrated"] += 1
            except Exception as e:  # noqa: BLE001 — surface and continue
                print(f"ERROR migrating {slug}: {e}", file=sys.stderr)
                summary["errors"] += 1
    return summary


if __name__ == "__main__":
    result = run()
    print(f"\nSummary: {result}")
    sys.exit(1 if result["errors"] else 0)
