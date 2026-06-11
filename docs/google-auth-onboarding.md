# Google Auth Onboarding (Per-Client Internal OAuth)

One internal OAuth app per client deployment is the single Google credential
story for the gateway (GA4 today; Workspace via the same app; Search Console /
Ads / BigQuery later). Design: `docs/superpowers/specs/2026-06-09-google-oauth-auth-design.md`.

Each MCP deployment serves exactly one Workspace org. The credential carries
the consenting user's own access — nobody is ever added to GA Admin, and no
Google verification is needed (the app is Internal to the client's org).

## One-time client setup (~20 min, drive it on the onboarding call)

1. **GCP project** — new or existing, inside the client's Google org.
   The client needs a free Google Cloud account tied to their Workspace.
2. **Enable APIs** (replace `<project>`):
   ```bash
   gcloud services enable analyticsdata.googleapis.com analyticsadmin.googleapis.com \
       gmail.googleapis.com calendar-json.googleapis.com drive.googleapis.com \
       docs.googleapis.com --project=<project>
   ```
3. **OAuth consent screen** — APIs & Services → OAuth consent screen → User type:
   **Internal**. (This is what removes verification, token expiry caps, and
   third-party app blocking.)
4. **OAuth client** — APIs & Services → Credentials → Create credentials →
   OAuth client ID → **Desktop app**. Download the JSON.

## Mint the deployment credential

On any machine with a browser, as the user whose Google access the gateway
should have (typically the operator):

```bash
uv run scripts/google_auth_setup.py \
    --client-secrets client_secret_<...>.json \
    --quota-project <project>
```

The script runs the consent flow, validates the credential against the GA
Admin API (fails loudly at mint time if an API is disabled or access is
missing), and prints:

- `GOOGLE_ADC_JSON` — set in Railway. The container writes it to
  `/tmp/google-adc.json` and exports `GOOGLE_APPLICATION_CREDENTIALS`.
- A reminder that `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`
  (workspace-mcp) come from the same OAuth app.

Then: document the client's GA4 property ID in the org profile
(`profile_update`) so agents know which property to pass on report calls.

## Verifying / monitoring

- `health_check` returns `google_auth: ok | not_configured | failing: <reason>`.
  It exercises the refresh token on every call.
- `failing: invalid_grant` means the token was revoked (password change on
  Gmail-scoped credentials, admin revocation, or ~6 months unused). Fix:
  re-run the mint step and update the one Railway var. No redeploy needed
  beyond Railway's automatic restart on env change.

## Legacy

Deployments still on a service-account key (`GOOGLE_SA_JSON`) keep working —
the Dockerfile falls back to that env var and ADC autodetects the JSON type.
Migrate them to `GOOGLE_ADC_JSON` opportunistically.
