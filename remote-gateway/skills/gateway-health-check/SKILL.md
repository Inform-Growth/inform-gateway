---
name: gateway-health-check
description: Systematic probe of every tool on the remote gateway — built-in and proxied. Tests authentication, runs smoke calls, cross-checks responses against field documentation, and writes structured issues to the GitHub notes repo. Run this periodically or after any infrastructure change.
---

# Gateway Health Check

Run this skill whenever you need to verify the gateway is healthy: after a redeploy,
after adding new proxied integrations, or on a scheduled basis. Each finding is written
as a structured issue note to `{NOTES_PATH}/issues/`. A summary note goes to
`{NOTES_PATH}/gateway-health-{date}.md`.

---

## Phase 1 — Gateway Connectivity

**Goal:** Confirm the gateway itself is up and report the registered tool inventory.

1. Call `health_check()`. If it errors, stop — the gateway is not reachable.
   Record the error for manual investigation; do not proceed.

2. Call `get_tool_stats()` with no arguments. Save the returned `tools` list.
   This is your master inventory. You will work through it systematically in Phase 3.

3. Note which tools appear in the inventory. Proxied tools follow the pattern
   `{integration}__{tool_name}`. Extract unique integration prefixes
   (e.g., `attio`, `exa`, `apollo`, `github`) — these are your probe targets.

---

## Phase 2 — Field Documentation Audit

**Goal:** Confirm every proxied integration has field definitions in the registry.
Missing documentation is itself an issue — it means responses cannot be validated.

For each integration prefix identified in Phase 1:

1. Call `get_field_definitions(integration)`. A non-empty `fields` dict means
   docs exist. An empty dict means they are missing.

2. Call `list_field_integrations()` to see all registered integration slugs.
   Note: field docs may use compound slugs (e.g., `attio-companies`, `attio-deals`)
   rather than just the integration prefix. Check whether any slug starts with the
   integration prefix.

3. If **no field docs exist** for an integration, record it:
   - Slug: `{integration}-missing-docs-{YYYY-MM-DD}`
   - Write with `write_issue(slug, content)` using the template:

```
# Issue: {integration} — Missing Field Documentation

**Detected:** {YYYY-MM-DD}
**Integration:** {integration}
**Type:** missing_docs

## Description
No field definitions found in the registry for the `{integration}` integration.
Responses from `{integration}__*` tools cannot be validated for schema drift.

## Recommended Action
1. Make a representative smoke call to a `{integration}__*` tool.
2. Call `discover_fields("{integration}", response)` to auto-generate definitions.
3. Edit `remote-gateway/context/fields/{integration}.yaml` to fill in business descriptions.
4. Redeploy so the updated registry is active.
```

---

## Phase 3 — Proxied Integration Smoke Calls

**Goal:** Confirm each proxied integration authenticates and returns data.
Use the lightest available call — 1 result, minimal params.

Work through each integration prefix. For each one:

### 3a. Select the smoke call

Use the tool from the inventory that is most likely to succeed with minimal parameters.
Guidance by integration type:

**attio** → `attio__list_records` with `{"object_type": "companies", "limit": 1}`
  - If that tool is not in the inventory, use the first `attio__*` tool listed.

**exa** → Look for a `exa__search` or `exa__web_search` tool.
  Use `{"query": "gateway health check", "numResults": 1}` or equivalent.
  Check the tool's description for the exact parameter names.

**apollo** → Look for a `apollo__search_people` or `apollo__people_search` tool.
  Use `{"q_organization_domains": ["apollo.io"], "page": 1, "per_page": 1}`
  or the minimal params shown in the tool description.

**github** → `github__search_repositories` with `{"query": "stars:>1000", "page": 1}`
  or `github__list_files_in_repo` with `{"repo": "owner/repo-name", "path": "/"}` (use the actual repo slug from context or GITHUB_REPO env var).

**Unknown integration** → Use the first tool listed for that prefix with no required
  parameters (check the tool description), or the simplest read operation.

### 3b. Make the call and evaluate

Call the smoke tool. Then:

**If the call raises an error or returns an error field:**

- Determine if it is an auth error (contains "401", "403", "unauthorized", "invalid key",
  "token", "credentials") or a connectivity/config error.
- Write an issue:
  - For auth errors: slug `{integration}-auth-failure-{YYYY-MM-DD}`
  - For non-auth errors: slug `{integration}-tool-error-{YYYY-MM-DD}`
  - Template:

```
# Issue: {integration} — {Auth Failure | Tool Error}

**Detected:** {YYYY-MM-DD}
**Integration:** {integration}
**Type:** {auth_failure | tool_error}

## Tool Call
- Tool: `{tool_name}`
- Args: `{args_as_json}`

## Error
```
{full error message}
```

## Recommended Action
{For auth: Check that the relevant env var is set on the gateway and not expired.
 For tool_error: Check the integration's upstream service status.
 Include the specific env var names from mcp_connections.json if known.}
```

**If the call succeeds:**

- You have a live response. Proceed to 3c.

### 3c. Validate against field documentation

Take the response dict. For each field doc slug that starts with the integration prefix
(e.g., `attio-companies` for the `attio` integration):

1. Call `check_field_drift("{doc_slug}", response)`.
   - If `has_drift` is true: write a drift issue (slug: `{integration}-schema-drift-{date}`):

```
# Issue: {integration} — Schema Drift Detected

**Detected:** {YYYY-MM-DD}
**Integration:** {integration}
**Type:** schema_drift
**Field Doc:** {doc_slug}

## Drift Report
- New fields (not in registry): {new_fields}
- Removed fields (in registry but absent from response): {removed_fields}

## Tool Call Used for Sample
- Tool: `{tool_name}`
- Args: `{args}`

## Recommended Action
1. Call `discover_fields("{doc_slug}", response)` to add new fields to the registry.
2. Review removed fields — remove from YAML if the integration no longer returns them.
3. Redeploy to sync the registry.
```

   - If `has_drift` is false: note "no drift" in the summary (no issue written).

2. If no field doc exists for this integration (confirmed in Phase 2): call
   `discover_fields("{integration}", response)` to auto-generate a skeleton YAML.
   Note in the summary that docs were auto-generated and need human enrichment.

---

## Phase 4 — Built-In Tool Spot Checks

**Goal:** Verify the internal gateway tools are functional.

1. **Notes tool** — Call `list_notes()`. If it returns an error (not a 404/empty list),
   write an issue: `notes-tool-error-{date}` with the error message and note that
   `GITHUB_TOKEN` and `GITHUB_REPO` env vars should be checked.

2. **Registry tool** — Call `list_field_integrations()`. If it errors, write an issue:
   `registry-tool-error-{date}`. If it returns an empty list but Phase 1 showed proxied
   integrations, note that the field registry may not have been populated.

3. **Telemetry** — From the `get_tool_stats()` result saved in Phase 1, check
   `summary.high_error_rate`. If any tools appear there, write a single issue:
   `high-error-rate-tools-{date}` listing each tool, its error rate, and call count.

---

## Phase 5 — Write Summary Report

After all phases are complete, write a summary note (not an issue) using `write_note`:

- Filename: `gateway-health-{YYYY-MM-DD}`
- Content template:

```markdown
# Gateway Health Check — {YYYY-MM-DD}

## Result: {PASS | PASS WITH WARNINGS | FAIL}

**Gateway status:** {ok | unreachable}
**Integrations tested:** {N}
**Issues written:** {N}

## Integration Status

| Integration | Smoke Call | Auth | Field Docs | Schema Drift |
|-------------|-----------|------|------------|--------------|
| attio       | {ok|fail} | {ok|fail} | {ok|missing} | {none|drift} |
| exa         | ...       | ...  | ...        | ...          |
| apollo      | ...       | ...  | ...        | ...          |
| github      | ...       | ...  | ...        | ...          |

## Issues Written

{List each issue slug and one-line description, or "None" if clean.}

## Built-In Tools

- Notes: {ok | error}
- Registry: {ok | error}
- Telemetry high-error tools: {none | list}
```

---

## Issue Slug Naming Convention

| Problem | Slug format |
|---------|-------------|
| Auth/credential failure | `{integration}-auth-failure-{YYYY-MM-DD}` |
| Tool call error (non-auth) | `{integration}-tool-error-{YYYY-MM-DD}` |
| Missing field docs | `{integration}-missing-docs-{YYYY-MM-DD}` |
| Schema drift detected | `{integration}-schema-drift-{YYYY-MM-DD}` |
| High error rate tools | `high-error-rate-tools-{YYYY-MM-DD}` |
| Built-in tool failure | `{tool_name}-error-{YYYY-MM-DD}` |

If two issues of the same type exist for one date, append `-2`, `-3`, etc.

---

## When to Stop Early

- If `health_check()` fails → stop, write no issues (gateway is unreachable, not individual tool failures)
- If `write_issue` itself fails → record issues in your response text; note that the notes repo may be misconfigured
- If an integration has zero tools in the inventory → skip it; the proxy failed at startup (will show in gateway logs)
