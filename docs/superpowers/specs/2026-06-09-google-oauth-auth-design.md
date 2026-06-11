# Google Auth Redesign — Per-Client Internal OAuth

**Date:** 2026-06-09
**Status:** Approved
**Supersedes:** the service-account credential model in `2026-06-08-google-analytics-design.md` (the analytics-mcp proxy itself is unchanged)

## Summary

Replace the service-account credential model for Google Analytics with **one internal OAuth app per client deployment**, shared by every Google integration (Workspace MCP and analytics-mcp today; Search Console, Ads, BigQuery later). Each MCP deployment serves exactly one Workspace org. A single shared OAuth credential per deployment ships now; the architecture documents a path to per-API-key credentials (employee X's gateway key → employee X's Gmail/Calendar/GA token) without redesign.

## Why

The 2026-06-08 design used a service account whose email is granted access in each Google product. Deploying it surfaced three classes of friction, all hit on day one:

1. **GA org user policy** — Google Marketing Platform org policies can forbid adding emails outside the org (`*.iam.gserviceaccount.com` included) to GA properties. The policy console is obscure and client-side.
2. **GA UI bugs** — even valid service-account emails are intermittently rejected with "this email does not match a Google account" (multiple open Google support threads).
3. **Wrong-project API enablement** — the SA lived in a stray auto-created GCP project (`gen-lang-client-*`) with the Analytics Admin API disabled, producing 403s that look like auth failures.

Domain-wide delegation was considered (and would also work) but was rejected because GA does not participate in DWD impersonation without forking `analytics-mcp` or owning native GA tool code, and because the operator prefers an OAuth-shaped credential model for the per-user future.

**Why internal OAuth avoids the classic OAuth problems:** an OAuth app with consent screen set to *Internal* (users in the app's own Workspace org only) requires **no Google verification** (no CASA audit for Gmail scopes, no 7-day refresh-token expiry, no 100-user cap) and is **not subject to third-party app blocking** in that org. Because tokens carry the connecting user's own access, nobody is ever added to GA Admin — the org policy, the UI bug, and per-property grants all disappear. Each client owns their app: no shared Inform Growth OAuth client, no cross-tenant blast radius.

## Decision

| Aspect | Choice |
|---|---|
| Credential | OAuth refresh tokens from a client-owned **internal** OAuth app |
| App location | A GCP project inside the client's own Google org |
| Scope (now) | One shared credential per deployment, consented by the operator |
| Scope (future) | Credentials resolved per gateway API key (see Future: per-key credentials) |
| GA tools | Unchanged `analytics-mcp` proxy; auth becomes an `authorized_user` ADC file |
| Workspace tools | Unchanged `workspace-mcp` single-user OAuth (already this pattern) |

## Architecture

### The per-client OAuth app (one-time, per client)

Created in a GCP project belonging to the client's Google org:

1. GCP project (new or existing) in the client org.
2. Enable APIs: `analyticsdata.googleapis.com`, `analyticsadmin.googleapis.com`, plus the Workspace APIs the deployment uses (Gmail, Calendar, Drive, Docs). Scriptable: `gcloud services enable ...` (one documented command).
3. OAuth consent screen → **Internal**.
4. Create OAuth client (Desktop type). Record client ID + secret.

OAuth clients cannot be created via API (Google limitation, except IAP), so steps 3–4 are console clicks. This is the onboarding cost accepted in exchange for never touching GA Admin, Marketing Platform policies, or DWD grants. Inform Growth drives this on the onboarding call.

### Credential minting — `scripts/google_auth_setup.py` (new)

A small local helper (google-auth-oauthlib loopback flow) run by whoever is consenting — the operator, on a machine with a browser:

```
python scripts/google_auth_setup.py --client-secrets client_secret.json \
    --quota-project <client-project-id>
```

- Requests only the scopes consumed via the ADC file — GA `analytics.readonly` today, with an `--extra-scopes` flag for future ADC-based integrations. Workspace scopes are deliberately excluded: workspace-mcp runs its own consent flow and never reads the ADC file, so including them would only widen the credential's blast radius.
- Prints two artifacts:
  - **`GOOGLE_ADC_JSON`** — an `authorized_user` ADC JSON (`client_id`, `client_secret`, `refresh_token`, `quota_project_id`) for Railway. Consumed by analytics-mcp (and any future ADC-based integration).
  - The `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` values for workspace-mcp (unchanged mechanism).
- Validates before printing: makes one `get_account_summaries`-equivalent Data/Admin API call so a bad consent fails at mint time, not at deploy time.

`quota_project_id` is required for `authorized_user` ADC against the GA APIs; it points at the client project where the APIs are enabled, and the consenting user (a member of that org) satisfies `serviceusage.services.use`.

### Runtime changes

- **Dockerfile CMD**: decode `GOOGLE_ADC_JSON` (falling back to the legacy `GOOGLE_SA_JSON` name for already-deployed instances) to `/tmp/google-adc.json`, export `GOOGLE_APPLICATION_CREDENTIALS`. ADC autodetects the JSON type, so `authorized_user` and `service_account` contents both keep working — the fallback is genuinely backward compatible.
- **`mcp_connections.json`**: no structural change. `google-analytics` keeps `GOOGLE_APPLICATION_CREDENTIALS`; `google` keeps its OAuth env vars. Update the `_comment` on `google-analytics` to describe the OAuth model and remove the service-account grant instructions.
- **Docs**: a per-client onboarding runbook (`docs/google-auth-onboarding.md`) covering the four app-setup steps, the helper invocation, and the two Railway vars. The GA property ID continues to be documented in the org profile per the prior design.

### What this removes

- Service account keys (long-lived secrets in env vars / on disk). The `gen-lang-client-0075541127` SA and its key file at the repo root are deleted after migration.
- All GA Admin / Marketing Platform grant steps from onboarding.
- The "wrong project" failure mode — APIs are enabled in the same client project that owns the OAuth app, checked by the helper at mint time.

## Token lifecycle & operations

Internal-app refresh tokens are long-lived but not immortal: revoked on password change (for Gmail scopes), admin revocation, or ~6 months of disuse. Mitigations:

- The helper's mint-time validation catches dead-on-arrival credentials.
- **Token-health surfacing (this phase):** extend the existing `health_check` tool to attempt a trivial Google API call when Google credentials are configured, reporting `google_auth: ok | failing` — so a dead token is a visible 2-minute re-consent (re-run the helper, update one Railway var), not a mystery outage.
- Re-consent is non-interactive for the gateway: only the Railway var changes; no redeploy of code.

## Future: per-key credentials (documented direction, not built now)

The target: five employees, five gateway API keys, each key using *that employee's* Gmail/Calendar/GA tokens.

- The gateway already resolves every request to a `user_id` (`_AuthMiddleware`). The extension is a `google_credentials` table keyed by `user_id`, holding per-user refresh tokens minted by the same internal app (each employee runs the same consent — internal apps allow any org member).
- Connection-level credential resolution: the proxy injects the per-user credential into the upstream call instead of the deployment-shared one. `workspace-mcp` supports multi-user operation (per-call `user_google_email` / OAuth 2.1 bearer mode); ADC-based integrations need per-user credential files or a gateway-side token exchange — that choice is deliberately deferred to the per-key phase's own design doc.
- A gateway-hosted consent flow (`/admin/google/connect` redirect URI on the gateway's own domain) replaces the local helper script when this ships, so employees onboard with a link instead of a CLI.

Nothing in the current phase blocks this: the credential is already externalized from the integrations, and adding per-user resolution is additive.

## Migration (dogfood deployment)

1. Confirm the existing workspace OAuth app's consent screen is **Internal** (it lives in an Inform Growth project); add the GA read scope to the helper run.
2. Run `google_auth_setup.py` with the existing client ID/secret; set `GOOGLE_ADC_JSON` in Railway (replacing `GOOGLE_SA_JSON`).
3. Smoke-test all seven `google-analytics__*` tools through the gateway (discovery tools now reflect the operator's GA access, so `get_account_summaries` returns real accounts).
4. Document property ID `443879695` in the org profile.
5. Cleanup: delete the SA key file from the repo root, delete the `inform-gateway-ga4-reader` service account, remove `GOOGLE_SA_JSON` from Railway.

## Template impact

- Dockerfile change and helper script are core files (sync to template via the normal distribute path).
- The onboarding runbook ships in template docs; `mcp_connections.json` remains consumer-owned and empty by default.

## Testing

- Unit test for the Dockerfile env fallback logic is impractical (shell); instead the helper script gets a unit test for ADC-JSON assembly (given fake client secrets + token, emits valid `authorized_user` JSON with `quota_project_id`).
- `health_check` Google-auth extension gets a test with mocked credentials present/absent/failing.
- End-to-end: the migration smoke test (step 3) is the acceptance gate, run through the deployed gateway.

## What does not change

- `analytics-mcp` and `workspace-mcp` packages and their tool surfaces
- The init gate, telemetry, field registry (`google-analytics.yaml` schema stays)
- Per-user tool permissions
