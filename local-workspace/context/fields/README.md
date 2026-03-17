# Field Definitions (Local Mirror)

This directory is a read-only mirror of `remote-gateway/context/fields/`.

**Do not edit files here directly.** Field definitions are managed on the remote
gateway and propagate here via `git pull`.

## How to Use

When your local agent encounters an unfamiliar field from an integration, call the
gateway's `lookup_field` tool before interpreting or presenting the data:

```
lookup_field(integration="stripe", field_name="mrr")
```

## How Definitions Are Created and Updated

1. **New integration** — admin or agent calls `discover_fields(integration, sample_response)`
   on the gateway. It auto-generates YAML entries with inferred types.
2. **Descriptions enriched** — an agent or admin fills in `description` and `notes`
   in `remote-gateway/context/fields/<integration>.yaml`.
3. **Drift detected** — `check_field_drift(integration, fresh_sample)` compares a live
   response against the registry and reports new or removed fields.
4. **Review and merge** — a human reviews the drift report and approves the YAML update.
5. **Propagation** — `git pull` updates this mirror; the gateway serves the latest
   definitions immediately on redeploy.

## Available Integrations

Run `list_field_integrations()` on the gateway to see the current list.
