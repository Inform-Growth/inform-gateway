# Plan: Integrations catalog for client gateways

**Status:** Designed, awaiting implementation approval.
**Date:** 2026-05-22.

## Goal

When scaffolding a new client gateway repo from the template, let the operator choose which pre-baked integrations to install. Same mechanism works post-scaffold via a CLI for adding more integrations later.

## Design decisions (from user)

| Question | Decision |
|---|---|
| Catalog location | Separate `catalog/` directory at repo root |
| When to choose | Copier multi-select at scaffold time **and** `install_integration.py` for post-scaffold additions |
| Update ownership | Client owns installed file; catalog source is the only thing distribute.yml syncs |
| Bundle contents | `tool.py`, `connection.json` (for proxies), `README.md`. Field schemas not required. |

## Repo structure after this lands

```
catalog/
  integrations/
    apollo/
      tool.py            # the register(mcp) module
      README.md          # description, env vars, examples, dependencies
      # no connection.json — Apollo is Python-implemented, no MCP proxy
    attio/
      tool.py
      connection.json    # MCP proxy snippet (attio-mcp via stdio)
      README.md
    buffer/
      connection.json    # MCP proxy only, no tool.py
      README.md
    exa/
      connection.json
      README.md
    github/
      connection.json
      README.md
    google/
      connection.json
      README.md
    wiza/
      tool.py
      README.md
    email_tools/
      tool.py
      README.md
  catalog.yaml           # registry: maps slugs → metadata for Copier prompts
                         #   - name, description, required env vars,
                         #     install kind (python|proxy|both), default-selected

scripts/
  install_integration.py # CLI: install_integration.py <slug> [--force]

remote-gateway/tools/integrations/
  # populated by install_integration; this is the "installed" set
  # client-owned; not synced by distribute.yml

remote-gateway/mcp_connections.json
  # merged in by install_integration when a connection.json snippet exists
```

## Two layers, two ownership models

- **`catalog/`** — synced to all client repos via `distribute.yml` (becomes part of CORE_FILES). Clients always have the latest catalog and can install new integrations from it.
- **`remote-gateway/tools/integrations/`** and **`mcp_connections.json`** — client-owned. Once an integration is installed, the client can customize it. Not synced.

This means: catalog updates flow downstream automatically; installed integration updates do not. To get an upstream fix, the client re-runs `install_integration.py <slug>` and resolves any conflicts (or accepts the upstream version).

## The catalog manifest (catalog.yaml)

```yaml
# catalog/catalog.yaml — registry of available integrations
version: 1
integrations:
  apollo:
    name: Apollo.io
    description: Lead enrichment and people/company search via Apollo REST API.
    kind: python              # python | proxy | both
    default_select: true      # include in Copier multi-select by default
    env_vars:
      - APOLLO_API_KEY
    register_call: |          # snippet inserted into mcp_server.py
      _apollo_tools.register(mcp)
  attio:
    name: Attio CRM
    description: Attio record search/create/upsert (CRM data).
    kind: both
    default_select: true
    env_vars:
      - ATTIO_API_KEY
    register_call: |
      _attio_tools.register(mcp)
  buffer:
    name: Buffer
    description: Social media post scheduling via Buffer's MCP server.
    kind: proxy
    default_select: false
    env_vars:
      - BUFFER_ACCESS_TOKEN
  # ... etc
```

## install_integration.py CLI

```
python scripts/install_integration.py <slug> [--force] [--dry-run]
```

Behavior:
1. Look up `<slug>` in `catalog/catalog.yaml`.
2. If `kind` includes `python`: copy `catalog/integrations/<slug>/tool.py` → `remote-gateway/tools/integrations/<slug>.py`. If destination exists and differs from catalog: warn and require `--force` (preserves client customizations).
3. If `kind` includes `proxy`: read `catalog/integrations/<slug>/connection.json`, merge into `remote-gateway/mcp_connections.json` under `connections.<slug>`. If already present: warn and require `--force`.
4. If `register_call` is set: append the snippet to a marked block in `mcp_server.py` (between `# BEGIN catalog-managed registrations` and `# END catalog-managed registrations` sentinels). Avoid duplicates.
5. Print env vars the operator needs to set, plus a link to `catalog/integrations/<slug>/README.md`.

`--dry-run`: print what would change, no writes.

## Copier integration

`copier.yml` adds a multi-select question that reads the catalog:

```yaml
integrations:
  type: str
  multiselect: true
  help: "Which pre-baked integrations to install? (you can add more later via scripts/install_integration.py)"
  choices: # generated from catalog.yaml at runtime via a Copier `_tasks` pre-step,
           # OR enumerated explicitly if Copier doesn't support dynamic choices.
    apollo: "Apollo.io — lead enrichment & search"
    attio:  "Attio CRM — record search/create/upsert"
    buffer: "Buffer — social media scheduling"
    exa:    "Exa — web search"
    github: "GitHub — file ops + issue read"
    google: "Google Workspace — Gmail + Calendar + Drive"
    wiza:   "Wiza — person enrichment"
    email_tools: "Email body normalizer"
  default: [apollo, attio, exa]   # most common starter set
```

Then a `_tasks:` block runs `scripts/install_integration.py` for each selected slug after Copier renders the base template.

If Copier's choices can't be dynamic, the catalog and copier.yml stay manually in sync — adding a new integration means editing two files. Acceptable cost.

## What this means for the existing dogfood deployment

On `main`:
1. Create `catalog/integrations/<slug>/` bundles for each integration currently wired up (apollo, attio, buffer, exa, github, google, wiza, email_tools).
2. The runtime files at `remote-gateway/tools/integrations/<name>.py` stay where they are (already there from the recent migration). The catalog versions are the canonical "what would be installed in a fresh client."
3. Document the promotion rule: "when an integration matures in dogfood, promote a copy of the runtime file to `catalog/integrations/<slug>/tool.py`."

## Sequenced implementation tasks

1. **Catalog scaffolding** — create `catalog/integrations/` directory and `catalog/catalog.yaml` manifest. Empty bundles.
2. **Populate catalog from current dogfood** — for each of apollo, attio, buffer, exa, github, google, wiza, email_tools: write tool.py (if applicable), connection.json (if applicable), README.md.
3. **install_integration.py script** — implement with `--dry-run` and `--force` flags; write tests.
4. **copier.yml multi-select + `_tasks` hook** — call install_integration for each selected slug at scaffold time. Test on a temp directory.
5. **Distribute the catalog** — add `catalog/**` and `scripts/install_integration.py` to `CORE_FILES` in `distribute.yml`.
6. **Promote to template branch** — once everything works on `main`, cherry-pick the catalog scaffolding + script + Copier changes (NOT the populated bundles for dogfood-specific integrations, unless we want them as the default starter set) to `template/clean-gateway`.
7. **Docs** — update `docs/template-and-distribution.md` with a "Catalog" section; remove the catalog item from "Known drift / next steps."

## Open questions to revisit before implementing

- Should `register_call` injection into `mcp_server.py` use sentinel comments, or should we generate the whole import/register block from the catalog manifest? Sentinel approach preserves manual edits; full generation is cleaner but loses customization.
- Should the catalog ship field schemas too? User opted out for now, but the YAML schemas in `remote-gateway/context/fields/` would benefit from the same install mechanism. Easy to add later as a fourth bundle file.
- The "skills" in `skills/` (mcp-builder, gateway-health-check, add-mcp-integration) — should they be cataloged the same way? Probably yes, but as a separate concern from MCP integrations. Likely a follow-up plan.
- Test strategy for the Copier multi-select: probably a tiny integration test that runs `copier copy` against a temp dir with `--data integrations=apollo,attio` and asserts the right files appear. Worth doing.
