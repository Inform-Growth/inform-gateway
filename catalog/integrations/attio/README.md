# Attio CRM

Attio CRM access via two layers:
- **MCP proxy** (`attio-mcp`) — most Attio tools, with `search_records` and `create_record` denied at the proxy
- **Python overrides** (`tool.py`) — `attio__search_records`, `attio__create_record`, `attio__upsert_record` reimplemented against Attio's REST API to fix payload-shape bugs in the upstream MCP

The proxy and Python tools are loaded together (`kind: both`). The deny list on the proxy ensures the Python versions are the only ones agents see for those three names.

## Required environment

| Variable | Where to get it |
|---|---|
| `ATTIO_API_KEY` | app.attio.com → Workspace settings → Apps → Generate token |

## Dependencies

The `attio-mcp` CLI must be installed and on `$PATH` (`npm install -g @attio/mcp-server` or via the Dockerfile install step).
