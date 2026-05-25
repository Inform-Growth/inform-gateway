# Template, dogfood, and client gateways

This repo wears three hats. Keeping them straight is the difference between "ship a fix to all clients in one PR" and "every client repo silently drifts."

```
┌──────────────────────────────────────────────────────────────────────┐
│  inform-gateway (this repo)                                          │
│                                                                      │
│   main branch                    template/clean-gateway branch       │
│   ───────────                    ──────────────────────────          │
│   The dogfood deployment.        The published template surface.     │
│   - Runs as Inform Growth's      - Empty mcp_connections.json        │
│     own gateway in production.   - No custom Python tools            │
│   - Carries experiments, custom  - No field schemas                  │
│     integrations, project        - No dogfood-only plans/specs       │
│     plans, dogfood prompts.      - Source of truth for clients.      │
│                                                                      │
└─────────────┬──────────────────────────────┬─────────────────────────┘
              │                              │
              │ copier copy                  │ .github/workflows/
              │ (initial scaffold)           │ distribute.yml
              │                              │ (ongoing core sync)
              ▼                              ▼
   ┌────────────────────┐         ┌────────────────────────┐
   │ new client repo    │  ◄──────│ existing client repos   │
   │ (one-time creation)│         │ (registered downstream) │
   └────────────────────┘         └────────────────────────┘
```

## Why two branches in one repo

We considered splitting "template repo" and "dogfood repo" into separate repos. We didn't, because:

- A single repo lets us promote stable changes from dogfood to template with a normal git workflow (cherry-pick or merge into `template/clean-gateway`) instead of cross-repo backports.
- The distribute workflow runs from this repo, so the template files have to live somewhere in this repo anyway.
- `main` having extra files is fine; the template branch is what clients see.

The discipline is: **experiments live on `main`. Stable changes get promoted to `template/clean-gateway` before they reach clients.** Don't trigger `distribute.yml` from `main` — trigger it from the template branch (see "Distributing a core change" below).

## The core / custom boundary

Every file in the repo falls into one of four buckets:

| Bucket | What | Lives in | Synced to clients? |
|---|---|---|---|
| **Core (shared)** | Infra all clients need: telemetry, admin API, MCP proxy, task manager, admin UI shell + tasks views, Dockerfile, pyproject, baseline CI workflow, pre-commit config, the catalog | See `CORE_FILES` + `CORE_DIRS` in `.github/workflows/distribute.yml` | Yes — via distribute.yml PRs |
| **Template-only** | Initial scaffolding: copier.yml answers, empty connections, default prompts | Anywhere in `template/clean-gateway` not in CORE_FILES | No (Copier renders once on init; never re-synced) |
| **Custom (client-owned)** | Per-deployment integrations, field schemas, prompts, plans, installed catalog bundles | Anything outside CORE_FILES | No — each repo owns and evolves these |
| **In-house (secret sauce)** | Inform Growth tooling — the agentic test/fix loop, future audit tooling | `.inform/` | No — excluded from copier scaffolds AND from distribute.yml. Delivered to client repos via manual installers when engaged. |

### Current synced set

Defined in `.github/workflows/distribute.yml`:

**`CORE_FILES`** (individual files):

- Backend infra: `remote-gateway/core/{admin_api,telemetry,mcp_proxy}.py`, `remote-gateway/tools/_core/task_manager.py`
- Admin UI shell: `remote-gateway/admin-ui/src/{App.tsx,lib/api.ts,lib/auth.ts,components/layout/AppShell.tsx,routes/LoginPage.tsx,hooks/useTasks.ts}`
- Admin UI tasks views: `remote-gateway/admin-ui/src/routes/tasks/{TasksPage,TasksTable,TaskDetailSheet}.tsx`
- Catalog tooling: `scripts/{__init__.py,install_integration.py,test_install_integration.py}`
- Build/runtime: `Dockerfile`, `pyproject.toml`

**`CORE_DIRS`** (whole directory trees):

- `catalog/` — pre-baked integration bundles. Clients install selected ones via Copier multi-select at scaffold time or `python scripts/install_integration.py <slug>` later. The catalog source is shared; the *installed* files at `remote-gateway/tools/integrations/<slug>.py` are client-owned.

### Explicitly excluded from sync

These look core but are intentionally per-deployment:

| File | Why excluded |
|---|---|
| `remote-gateway/core/mcp_server.py` | Each deployment owns its tool registration — which integrations are wired up, which custom tools are loaded |
| `remote-gateway/tools/notes.py` | GitHub-Issues-backed notes are inform-gateway internal; downstream deployments use DB-backed storage instead |
| `docs/superpowers/plans/` and `docs/superpowers/specs/` | Planning docs are repo-specific; each client maintains their own |
| `mcp_connections.json` | Per-deployment integration list (the install script merges into it; not synced wholesale) |
| `remote-gateway/context/fields/*.yaml` | Field schemas are per-integration and per-deployment |
| `remote-gateway/prompts/init.md` | Operator instructions are tuned per deployment |
| `remote-gateway/tools/integrations/<slug>.py` | Once a client installs an integration from the catalog, they own the runtime copy. Catalog source is synced; installed copies are not. |
| `.inform/**` | Inform Growth in-house tooling (QA fix loop, etc.). Delivered only via manual installers under `.inform/<area>/scripts/install_*.sh`. |

## Path-based convention (going forward)

The current `CORE_FILES` is an enumerated list. That works but grows brittle as new shared modules appear. The target convention is **path-based**: a new file's location tells you whether it gets distributed.

| Path | Bucket | Notes |
|---|---|---|
| `remote-gateway/core/**` | Core | Infra modules. Add to CORE_FILES when adding new shared modules here. |
| `remote-gateway/tools/_core/**` | Core | Shared tool modules (task manager, profile, onboarding, skills). |
| `remote-gateway/admin-ui/src/lib/**` | Core | Shared API/auth/utility libs. |
| `remote-gateway/admin-ui/src/routes/tasks/**` | Core | Shared task views. |
| `remote-gateway/tools/integrations/<name>.py` | **Custom** | Per-deployment integration tool implementations. `apollo.py`, `attio.py`, `email_tools.py`, `wiza.py` live here. |
| `remote-gateway/context/fields/<name>.yaml` | Custom | Field schemas the deployment uses. |
| `mcp_connections.json` | Custom | Per-deployment integration list. |
| `remote-gateway/prompts/**` | Custom | Per-deployment prompts (except `init.md` if standardized later). |
| `docs/superpowers/**` | Custom | Per-deployment planning docs. |
| `skills/**` | Mixed | Some are framework-level (e.g. `mcp-builder`); some are deployment-specific. Per-skill decision today; consider splitting into `skills/_core/` vs `skills/custom/` later. |

When the migration to `tools/integrations/` lands, distribute.yml can drop the enumerated list in favor of "sync everything under these directory globs."

## Common operations

### Adding a new client repo

1. **Scaffold**:
   ```bash
   pip install copier
   copier copy --vcs-ref template/clean-gateway gh:Inform-Growth/inform-gateway ./<client-slug>
   ```
   Copier prompts for `project_name`, `project_slug`, `gateway_url`, `github_org`, `admin_ui_title`, `deployment_repo`.

2. **Push to GitHub** as a fresh repo under your org.

3. **Register for ongoing sync**: add `"owner/repo"` to the matrix in `.github/workflows/distribute.yml` (on the template branch).

### Updating an existing client repo with a core change

1. Make the change on `main` first — verify it works in dogfood.
2. Cherry-pick / merge the change into `template/clean-gateway`.
3. Trigger the `distribute` workflow **from `template/clean-gateway`**:
   - GitHub → Actions → "Distribute Core Files to Downstream Repos" → Run workflow → select the `template/clean-gateway` branch.
   - Optionally restrict to specific repos via the `repos` input (comma-separated).
   - Use `dry_run: true` first to see the diff before opening PRs.
4. Each registered client gets a `template-sync/<sha>` PR. Merge when ready.

> **Why trigger from the template branch and not main?** distribute.yml checks out whatever ref it runs on and copies from there. Running it from main would distribute whatever dogfood state main is in. Running from `template/clean-gateway` distributes only what's been promoted.
>
> The workflow now enforces this with a `guard` job that refuses to run unless `github.ref == refs/heads/template/clean-gateway`. The `allow_non_template_ref: true` input is an explicit override for emergencies — it emits a warning and proceeds.

### Adding a new file to the synced core set

1. Add the file's path to `CORE_FILES` in `.github/workflows/distribute.yml` (on the template branch).
2. Add the file (or a working version of it) to `template/clean-gateway`.
3. Next distribute run will pick it up for clients that don't have it yet, or sync changes for ones that do.

### Adding a new custom integration (dogfood or client)

1. Add the proxy entry to `mcp_connections.json` (if it's an upstream MCP).
2. For Python-implemented tools, add the file at `remote-gateway/tools/integrations/<name>.py` and register it in `mcp_server.py`.
3. Add a field schema at `remote-gateway/context/fields/<name>.yaml` if the tool returns structured data.
4. These files are **not synced** — they live and die with this deployment.

### Promoting a dogfood experiment to template

When a custom integration or pattern proves stable in dogfood and should be standard:

1. Decide whether it's truly universal (becomes core) or just a useful starting point (stays as scaffold). Ask: would *every* client want this on day one?
2. If core: move to a shared path (e.g. `remote-gateway/tools/_core/` or one of the directories above) and add to `CORE_FILES`.
3. If scaffold: add to `template/clean-gateway` as a starting file, but don't add to `CORE_FILES` (clients can customize without re-sync overwriting).

## In-house tooling (`.inform/`)

Inform Growth maintains tooling that's part of *our* service offering but isn't standard for every client gateway. It lives under `.inform/` and is:

- **Excluded from Copier scaffolds** via `copier.yml`'s `_exclude` block — never reaches a fresh client repo via `copier copy`.
- **Excluded from distribute.yml** — `.inform/**` is not listed in `CORE_FILES` or `CORE_DIRS`, so updates never auto-PR to clients.
- **Delivered to client repos via manual installers** when we're engaged for ongoing maintenance. Example: `.inform/qa/scripts/install_qa_tooling.sh /path/to/client-repo` rsyncs the QA tooling into a client.

Current areas:

- **`.inform/qa/`** — agentic test/fix loop. `scripts/fix_until_green.sh` runs the test command, hands failures to Claude via the CLI, applies edits, re-runs, repeats until green or the iteration cap is hit. A companion `SKILL.md` makes the same pattern available inside interactive Claude Code sessions. See `.inform/qa/README.md`.

## Catalog vs installed integrations

Two layers, distinct ownership:

| Layer | Path | Ownership | Synced? |
|---|---|---|---|
| **Catalog source** | `catalog/integrations/<slug>/` | Inform Growth (this repo) | Yes (whole tree via `CORE_DIRS`) |
| **Installed runtime** | `remote-gateway/tools/integrations/<slug>.py` and entries in `mcp_connections.json` | Client gateway | No |

So: catalog updates flow downstream automatically; installed integrations don't. To pick up a catalog fix, the client re-runs `python scripts/install_integration.py <slug>` (with `--force` if their copy has diverged).

## Known drift / next steps

- **`skills/`** mixes framework skills and deployment-specific skills. A `skills/_core/` vs `skills/custom/` split would make distribution decisions trivial.
