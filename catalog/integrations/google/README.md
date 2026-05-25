# Google Workspace

Gmail + Calendar + Drive/Docs via the unified `workspace-mcp` server (stdio, single-user OAuth).

## Required environment

| Variable | Where to get it |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | console.cloud.google.com → APIs & Services → Credentials → OAuth 2.0 Client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Same place |
| `USER_GOOGLE_EMAIL` | The account the gateway authenticates as |
| `WORKSPACE_MCP_CREDENTIALS_DIR` | Persistent dir for cached refresh tokens (e.g. `/data/google-workspace-creds` on Railway) |

## First-time auth

Tokens are cached at `WORKSPACE_MCP_CREDENTIALS_DIR` and reused; the initial OAuth flow needs browser access.

1. Set the four env vars locally (use `~/.google_workspace_mcp/credentials` as `WORKSPACE_MCP_CREDENTIALS_DIR`).
2. Run `uvx workspace-mcp --tool-tier core` and make any tool call. First call returns an OAuth URL — open it, consent, and the server writes refresh tokens to disk.
3. Copy `~/.google_workspace_mcp/credentials/*` to the production volume at `WORKSPACE_MCP_CREDENTIALS_DIR`.
4. Redeploy. Look for `[proxy] 'google' connected — N tool(s) registered` in startup logs.

Refresh tokens auto-rotate; re-do step 1 only if the user revokes access in Google account settings.

## Dependencies

`uvx` (from `uv`) must be installed on the host so `uvx workspace-mcp` can fetch and run the package on demand.
