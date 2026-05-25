# GitHub

GitHub file operations and issue reads via the official `mcp-server-github` (stdio).

## Required environment

| Variable | Where to get it |
|---|---|
| `GITHUB_TOKEN` | github.com → Settings → Developer settings → Personal access tokens. For read-only on public repos a classic token with `public_repo` works; for private repos and writes, use a fine-grained PAT with Contents and Issues read+write on the target repos. |

## Tool allow-list

The proxy ships with `tools.allow` restricting agents to read-leaning operations plus one write (`create_or_update_file`):

- `get_file_contents`, `list_files_in_repo`, `search_repositories`
- `get_issue`, `list_issues`
- `create_or_update_file`

Edit `mcp_connections.json` after install to broaden or tighten.

## Dependencies

`mcp-server-github` must be installed (`npm install -g @modelcontextprotocol/server-github`).
