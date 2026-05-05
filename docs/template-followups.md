# Template followups

Deferred items from the template-prep work (`chore/template-prep`). Each entry has enough context to be picked up cold.

## High priority — do before standalone-repo extraction

### Delete `template/hubspot-gateway` branch

The HubSpot pre-wire that lived as a separate branch is now an entry in `remote-gateway/mcp_connections.example.json` (per Phase 6 of `2026-05-05-template-branch-prep`). The branch is redundant.

**Action:** when promoting `template/clean-gateway` to a standalone repo, also delete `template/hubspot-gateway` from origin:

```bash
git push origin --delete template/hubspot-gateway
git branch -D template/hubspot-gateway  # local
```

Don't delete before then — keeps a fallback in case the example-config approach has a wrinkle in early client testing.

### Pin Copier as a documented prerequisite

The README's Quickstart says `pip install copier`, but doesn't pin a version. Copier 9.x changed the `_jinja_env` config key to `_envops` (caught during Batch 3 smoke testing). If a client uses Copier 8.x or earlier, the template's `copier.yml` will silently produce wrong output.

**Action:** either bump the README to `pip install copier>=9` or add a `_min_copier_version: "9.0.0"` declaration in `copier.yml`. Probably both.

## Medium priority — known noise to clean when convenient

### Fix the pytest `testpaths` warning

Every `pytest` run prints:

```
PytestConfigWarning: No files were found in testpaths; consider removing or adjusting your testpaths configuration. Searching recursively from the current directory instead.
```

The cause: `pyproject.toml` has `testpaths = ["tests"]` but tests live at `remote-gateway/tests/`. Pytest's recursive fallback works, so all 176 tests run — but the warning is noise.

**Action:** change `pyproject.toml` to `testpaths = ["remote-gateway/tests"]`.

### Fix the deprecated `_telemetry._enabled` private access in `admin_api.py`

`_get_primary_org_id` (line ~52) reads `telemetry._enabled` directly. Works, but reaches across the abstraction. Consider exposing a public `is_enabled()` on `TelemetryStore` or guard differently.

Not urgent — just architectural hygiene.

## Future template variants

### n8n premium variant

n8n integration scoping lives on the `feat/n8n-batch-integration` branch (docs only — `docs/n8n-integration-scoping.md`). Per the user's decision in Batch 1 planning, n8n will ship as a separate template variant once the integration MVP lands. Naming convention TBD — likely `template/n8n-gateway` paralleling the now-deleted `template/hubspot-gateway`.

This is a premium offering, not a default for clean-gateway.

## Ruff config decisions worth re-examining later

### `E402` is suppressed for `remote-gateway/tests/*.py`

Per-file-ignore in `pyproject.toml`. Justification: test files do `sys.path.insert(0, ...)` then import, which is the standard pattern for testing modules from `remote-gateway/core/` without installing them as a package.

If we ever convert the gateway to a real installable package (e.g. `pip install agent_gateway` with a proper `agent_gateway/` package directory), this suppression should be revisited — the tests could just `from agent_gateway.core import telemetry` and the sys.path mutation goes away.

### `N806` on `_TASK_BYPASS` in `test_task_gate.py`

Inline `# noqa: N806` because the test sets up a local copy of the same constant as the module-level `_TASK_BYPASS` in `mcp_server.py`. Keeping the same UPPER_CASE name makes the connection grep-visible.

If the test ever stops mirroring the module constant, drop the `noqa`.

## Things explicitly NOT done in this batch

- **No GitHub Actions added.** The Inform-specific operator-promotion pipeline was deleted in Phase 8 (Batch 3). Clients add their own CI per their preference.
- **No `_min_copier_version` declared.** See "Pin Copier" above.
- **No promotion to a standalone repo.** Per the user's Batch 1 decision, that happens after local testing of the template branch.
- **No MCP-client-driven `run_skill("skill-creator", ...)` smoke test.** SQLite presence + admin API visibility was deemed sufficient for v1. If a future smoke test wants end-to-end coverage of the runtime path, the `mcp` CLI from `mcp[cli]` is the right tool.
