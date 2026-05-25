# Apollo.io

Lead enrichment and people/company search via Apollo's REST API. Python-implemented (no MCP proxy — Apollo's OAuth proxy was unreliable).

## Tools

- `apollo__search_people` — search by name, title, company, location, etc.
- `apollo__search_companies` — search by domain, name, industry, headcount
- `apollo__enrich_person` — full profile by email or LinkedIn URL
- `apollo__enrich_organization` — full company profile by domain

## Required environment

| Variable | Where to get it |
|---|---|
| `APOLLO_API_KEY` | app.apollo.io → Settings → Integrations → API Keys |

## Notes

Field schema lives at `remote-gateway/context/fields/apollo.yaml` if you want validated responses (not shipped in the catalog bundle — copy from this dogfood deployment if needed).
