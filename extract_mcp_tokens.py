#!/usr/bin/env python3
"""
Extract MCP OAuth tokens from the macOS Keychain (Claude Code / Claude Desktop).

Claude stores MCP OAuth tokens across multiple keychain service names:
  - Claude Code-credentials          (Claude Code base entry)
  - Claude Code-credentials-<hash>   (Claude Desktop plugin entries)

This script searches all of them and merges the results.

Usage:
    python extract_mcp_tokens.py              # print all integrations
    python extract_mcp_tokens.py apollo       # print just apollo
    python extract_mcp_tokens.py apollo --env # print as .env lines (ready to paste)
"""

import json
import subprocess
import sys


def _read_keychain_service(service: str) -> dict:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {}


def _find_all_claude_services() -> list[str]:
    """Return all Claude-related keychain service names on this machine."""
    result = subprocess.run(
        ["security", "dump-keychain"],
        capture_output=True,
        text=True,
    )
    services = []
    for line in result.stdout.splitlines():
        if '"svce"' in line and "Claude Code-credentials" in line:
            # Extract the value between the quotes after <blob>=
            parts = line.split('"')
            if len(parts) >= 4:
                services.append(parts[-2])
    return list(dict.fromkeys(services))  # deduplicate, preserve order


def get_all_credentials() -> dict:
    """Merge mcpOAuth entries from all Claude keychain services."""
    services = _find_all_claude_services()
    if not services:
        # Fallback to the base name if dump-keychain fails
        services = ["Claude Code-credentials"]

    merged: dict = {}
    for svc in services:
        data = _read_keychain_service(svc)
        oauth = data.get("mcpOAuth", {})
        merged.update(oauth)
    return merged


def main() -> None:
    filter_name = (
        sys.argv[1].lower()
        if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    )
    env_mode = "--env" in sys.argv

    oauth = get_all_credentials()

    if not oauth:
        print("No MCP OAuth tokens found in any Claude keychain entry.")
        return

    matched = False
    for key, entry in oauth.items():
        name = entry.get("serverName", key.split("|")[0])
        if filter_name and filter_name not in name.lower():
            continue

        matched = True
        slug = name.upper().replace("-", "_").replace(".", "_").replace(":", "_")
        access_token = entry.get("accessToken", "")
        refresh_token = entry.get("refreshToken", "")
        client_id = entry.get("clientId", "")
        server_url = entry.get("serverUrl", "")

        if env_mode:
            print(f"{slug}_ACCESS_TOKEN={access_token}")
            print(f"{slug}_REFRESH_TOKEN={refresh_token}")
            print(f"{slug}_CLIENT_ID={client_id}")
        else:
            print(f"\n=== {name} ===")
            print(f"  URL:           {server_url}")
            print(f"  client_id:     {client_id}")
            print(f"  access_token:  {access_token[:60]}...")
            print(f"  refresh_token: {refresh_token}")

    if filter_name and not matched:
        print(f"No MCP OAuth token found for '{filter_name}'.")
        print("Run without arguments to list all available integrations.")


if __name__ == "__main__":
    main()
