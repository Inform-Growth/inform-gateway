# Google Analytics Integration Design

**Date:** 2026-06-08
**Status:** Approved

## Summary

Proxy the official Google `analytics-mcp` package through the gateway so agents can query GA4 data (reports, real-time, funnels, account structure) without managing credentials locally. One deployment connects to one hardcoded GA4 property.

## Architecture

Three changes, no new Python code:

1. **`remote-gateway/mcp_connections.json`** — add a `google-analytics` stdio entry using `uvx analytics-mcp`. `uvx` is already installed in the Dockerfile (used by the `google` workspace integration).
2. **`Dockerfile` CMD** — write `GOOGLE_SA_JSON` env var to `/tmp/google-sa.json` at startup and export `GOOGLE_APPLICATION_CREDENTIALS` pointing to it. Standard Railway pattern for service account credentials.
3. **`context/fields/google-analytics.yaml`** — minimal field schema for GA4 report responses, enabling `validated("google-analytics", result)` and drift detection.

## Integration Details

### Package

- **Package:** `analytics-mcp` (PyPI) — `github.com/googleanalytics/google-analytics-mcp`
- **Invocation:** `uvx analytics-mcp` (stdio transport)
- **Auth:** Application Default Credentials via `GOOGLE_APPLICATION_CREDENTIALS` file path
- **Status:** Experimental, Google-maintained

### Why not npm alternatives

- `mcp-server-google-analytics` (ruchernchong): archived October 2025, no further maintenance
- Stape cloud (`npx mcp-remote`): data transits a third-party server; browser OAuth unsuitable for headless Railway

### Tools exposed (all read-only)

| Gateway tool name | Description |
|---|---|
| `google-analytics__run_report` | Custom GA4 report with arbitrary dimensions/metrics/filters |
| `google-analytics__run_realtime_report` | Active users and events in the last 30 minutes |
| `google-analytics__run_funnel_report` | Multi-step funnel analysis |
| `google-analytics__get_account_summaries` | List all GA4 accounts and properties accessible to the service account |
| `google-analytics__get_property_details` | Metadata for a specific GA4 property |
| `google-analytics__get_custom_dimensions_and_metrics` | Custom schema registered on a property |
| `google-analytics__list_google_ads_links` | Google Ads accounts linked to a GA4 property |

Property ID is a **parameter** on each tool call, not an env var. Operators should document their property ID in the org profile so agents always know which to pass.

## `mcp_connections.json` entry

```json
"google-analytics": {
  "_comment": "Read-only GA4 data via official analytics-mcp. Property ID is passed as a parameter on each tool call — document your property ID in the org profile so agents know which to use.",
  "transport": "stdio",
  "command": "uvx",
  "args": ["analytics-mcp"],
  "env": {
    "GOOGLE_APPLICATION_CREDENTIALS": "${GOOGLE_APPLICATION_CREDENTIALS}"
  },
  "tools": {
    "allow": [
      "run_report",
      "run_realtime_report",
      "run_funnel_report",
      "get_account_summaries",
      "get_property_details",
      "get_custom_dimensions_and_metrics",
      "list_google_ads_links"
    ]
  }
}
```

## Dockerfile CMD change

```dockerfile
CMD ["sh", "-c", \
  "if [ -n \"$GOOGLE_SA_JSON\" ]; then printf '%s' \"$GOOGLE_SA_JSON\" > /tmp/google-sa.json && export GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-sa.json; fi && \
  MCP_SERVER_PORT=${PORT:-8000} python3 remote-gateway/core/mcp_server.py"]
```

If `GOOGLE_SA_JSON` is absent the gateway starts normally — the GA proxy silently fails to connect at spawn time, consistent with existing behaviour for any misconfigured integration.

## Credentials

| Railway env var | Required | Description |
|---|---|---|
| `GOOGLE_SA_JSON` | Yes (for GA) | Raw service account JSON key content. Set this in Railway; the startup script writes it to `/tmp/google-sa.json`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Auto-set | Set to `/tmp/google-sa.json` by the startup script. Can also be set directly to a mounted file path if not using `GOOGLE_SA_JSON`. |

### Service account setup (one-time)

1. Google Cloud Console → IAM → Service Accounts → Create
2. GA4 Admin → Property Access Management → Add service account email with **Viewer** role
3. Cloud Console → Service Account → Keys → Add Key → JSON → Download
4. Paste the JSON file contents as `GOOGLE_SA_JSON` in Railway

The existing `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` credentials (used by the workspace MCP for Gmail/Calendar/Drive) are a different credential type (user OAuth2) and cannot be reused here.

## Field schema

`context/fields/google-analytics.yaml` covers the common fields returned by `run_report`: `date`, `sessions`, `users`, `activeUsers`, `newUsers`, `pageviews`, `bounceRate`, `sessionDuration`. Schema is minimal — GA4 reports return arbitrary dimension/metric combinations so the schema documents the most common ones without being exhaustive.

## What does not change

- No Python code changes
- No admin UI changes
- No new npm or Python packages in pyproject.toml / package.json
- No copier.yml changes (this is a dogfood deployment change)
- `uvx` already available in the Dockerfile
