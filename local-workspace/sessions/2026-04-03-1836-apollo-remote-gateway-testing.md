---
date: 2026-04-03
slug: apollo-remote-gateway-testing
status: active
---

# Session: apollo-remote-gateway-testing

**Date:** 2026-04-03
**Integration(s):** apollo
**Goal:** Test Apollo through the remote-gateway MCP connection.

## Discoveries

- **Apollo connection confirmed working** — profile endpoint returned Jaron Sander's account info successfully. Basic auth and gateway proxying are functional end-to-end.

- **Company search returns results but filters are silently ignored** — `apollo_mixed_companies_search` returned Google, Amazon, LinkedIn, etc. regardless of `organization_num_employees_ranges` and `organization_industries` filter params. Root cause was the double-wrapping bug in `mcp_proxy.py` (see API Quirks). Optional params were reaching Apollo as a nested `kwargs` dict, which Apollo silently discarded, falling back to unfiltered results.

- **Enrich tools failed with "Invalid params"** — same root cause as above. Required params (e.g. `domain`) were nested under a `kwargs` key instead of at the top level, so Apollo rejected the call outright.

## Decisions

- **Fix double-wrapping in mcp_proxy.py at the proxy layer, not the client layer** — unwrapping logic added at ~line 363 in `remote-gateway/core/mcp_proxy.py`. If the kwargs dict has exactly one key named `"kwargs"` pointing to a dict, unwrap it before forwarding upstream. This keeps the fix in one place and doesn't require changes to any skill or client code.

## API Quirks

- **FastMCP double-wrapping bug** — FastMCP registers `proxy_fn(**kwargs)`, which causes clients calling a tool with `{"kwargs": {"domain": "gong.io"}}` to have their params forwarded as `{"kwargs": {"domain": "gong.io"}}` instead of the flat `{"domain": "gong.io"}`. Apollo's MCP server treats unknown top-level keys as missing params. Fix: unwrap the single `kwargs` key before the upstream call in `mcp_proxy.py`.

- **Apollo silently ignores unrecognized filter params** — when filters arrive wrapped (i.e. malformed), Apollo does not error; it returns default unfiltered results. No way to detect this failure mode without inspecting the result set for obviously wrong entries (e.g. mega-cap companies when you filtered for mid-market).

## Open Questions

- Gateway restart required before bulk enrich can be validated — once restarted, test enrich against: gong.io, outreach.io, salesloft.com, clari.com, chilipiper.com, qualified.com, demandbase.com, crossbeam.com.
- After restart, re-run company search with filters to confirm double-wrapping fix resolves silent filter-ignore behavior.
- Are there other tools in the proxy that could exhibit the same double-wrapping issue, or is it isolated to how Apollo's MCP tools are registered?
