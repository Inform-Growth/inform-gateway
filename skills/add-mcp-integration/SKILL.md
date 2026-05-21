---
name: add-mcp-integration
description: Use when adding a new proxied MCP integration to this gateway. Covers package discovery, install command validation, mcp_connections.json config, env var setup, local testing, and commit. Encodes all known gotchas.
---

# Adding a Proxied MCP Integration

Follow every step in order. Do not skip the install-command validation — it is the step most likely to fail silently.

---

## Step 1 — Discover the correct install command

Run all three checks in parallel before writing any config.

### 1a. Check npm
```bash
npm show <package-name>
```
- If it returns metadata → use `npx --yes <package-name>` as the command.
- If it returns 404 → the package is NOT on npm. Go to 1b.

### 1b. Check GitHub
Find the GitHub repo (usually linked from the integration's website or README). Look at `package.json`:
- `"name"` field — this is what you'd pass to npm, but the 404 means it wasn't published.
- `"bin"` field — confirms there is a CLI entry point.
- `"scripts"."build"` — confirms the TypeScript needs to be compiled before running.

### 1c. Try GitHub-direct via npx
```bash
BUFFER_ACCESS_TOKEN=dummy npx --yes github:<owner>/<repo> 2>&1 | head -5
```
- If you see an auth/config error (e.g. "access token required") → ✅ it ran successfully. Use `npx --yes github:<owner>/<repo>` as the command.
- If you see a build/compile error → the repo needs a build step first. Consider cloning and building locally instead.
- If you see an npm 404 → GitHub-direct also failed; escalate to the user.

**Never assume the npm package name matches the GitHub repo slug.** Always verify.

---

## Step 2 — Configure mcp_connections.json

File: `remote-gateway/mcp_connections.json`

Add a new entry to `"connections"`. Use the validated command from Step 1.

**stdio template (npm package):**
```json
"<integration>": {
  "transport": "stdio",
  "command": "npx",
  "args": ["--yes", "<package-name>"],
  "env": {
    "API_KEY": "${ENV_VAR_NAME}"
  }
}
```

**stdio template (GitHub-direct, not on npm):**
```json
"<integration>": {
  "transport": "stdio",
  "command": "npx",
  "args": ["--yes", "github:<owner>/<repo>"],
  "env": {
    "API_KEY": "${ENV_VAR_NAME}"
  }
}
```

**http template (remote MCP server):**
```json
"<integration>": {
  "transport": "http",
  "url": "https://mcp.example.com/mcp",
  "auth": {
    "type": "header",
    "headers": { "x-api-key": "${ENV_VAR_NAME}" }
  }
}
```

Optional fields:
- `"tools": { "allow": [...] }` — whitelist specific tools (deny all others)
- `"tools": { "deny": [...] }` — blacklist specific tools
- `"rate_limit": { "rpm": 20, "concurrency": 2 }` — throttle if the upstream has limits

---

## Step 3 — Update env var documentation

File: `remote-gateway/.env.example`

Add a commented section for the new integration. Keep it consistent with the existing style:
```
# <Integration Name> (<what it does>, proxied via gateway)
# Get from: <where to find the key>
# <ENV_VAR_NAME>=your_value_here
```

---

## Step 4 — Set the env var locally

**Critical gotcha: the server reads `remote-gateway/.env`, NOT the repo root `.env`.**

Add the real credential to `remote-gateway/.env` (gitignored). Verify with:
```bash
grep ENV_VAR_NAME remote-gateway/.env
```

If it's missing or ended up on the same line as another variable (no trailing newline), fix with the Edit tool — do not use `echo >>` which can merge lines.

---

## Step 5 — Test locally

### 5a. Start the gateway

```bash
pkill -f "mcp_server.py" 2>/dev/null
MCP_TRANSPORT=combined MCP_SERVER_PORT=8099 python remote-gateway/core/mcp_server.py &
sleep 10
```

**Use port 8099, not 8000.** The `workspace-mcp` subprocess binds to `localhost:8000` and intercepts traffic before the gateway's `0.0.0.0:8000` binding.

### 5b. Check startup logs

Look for:
```
[proxy] '<integration>' connected — N tool(s) registered
```

If you see `failed to connect`, the install command or env var is wrong. Read the error carefully — it will say either "Connection closed" (binary not found) or an auth error (env var missing).

### 5c. Verify via admin API

```bash
curl -s "http://localhost:8099/admin/api/tools?token=inform-admin-2026" \
  | python3 -c "
import sys, json
tools = json.load(sys.stdin)
hits = [t for t in tools if '<integration>' in t['name']]
print(f'<Integration> tools: {len(hits)}')
for t in hits: print(f'  {t[\"name\"]}')
"
```

**Admin API auth gotcha:** Use `?token=<ADMIN_TOKEN>` query param, NOT `Authorization: Bearer`. The Bearer path returns 403.

A count of 0 with no startup error usually means the tool allowlist in `mcp_connections.json` excluded everything — double-check the `"allow"` list.

---

## Step 6 — Commit

Only commit the config files. Never commit `.env`.

```bash
git add remote-gateway/mcp_connections.json remote-gateway/.env.example
git commit -m "feat: add <integration> MCP integration"
```

---

## Gotcha Reference

| Gotcha | Fix |
|---|---|
| `npm show` returns 404 | Package not published. Try `npx github:<owner>/<repo>` instead |
| Tools show 0 after connect | Check `"allow"` list in connections config |
| Admin API returns 403 | Use `?token=` query param, not `Authorization: Bearer` |
| Server not reachable on :8000 | `workspace-mcp` occupies that port locally. Use :8099 |
| Env var not picked up | Server reads `remote-gateway/.env`, not repo root `.env` |
| Token merged with previous line | Use Edit tool to insert newline; don't use `echo >>` |
| Integration in right file, wrong variable | Double-check `${VAR_NAME}` in `mcp_connections.json` matches what's in `.env` |
