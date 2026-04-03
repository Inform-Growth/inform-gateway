---
date: 2026-04-03
slug: attio-mcp-setup
status: active
---

# Session: attio-mcp-setup

**Date:** 2026-04-03
**Integration(s):** attio
**Goal:** Connect Attio MCP, explore the workspace, and create field definitions for all core objects.

## Discoveries

- Attio MCP connects via hosted server at `https://mcp.attio.com/mcp` with `Authorization: Bearer ${ATTIO_API_KEY}` header pattern.
- Workspace is "Inform Growth" — single member (Jaron Sander, admin).
- Three core objects with full attribute sets: **people** (29 fields), **companies** (32 fields), **deals** (9 fields).
- Deals pipeline has 4 stages: Lead → In Progress → Won 🎉 → Lost.
- Companies have two separate revenue signals: `estimated_arr_usd` (banded select enum) and `funding_raised_usd` (exact currency in USD) — different use cases.
- `connection_strength` is Attio-computed on both people and companies (Very weak → Very strong) — useful for relationship health queries.
- `associated_workspaces` on companies suggests a product-led growth data model (companies linked to product workspaces).
- Attio deduplicates companies on `domains` (not `name`) — domain is the primary key for company dedup.

## Decisions

- Used `type: http` with Bearer token auth for `.mcp.json`, matching existing Exa pattern.
- Created three separate YAML files in `context/fields/` (attio-people, attio-companies, attio-deals) rather than one combined file — easier to maintain and query per object.
- Mapped Attio-specific types (personal-name, interaction, actor-reference, record-reference) to template types (string, timestamp, id) with notes explaining the original type.

## API Quirks

- `strongest_connection_strength_legacy` (number) exists alongside `strongest_connection_strength` (select enum) — legacy field should be ignored in favor of the enum version.
- `claude mcp list` does not show project-scoped servers from `.mcp.json` — silence ≠ failure; verify by actually calling a tool.
- Trust prompt required on first launch after editing `.mcp.json` — must approve or server silently won't load.

## Open Questions

- What API key scopes are required for full Attio MCP access?
- Which Attio workflows are candidates for codification (e.g. deal reporting, contact enrichment checks)?
- Are there custom objects beyond people/companies/deals/users/workspaces in this workspace?
- What data lives in the `users` and `workspaces` objects — product analytics integration?
