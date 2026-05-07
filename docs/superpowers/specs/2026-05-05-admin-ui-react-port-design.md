# Admin UI — React Port Design

**Date:** 2026-05-05
**Branch:** `template/clean-gateway`
**Status:** Design (pre-implementation)

---

## Summary

Replace the single-file `remote-gateway/core/admin_dashboard.html` (2,231 lines, 8 tabs, vanilla JS + D3) with a React + Vite + TypeScript + Tailwind + shadcn application living in `remote-gateway/admin-ui/`. Production serves the built bundle from Starlette on the same port as the MCP gateway (no operational change). Local dev runs Vite alongside Python via `./dev.sh` for HMR.

The rewrite includes a **redesign**: top tab bar → left sidebar with grouped navigation, app-best-practice patterns (command palette, sticky page headers, toasts, skeletons, empty states), and renamed sections. The admin REST API at `/admin/api/*` is unchanged; only the frontend is rewritten.

## Goals

1. Make the dashboard **familiar** — every interaction matches what users expect from modern admin tools (Linear, Notion, GitHub, Vercel).
2. Make it **extensible** — adding a new page is a file in `src/routes/`; adding a new component is a shadcn primitive copied in via CLI.
3. Preserve the **existing palette and editorial vibe** (cream / moss / ember / serif).
4. Add **zero operational complexity** in production — single port, single Python process, no new runtime dependencies.
5. Enable **fast iteration** — Vite HMR for sub-100ms feedback while developing the UI.

## Non-Goals

- Replacing or modifying the admin REST API (`admin_api.py`).
- Authentication beyond the existing `?token=<ADMIN_TOKEN>` model.
- Dark mode (palette has no dark variants today; can add later).
- Internationalization.
- Real-time updates via SSE/websocket (TanStack Query's refetch-on-focus + manual refresh button is sufficient).
- E2E test framework (Playwright etc.) — manual verification per migration phase.

---

## Information Architecture

The 8 top tabs become a left sidebar with grouped sections:

```
▸ Dashboard          (was: Executive)

ACTIVITY
▸ Tool Calls         (was: Logs)
▸ Tasks
▸ Operators          (was: Ops)

REGISTRY
▸ Tools
▸ Skills
▸ Tool Hints

▸ Settings           (was: Org Profile)
```

### Renames and rationale

| Old | New | Why |
|---|---|---|
| Executive | Dashboard | "Executive" is jargon. Every admin tool calls its overview "Dashboard." |
| Logs | Tool Calls | Every row IS a tool call; "Logs" is generic and ambiguous. |
| Ops | Operators | Matches the "Gateway Operator" persona terminology in `prompts/init.md` and `get_operator_instructions`. More specific than "Users." |
| Org Profile | Settings | Only one org profile exists per gateway; calling it anything other than "Settings" is over-precise. |

### Layout

```
┌─ Sidebar ──────────┐ ┌─ Top bar ────────────────────────────┐
│  GATEWAY           │ │ Page title       ⌘K   ↻ Refresh      │
│                    │ ├──────────────────────────────────────┤
│  ▸ Dashboard       │ │                                      │
│                    │ │  Page content                        │
│  ACTIVITY          │ │  • DataTable                         │
│  ▸ Tool Calls      │ │  • Detail Sheet drawer               │
│  ▸ Tasks           │ │  • Dialog forms                      │
│  ▸ Operators       │ │                                      │
│                    │ │                                      │
│  REGISTRY          │ │                                      │
│  ▸ Tools           │ │                                      │
│  ▸ Skills          │ │                                      │
│  ▸ Tool Hints      │ │                                      │
│                    │ │                                      │
│  ▸ Settings        │ │                                      │
│                    │ │                                      │
│  v1.x · org name   │ │                                      │
└────────────────────┘ └──────────────────────────────────────┘
```

App-best-practice patterns layered on:
- **Command palette** (⌘K) — jump to any page, search users, search tools.
- **Sticky page headers** — h1 + primary action button, persistent on scroll.
- **Toast notifications** (Sonner) — every action gives feedback.
- **Loading skeletons** — replace "Loading…" text with `<Skeleton>` rows.
- **Empty states** — icon + headline + body + CTA when a list is empty.
- **Breadcrumbs** — when drilling into session/task detail views.

---

## Architecture

### Repo layout

```
remote-gateway/
├── admin-ui/                    ← NEW
│   ├── src/
│   │   ├── main.tsx             ← React entry
│   │   ├── App.tsx              ← AppShell + Router
│   │   ├── routes/              ← one file per page
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── ToolCallsPage.tsx
│   │   │   ├── TasksPage.tsx
│   │   │   ├── OperatorsPage.tsx
│   │   │   ├── ToolsPage.tsx
│   │   │   ├── SkillsPage.tsx
│   │   │   ├── ToolHintsPage.tsx
│   │   │   ├── SettingsPage.tsx
│   │   │   └── LoginPage.tsx
│   │   ├── components/
│   │   │   ├── ui/              ← shadcn primitives (copied via CLI)
│   │   │   ├── layout/          ← AppShell, Sidebar, TopBar, PageHeader, EmptyState, CommandPalette
│   │   │   └── charts/          ← recharts wrappers (Sankey, Timeline, Adoption)
│   │   ├── lib/
│   │   │   ├── api.ts           ← typed fetch client (single source of auth)
│   │   │   ├── auth.ts          ← admin token storage
│   │   │   ├── branding.ts      ← Copier-templated brand constants
│   │   │   └── utils.ts         ← cn() helper (shadcn convention)
│   │   ├── hooks/               ← TanStack Query hooks per resource
│   │   │   ├── useStats.ts
│   │   │   ├── useToolCalls.ts
│   │   │   ├── useTasks.ts
│   │   │   ├── useOperators.ts
│   │   │   ├── usePermissions.ts
│   │   │   ├── useTools.ts
│   │   │   ├── useSkills.ts
│   │   │   ├── useToolHints.ts
│   │   │   └── useOrgProfile.ts
│   │   └── styles/
│   │       └── globals.css      ← Tailwind directives + CSS variables
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts       ← cream/moss/ember palette as theme tokens
│   ├── tsconfig.json
│   ├── components.json          ← shadcn CLI config
│   ├── package.json
│   ├── .env.example
│   └── README.md
├── core/
│   ├── admin_api.py             ← +20 lines for SPA static serving
│   ├── admin_dashboard.html     ← DELETED in Phase 8
│   └── ...
└── ...
dev.sh                           ← NEW — runs Python + Vite together
```

### Production serving (single port)

- **Build:** Dockerfile adds a build stage — `cd remote-gateway/admin-ui && npm install && npm run build` → `remote-gateway/admin-ui/dist/`. Node 20 is already in the existing image.
- **Vite `base`:** `vite.config.ts` sets `base: '/admin/'` so emitted asset paths in `index.html` resolve correctly when served behind the `/admin` mount (e.g., `<script src="/admin/assets/main-<hash>.js">`).
- **Serve:** `admin_api.py` mounts `dist/assets/` at `/admin/assets/` and serves `dist/index.html` for any non-API GET under `/admin/`. React Router handles client-side routing from there.
- **Result:** Railway/Render/EC2 see exactly one port. No new processes, no new runtime deps.

### Local dev (two ports, one command)

- **`dev.sh`** (repo root) runs `python remote-gateway/core/mcp_server.py` (`:8000`) and `npm run dev` (`:5173`) in parallel. Ctrl-C kills both.
- **Vite proxy:** `vite.config.ts` forwards `/admin/api/*` and `/mcp` from `:5173` → `:8000` so the React app sees a single origin.
- **Token:** `admin-ui/.env.local` holds `VITE_ADMIN_TOKEN=inform-admin-2026` (gitignored). The API client appends it automatically. `.env.example` is committed.
- **Browse:** `localhost:5173` to develop with HMR; `localhost:8000/admin` to test the production-style bundle.

### Routing

React Router v6, `BrowserRouter` with `basename="/admin"`:

```
/admin                  → redirect to /admin/dashboard
/admin/dashboard
/admin/tool-calls
/admin/tasks
/admin/operators
/admin/tools
/admin/skills
/admin/tool-hints
/admin/settings
/admin/login            → token entry (shown on 403)
```

Deep-linking works: `/admin/tool-calls?tool=attio__search&user=X` lands directly on the filtered view.

### Auth boundary

- **First load:** if URL has `?token=...`, capture into `sessionStorage`, then strip from URL.
- **All requests:** go through `lib/api.ts`, which appends `?token=...` to every URL.
- **403 response:** redirect to `/admin/login` with a token input.
- **Dev:** token comes from `VITE_ADMIN_TOKEN`, login page never appears.
- **`sessionStorage` (not `localStorage`):** token clears when the browser session ends — more secure.

---

## Visual Design

### Tailwind theme — palette as design tokens

`tailwind.config.ts` extends Tailwind so the existing cream/green/orange palette becomes first-class. Both raw color names AND shadcn semantic tokens map to the palette, so `bg-cream`, `bg-background`, and shadcn defaults all resolve to the same colors.

```ts
theme: {
  extend: {
    colors: {
      cream:      { DEFAULT: '#f2ead8', light: '#faf6ec', dark: '#e6dcc4' },
      moss:       { DEFAULT: '#2d5a27', mid: '#4a7a3e', light: '#6ba35a' },
      ember:      { DEFAULT: '#c8501a', light: '#e07040' },
      ink:        { DEFAULT: '#1e2a18', muted: '#6b6b50' },
      // shadcn semantic tokens
      background: '#f2ead8',
      foreground: '#1e2a18',
      primary:    { DEFAULT: '#2d5a27', foreground: '#faf6ec' },
      accent:     { DEFAULT: '#c8501a', foreground: '#ffffff' },
      border:     '#c4b492',
      muted:      { DEFAULT: '#e6dcc4', foreground: '#6b6b50' },
    },
    fontFamily: {
      serif: ['Georgia', '"Times New Roman"', 'serif'],
      mono:  ['"Courier New"', 'monospace'],
    },
  },
}
```

### shadcn components in scope

Installed via `npx shadcn@latest add`:

```
button, input, label, textarea, select, checkbox, switch,
card, table, tabs, dialog, sheet, drawer, popover, dropdown-menu,
form, sonner, skeleton, badge, separator, alert,
command, tooltip, scroll-area, breadcrumb,
data-table (custom, built on TanStack Table per shadcn docs)
```

These get **copied into `src/components/ui/`** — they are project code, not an opaque dependency.

### Defaults

- Use shadcn's `data-table` everywhere a list is shown — gets sorting, filtering, and pagination for free.
- Use **explicit Save buttons** on forms (no auto-save on blur).
- Use **Sonner** for toasts (current shadcn default).
- Use **recharts** for all charts including the Sankey — drop D3 entirely.

---

## Components

### Shared layout

```
src/components/layout/
├── AppShell.tsx       sidebar + topbar + content slot
├── Sidebar.tsx        grouped nav, footer with version + org name
├── TopBar.tsx         page title, ⌘K trigger, refresh, last-updated stamp
├── PageHeader.tsx     sticky h1 + primary action
├── EmptyState.tsx     icon + headline + body + CTA
└── CommandPalette.tsx ⌘K — jump to page, search users, search tools
```

### Per-page component plan

| Page | Components |
|---|---|
| **Dashboard** | 4× `<Card>` for KPIs · `<SankeyChart>` (recharts) · `<UserAdoptionChart>` (recharts BarChart) · `<ActivityTimeline>` (recharts LineChart) · `<DataTable>` for tool health |
| **Tool Calls** | `<DataTable>` with column filters (tool, user, status), pagination · row click → `<Sheet>` with full request/response |
| **Tasks** | `<DataTable>` of tasks · row click → `<Sheet>` with nested tool-calls table |
| **Operators** | `<DataTable>` of users · row select shows right pane with `<PermissionsList>` (search + per-tool toggles) · `<Dialog>` for "+ Add Operator" → reveals new API key in `<Alert>` with copy button |
| **Tools** | `<DataTable>` with global on/off `<Switch>` per row · row click → `<Sheet>` with description + per-user override summary |
| **Skills** | `<DataTable>` · "+ New Skill" `<Dialog>` with `<Form>` (name, description, prompt template) · row actions: Edit, Delete (confirm `<Dialog>`) |
| **Tool Hints** | `<DataTable>` + same `<Dialog>` form pattern as Skills |
| **Settings** | `<Card>` per section (Org Identity, Tone, ICP, Vocab Rules) · `<Form>` with explicit Save button |

---

## Data Layer

### TanStack Query

One hook per resource in `src/hooks/`. All queries call `api.get/post/put/delete` from `lib/api.ts`. Mutations invalidate relevant query keys.

Example shape:

```ts
// hooks/useToolCalls.ts
export function useToolCalls(filters: ToolCallFilters) {
  return useQuery({
    queryKey: ['toolCalls', filters],
    queryFn: () => api.get('/admin/api/logs', filters),
    staleTime: 10_000,
  });
}

export function useDeleteOperator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => api.delete(`/admin/api/users/${userId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['operators'] }),
  });
}
```

Defaults: `staleTime: 10s`, `refetchOnWindowFocus: true`, retry once on 5xx, never retry on 4xx.

### API client — `src/lib/api.ts`

Single file, single responsibility:

```ts
export const api = {
  get<T>(path: string, params?: Record<string, unknown>): Promise<T>,
  post<T>(path: string, body: unknown): Promise<T>,
  put<T>(path: string, body: unknown): Promise<T>,
  delete<T>(path: string): Promise<T>,
};
```

Internally:
- Appends `?token=...` from `auth.ts`.
- Handles `403` → redirect to `/admin/login`.
- Throws typed `ApiError` for non-2xx with `{status, message, body}`.
- Parses JSON, including for error responses.

Every hook calls only `api.*`. Nothing else fetches.

### Forms — react-hook-form + zod

shadcn's recommended stack. One zod schema per form (Settings, New Skill, Edit Skill, New Tool Hint, New Operator). Validation errors render via `<FormMessage>`.

### Toasts and loading states

- `<Toaster />` (Sonner) mounted once at app root.
- `toast.success("Profile saved")`, `toast.error("Failed to revoke key")` from anywhere — including inside mutation `onSuccess` / `onError`.
- `<Skeleton>` rows in tables while `useQuery` is loading.
- 403 / network errors → toast + Retry button. Never silent failure.

---

## Backend Changes

The admin REST API at `/admin/api/*` is unchanged. Only `admin_api.py`'s static serving changes.

### `admin_api.py` (additive)

```python
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse, HTMLResponse

DIST = Path(__file__).parent.parent / "admin-ui" / "dist"

async def _serve_spa(request: Request) -> Response:
    if not _is_authorized(request):
        return HTMLResponse("403 Forbidden — invalid token", status_code=403)
    index = DIST / "index.html"
    if not index.exists():
        return HTMLResponse(
            "<h1>admin-ui not built</h1><p>Run <code>cd remote-gateway/admin-ui && npm run build</code> "
            "or use <code>./dev.sh</code> for development.</p>",
            status_code=503,
        )
    return FileResponse(index)

# Route changes inside create_admin_app() (paths are relative to the /admin mount):
routes = [
    Route("/legacy", dashboard),               # OLD HTML moves here through Phase 7
    # ... existing /api/* routes unchanged ...
    Mount(
        "/assets",
        app=StaticFiles(directory=DIST / "assets"),
        name="admin-assets",
    ),
    Route("/{path:path}", _serve_spa),         # SPA fallback — MUST come last
]
# Order matters: Starlette matches routes top-to-bottom, so /api/* and /assets/*
# are tried before the catch-all. The catch-all serves index.html for "/", "/dashboard",
# "/operators", etc., letting React Router take over on the client.
```

### Dockerfile (additive)

```dockerfile
# Existing stage already has Node 20.
WORKDIR /app/remote-gateway/admin-ui
COPY remote-gateway/admin-ui/package*.json ./
RUN npm install
COPY remote-gateway/admin-ui/ ./
RUN npm run build
WORKDIR /app
# Result: /app/remote-gateway/admin-ui/dist/ exists at runtime.
```

`package*.json` is copied first so `npm install` only re-runs when deps change.

---

## Migration Plan

The dashboard ships in production today. Each phase is an independently shippable PR/commit. Old HTML stays at `/admin/legacy` as a safety net until Phase 8.

### Phase 0 — Scaffolding (no visible UI changes)

- Add `remote-gateway/admin-ui/` Vite project.
- Wire Tailwind, shadcn CLI, base UI primitives.
- Wire `AppShell`, `Sidebar`, `TopBar`, `CommandPalette`.
- Wire React Router with all 8 routes pointing at "Coming soon" placeholder pages.
- Wire `api.ts`, `auth.ts`, TanStack Query provider, Sonner.
- Update `Dockerfile` (build stage).
- Update `admin_api.py`: serve `dist/` at `/admin/`, keep old HTML at `/admin/legacy`.
- Add `dev.sh`.
- **Result:** `/admin` shows the new shell with empty pages; `/admin/legacy` shows the old dashboard.

### Phase 1 — Settings (was Org Profile)

Smallest page, validates Form + Toast + `api.put` + `useQuery` patterns. Lowest risk.

### Phase 2 — Operators (was Ops)

Validates DataTable + Dialog + side-pane pattern. Validates the new-API-key reveal flow.

### Phase 3 — Tools

DataTable + per-row Switch (mutation + optimistic update). Validates Sheet for detail view.

### Phase 4 — Skills + Tool Hints

Done together — they share the entire pattern (DataTable + Dialog + Form CRUD).

### Phase 5 — Tool Calls (was Logs)

DataTable with column filters + pagination. Sheet for full request/response detail.

### Phase 6 — Tasks

DataTable + Sheet with nested table.

### Phase 7 — Dashboard (was Executive)

Recharts: timeline (LineChart), adoption (BarChart), sankey (Sankey). KPI cards. Tool Health DataTable. Saved for last because charts have the most fiddly polish.

### Phase 8 — Cleanup

- Delete `admin_dashboard.html`.
- Remove `/admin/legacy` route.
- Remove D3 references (none should remain).

---

## Documentation Updates

| File | Change |
|---|---|
| **Root `CLAUDE.md`** | Add admin-ui section: directory, build/serve story, `./dev.sh` for local. Update "Run the Remote Gateway." |
| **`remote-gateway/CLAUDE.md`** | Add admin-ui paragraph, document dev workflow. |
| **`README.md`** | Add quickstart for dashboard dev. |
| **`Dockerfile`** | Build stage above. |
| **`copier.yml`** | Add `admin_ui_title` question (defaults to `[[ project_name ]] Admin`). |
| **`.gitignore`** | Add `remote-gateway/admin-ui/node_modules/`, `remote-gateway/admin-ui/dist/`, `remote-gateway/admin-ui/.env.local`. |
| **`package.json`** (root) | Add `dev` script that calls `./dev.sh`; add `build:ui` for convenience. |
| **`.env.example`** | Verify `ADMIN_TOKEN` wording mentions the dashboard. |
| **NEW: `remote-gateway/admin-ui/README.md`** | Short — Vite + React + Tailwind + shadcn quickstart. |
| **NEW: `remote-gateway/admin-ui/.env.example`** | Documents `VITE_ADMIN_TOKEN`. |

---

## Templating (Copier)

Goal: aggressive templating where it adds value, untouched code everywhere else. Copier `update` will conflict-merge cleanly because file paths are stable.

| File | Templated content |
|---|---|
| `admin-ui/package.json` | `name: "[[ project_slug ]]-admin-ui"` |
| `admin-ui/index.html` | `<title>[[ project_name ]] Admin</title>` |
| `admin-ui/src/lib/branding.ts` | Single source of brand constants — exports `BRAND_NAME = "[[ project_name ]]"`, `BRAND_TAGLINE = "[[ admin_ui_title ]]"`. All UI imports from here. |

`copier.yml` adds:

```yaml
admin_ui_title:
  type: str
  help: "Title shown in the admin dashboard sidebar/topbar"
  default: "[[ project_name ]] Admin"
```

Everything else in `admin-ui/` is plain code consumers inherit verbatim.

---

## Testing Strategy

- **Python tests:** unchanged. The API layer is untouched; existing pytest suite still covers it.
- **Frontend unit tests (Vitest):** light — one test per shared primitive only.
  - `api.ts` — appends token, handles 403, throws typed errors.
  - `auth.ts` — captures token from URL, strips it, persists to `sessionStorage`.
  - `AppShell` — renders with sidebar collapsed/expanded.
  - `DataTable` — basic sort + filter + pagination.
  - ~10 tests total.
- **No E2E framework** initially. Add Playwright later if needed.
- **Manual verification per phase:** every PR includes a short checklist (e.g., Phase 2: "create operator, copy key, revoke operator, toggle a permission, refresh page → state persists").
- **CI:** extend existing GitHub Actions — add `npm install`, `npm run build`, and `npm run lint` (eslint + `tsc --noEmit`) on PRs. No new workflow file.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Phased migration introduces dual-runtime complexity | `/admin/legacy` route is a single 5-line fallthrough; no shared state between old HTML and new React app. Removed in Phase 8. |
| shadcn CLI version drift between consumers | `components.json` pins generator config; primitives are copied (not npm-pinned), so consumers own their versions after the initial render. |
| Recharts Sankey less polished than the existing D3 sankey | If recharts Sankey looks worse, fall back to keeping D3 *only for that one chart* — wrapped in `<SankeyChart>`. Local decision in Phase 7, not blocking. |
| Token in `sessionStorage` exposed to XSS | Same exposure surface as today (the existing HTML reads `?token=` from URL too). XSS in admin UI would already be game-over given admin privileges. |
| Build failures in Docker due to missing Node deps | Existing image already installs Node 20 and runs `npm install`. New build stage uses the same toolchain — no new system deps. |
| Copier `update` conflicts on consumer edits to `admin-ui/` | Most files untemplated → Copier copies them only if absent or unchanged. Templated files are limited to 3 small ones with stable structure. |

---

## Success Criteria

1. **Feature parity:** every action available in the current dashboard works in the new one (verified per phase).
2. **Single port in production:** Railway/Render deployment requires no port changes.
3. **Dev loop:** `./dev.sh` starts both servers; saving a `.tsx` file updates the browser in <500ms.
4. **Templating:** `copier copy` produces a working dashboard with consumer's project name in the sidebar/title without manual edits.
5. **CI green:** `pytest`, `ruff check`, `npm run build`, `npm run lint` all pass on PRs.
6. **HTML deleted:** Phase 8 lands and `admin_dashboard.html` is gone from the repo.

---

## Out of Scope (for this rewrite)

- Dark mode.
- i18n.
- E2E tests (Playwright).
- SSO / per-user dashboard authentication.
- Real-time updates (SSE, websockets).
- Replacing or modifying `admin_api.py` REST endpoints.
- Replacing the existing telemetry SQLite schema.
