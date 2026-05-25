# Email body normalizer

Strips quoted replies, forwarded-message blocks, and signatures from email bodies so downstream tools see only the active message. Pure Python — no external API, no env vars.

## Tools

- `normalize_email_body` — input: raw email body string; output: cleaned body with quoted history and signatures removed.

## When to install

Install if your gateway handles email content (e.g. Gmail proxy is also installed, or you ingest email via n8n). Skip otherwise — small but adds one tool name to the surface.
