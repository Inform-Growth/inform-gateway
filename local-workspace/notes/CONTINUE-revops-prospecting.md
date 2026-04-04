# CONTINUATION PROMPT — RevOps AI Infra Prospecting
**Left off:** 2026-04-03 | Session: `2026-04-03-2142-revops-ai-infra-prospecting`

---

## What was done

1. Searched for companies interested in AI infrastructure as a service for RevOps
2. Identified 5 test prospects using active job postings as buying-intent signal
3. Saved prospect list to `notes/revops-ai-infra-prospects.md` locally and committed to GitHub remote-gateway notes repo (commit: `cd63e845999d644fdf9cc434fae190de4e0d5dcc`)

## What to do next

### Step 1 — Verify Apollo is working
Run a quick health check on the gateway and confirm Apollo tools are available (they should appear as `apollo__*` tools). If they're missing, the gateway still needs a restart.

### Step 2 — Enrich all 5 companies and find decision makers
Use Apollo's people search / enrich tools to find decision makers at each company. Target titles: **CRO, VP Sales, VP RevOps, Head of Revenue Operations, Director of GTM Operations**.

Companies to enrich:
| Company | Domain | Priority |
|---|---|---|
| Kubelt | kubelt.com | 1 — highest fit |
| Ivo | ivo.ai | 2 |
| Hippocratic AI | hippocraticai.com | 3 |
| Quorum | quorum.us | 4 |
| JUPUS | jupus.de | 5 |

### Step 3 — Add contacts to Apollo
For each decision maker found, add them to an Apollo sequence or list for outreach. The angle is: **AI infrastructure as a service for RevOps** — they're either building this from scratch post-funding or actively hiring for it.

### Step 4 — Update the notes file
Append the enriched contacts to `notes/revops-ai-infra-prospects.md` and commit back to the remote-gateway notes repo using `write_note`.

---

## Context on the prospects (why they're warm)

All 5 were identified because they are **actively hiring for RevOps + AI roles** — the strongest buying signal for AI infra as a service:

- **Kubelt** — literally titled "RevOps Lead, AI Infrastructure" — greenfield build
- **Ivo** — $55M Series B Jan 2026, scaling GTM from scratch, 90 employees
- **Hippocratic AI** — 200 employees, +132% YoY, $76M ARR, building RevOps infra
- **Quorum** — hiring "AI GTM Systems Manager", architecting AI into revenue stack
- **JUPUS** — $7.3M seed, first RevOps hire, building from zero

## Blocker that was hit last session

Apollo MCP tools were not appearing from the gateway even though Apollo is configured in `remote-gateway/mcp_connections.json`. Root cause: the gateway process needed a restart to pick up the `mcp_proxy.py` double-wrapping fix (see `sessions/2026-04-03-1836-apollo-remote-gateway-testing.md` for full context). **The fix is already in the code** — a restart is all that was needed.
