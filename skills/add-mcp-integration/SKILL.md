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

## First-time local dev setup (do once per machine)

The local gateway needs a database to handle auth — without it every `/mcp` request returns 401.

```bash
# 1. Start Postgres (already installed via Homebrew)
brew services start postgresql@16

# 2. Create the dev database (gateway auto-creates its schema on first start)
createdb inform_gateway_dev

# 3. DATABASE_URL is already set in remote-gateway/.env:
#    postgresql://jaronsander@localhost:5432/inform_gateway_dev

# 4. Start the gateway once to initialize the schema
MCP_TRANSPORT=combined python remote-gateway/core/mcp_server.py &
sleep 6

# 5. Register GATEWAY_USER_API_KEY (from ~/.claude/settings.json) in the local DB
psql -d inform_gateway_dev -c "
  INSERT INTO api_keys (key, user_id, created_at)
  VALUES ('sk-7f3a26b57ac1cc73c120f906c7527d91', 'jaron', extract(epoch from now()))
  ON CONFLICT (key) DO NOTHING;
"
# Kill the background gateway — use dev.sh going forward
pkill -f "mcp_server.py"
```

The `.mcp.json` in the repo root connects Claude Code to `http://localhost:8000/mcp` using `${GATEWAY_USER_API_KEY}`. Run `./dev.sh` to start both gateway and admin UI, then reload Claude Code's MCP connection.

---

## Step 5 — Test via .mcp.json (sandbox before touching the gateway)

`.mcp.json` uses almost the same format as `mcp_connections.json`. Use it as a sandbox: Claude Code starts the subprocess directly, and tools immediately appear in the sidebar. No gateway restart, no port conflicts, no curl.

### 5a. Add to .mcp.json

`.mcp.json` lives at the repo root (gitignored for local-only entries). Add the new integration with real credentials inline:

```json
{
  "mcpServers": {
    "<integration>": {
      "command": "npx",
      "args": ["--yes", "github:<owner>/<repo>"],
      "env": {
        "API_KEY": "your-real-key-here"
      }
    }
  }
}
```

### 5b. Verify in Claude Code

Reload the MCP connection (Claude Code → Settings → MCP or restart the session). The integration's tools should appear in the tool list. Call one to confirm auth works.

If the tool list is empty, the subprocess crashed — run the command manually in a terminal with the env var set to see the error:
```bash
API_KEY=your-real-key npx --yes github:<owner>/<repo>
```

### 5c. Promote to gateway

Once it works in `.mcp.json`, translate to `mcp_connections.json`. The diff is mechanical:
- Wrap in `"transport": "stdio"`
- Replace real credential values with `${VAR_NAME}` placeholders
- Add the real values to `remote-gateway/.env`

The gateway will behave identically to what you tested in the sandbox.

> **Admin API note (if you need to verify after gateway restart):** Use `?token=<ADMIN_TOKEN>` query param, NOT `Authorization: Bearer`. Use port 8099 not 8000 (`workspace-mcp` binds 8000 locally).

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
| Want faster feedback than gateway restart | Use `.mcp.json` as sandbox first (Step 5) |
| Env var not picked up | Server reads `remote-gateway/.env`, not repo root `.env` |
| Token merged with previous line | Use Edit tool to insert newline; don't use `echo >>` |
| Integration in right file, wrong variable | Double-check `${VAR_NAME}` in `mcp_connections.json` matches what's in `.env` |
