# Exa

Neural web search via Exa's hosted MCP server (HTTP).

## Required environment

| Variable | Where to get it |
|---|---|
| `EXA_API_KEY` | dashboard.exa.ai → API Keys |

## Notes

Rate-limited to 20 RPM / 2 concurrent at the proxy layer to stay under Exa's free-tier limits — bump in `mcp_connections.json` if on a paid plan. Tools appear as `exa__web_search_exa`, `exa__web_fetch_exa`.
