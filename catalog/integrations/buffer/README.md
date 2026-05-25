# Buffer

Social media post scheduling via Buffer's hosted MCP server (HTTP, no local install).

## Required environment

| Variable | Where to get it |
|---|---|
| `BUFFER_ACCESS_TOKEN` | publish.buffer.com → Account → Apps & Integrations → Personal Access Token |

## Notes

Pure proxy — no Python wrapper. Tools appear as `buffer__*`. Buffer's MCP exposes `create_post`, `list_posts`, `get_account`, `list_channels`, etc.
