# Decision Ledger

Exposes the Supabase-backed company-strategy decision ledger as MCP tools.

The data lives in agent-inform's Supabase `decisions` table (the strategy data
plane). This integration is a pure access surface — it stores nothing locally.

## Tools
- `list_open_decisions()` — open + in-progress decisions, newest first.
- `upsert_decision(title, kind, detail, priority, source)` — mint, deduped on
  case-insensitive title (no-op returns the existing row).
- `resolve_decision(id, status, resolution)` — close/update a decision.

## Env vars
- `SUPABASE_URL` — the Supabase project URL.
- `SUPABASE_KEY` — service key (reuse agent-inform's).

## Notes
There is intentionally no GitHub/issue reconciliation. Decisions are closed
explicitly (by an operator or an agent), not inferred from external signals.
