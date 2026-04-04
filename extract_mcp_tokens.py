#!/usr/bin/env python3
"""
Extract MCP OAuth tokens from the macOS Keychain (Claude Code-credentials).

Usage:
    python extract_mcp_tokens.py              # print all integrations
    python extract_mcp_tokens.py apollo       # print just apollo
    python extract_mcp_tokens.py apollo --env # print as .env lines (ready to paste)
"""

import json
import subprocess
import sys


def get_credentials() -> dict:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Error: could not read Claude Code-credentials from keychain.")
        print(result.stderr)
        sys.exit(1)
    return json.loads(result.stdout.strip())


def main() -> None:
    filter_name = sys.argv[1].lower() if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    env_mode = "--env" in sys.argv

    data = get_credentials()
    oauth = data.get("mcpOAuth", {})

    if not oauth:
        print("No MCP OAuth tokens found.")
        return

    for key, entry in oauth.items():
        name = entry.get("serverName", key.split("|")[0])
        if filter_name and filter_name not in name.lower():
            continue

        slug = name.upper().replace("-", "_").replace(".", "_")
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


if __name__ == "__main__":
    main()
