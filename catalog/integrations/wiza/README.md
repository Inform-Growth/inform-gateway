# Wiza

Person enrichment (mobile phone + email) via Wiza's Individual Reveal REST API. Python-implemented (no MCP proxy available).

## Tools

- `wiza__enrich_person` — given a LinkedIn URL or email, returns mobile phone, work/personal email, and matched fields. Synchronous; ~5–15 s per call.

## Required environment

| Variable | Where to get it |
|---|---|
| `WIZA_API_KEY` | wiza.co → Settings → API |

## Notes

Each successful reveal consumes a Wiza credit. The tool surfaces credit-exhaustion and rate-limit errors from Wiza's API as readable messages.
