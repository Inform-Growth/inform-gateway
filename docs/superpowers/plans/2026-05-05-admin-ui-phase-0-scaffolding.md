# Admin UI — Phase 0: Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an empty React + Vite + TypeScript + Tailwind + shadcn admin UI shell at `remote-gateway/admin-ui/`, served by Starlette in production and runnable locally via `./dev.sh`. No real pages — every route shows a "Coming soon" placeholder. Subsequent plans (Phases 1–8) populate the pages.

**Architecture:** Vite project lives under `remote-gateway/admin-ui/`. Production builds emit `dist/`, which Starlette mounts at `/admin/assets` and serves via SPA-fallback `index.html`. Dev runs Vite on `:5173` proxying `/admin/api/*` to Python on `:8000`. The legacy HTML dashboard moves to `/admin/legacy` and stays there until Phase 8.

**Tech Stack:** Vite 5, React 18, TypeScript 5, Tailwind 3, shadcn/ui (CLI), TanStack Query 5, React Router 6, react-hook-form, zod, Sonner, recharts, Vitest.

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`

---

## File Structure

### New files
```
remote-gateway/admin-ui/
├── package.json
├── package-lock.json
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── components.json                        ← shadcn CLI config
├── index.html
├── .env.example
├── .gitignore
├── README.md
├── public/
│   └── favicon.svg                        ← copied from existing /admin if present
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── routes/
    │   ├── DashboardPage.tsx              ← placeholder
    │   ├── ToolCallsPage.tsx              ← placeholder
    │   ├── TasksPage.tsx                  ← placeholder
    │   ├── OperatorsPage.tsx              ← placeholder
    │   ├── ToolsPage.tsx                  ← placeholder
    │   ├── SkillsPage.tsx                 ← placeholder
    │   ├── ToolHintsPage.tsx              ← placeholder
    │   ├── SettingsPage.tsx               ← placeholder
    │   └── LoginPage.tsx
    ├── components/
    │   ├── ui/                            ← shadcn primitives, copied via CLI
    │   └── layout/
    │       ├── AppShell.tsx
    │       ├── Sidebar.tsx
    │       ├── TopBar.tsx
    │       ├── PageHeader.tsx
    │       ├── EmptyState.tsx
    │       └── CommandPalette.tsx
    ├── lib/
    │   ├── api.ts                         ← typed fetch client
    │   ├── auth.ts                        ← admin token storage
    │   ├── branding.ts                    ← Copier-templated brand constants
    │   ├── queryClient.ts                 ← TanStack Query setup
    │   └── utils.ts                       ← cn() helper
    └── styles/
        └── globals.css

dev.sh                                     ← repo root, runs Python + Vite
```

### Modified files
- `Dockerfile` — add admin-ui build stage
- `remote-gateway/core/admin_api.py` — SPA static serving + `/legacy` route
- `.gitignore` — admin-ui artifacts
- `package.json` (root) — `dev` and `build:ui` scripts
- `copier.yml` — add `admin_ui_title` question
- `CLAUDE.md` — admin-ui section
- `remote-gateway/CLAUDE.md` — admin-ui paragraph
- `README.md` — quickstart section
- `.github/workflows/qa_agent_review.yml` — add UI build/lint checks

---

## Task 1: Create the Vite + React + TypeScript project

**Files:**
- Create: `remote-gateway/admin-ui/package.json`, `tsconfig.json`, `tsconfig.node.json`, `vite.config.ts`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/styles/globals.css`

- [ ] **Step 1: Run the Vite scaffolding command**

```bash
cd remote-gateway
npm create vite@latest admin-ui -- --template react-ts
cd admin-ui
npm install
```

This creates the standard Vite React-TS template. We'll modify the generated files in subsequent steps.

- [ ] **Step 2: Verify the dev server boots**

```bash
cd remote-gateway/admin-ui
npm run dev
```

Expected: Vite starts on `:5173`, browser shows the default Vite + React landing page. Stop with Ctrl-C.

- [ ] **Step 3: Replace `vite.config.ts` with the production config**

```ts
// remote-gateway/admin-ui/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/admin/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/mcp':       { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
});
```

The `base: '/admin/'` is critical — it tells Vite to emit asset references like `/admin/assets/main-<hash>.js` so they resolve when served behind Starlette's `/admin` mount.

- [ ] **Step 4: Update `tsconfig.json` to add the `@/*` path alias**

Open `remote-gateway/admin-ui/tsconfig.json`. Add to `compilerOptions`:

```json
"baseUrl": ".",
"paths": { "@/*": ["./src/*"] }
```

- [ ] **Step 5: Commit the scaffolding**

```bash
git add remote-gateway/admin-ui/
git commit -m "feat(admin-ui): scaffold Vite + React + TypeScript project"
```

---

## Task 2: Install and configure Tailwind CSS

**Files:**
- Create: `remote-gateway/admin-ui/tailwind.config.ts`, `postcss.config.js`
- Modify: `remote-gateway/admin-ui/src/styles/globals.css`, `remote-gateway/admin-ui/src/main.tsx`

- [ ] **Step 1: Install Tailwind**

```bash
cd remote-gateway/admin-ui
npm install -D tailwindcss@^3 postcss autoprefixer
npx tailwindcss init -p
```

This creates `tailwind.config.js` and `postcss.config.js`. Rename the former to `tailwind.config.ts`.

- [ ] **Step 2: Replace `tailwind.config.ts` with the gateway palette**

```ts
// remote-gateway/admin-ui/tailwind.config.ts
import type { Config } from 'tailwindcss';

export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        cream:      { DEFAULT: '#f2ead8', light: '#faf6ec', dark: '#e6dcc4' },
        moss:       { DEFAULT: '#2d5a27', mid: '#4a7a3e', light: '#6ba35a' },
        ember:      { DEFAULT: '#c8501a', light: '#e07040' },
        ink:        { DEFAULT: '#1e2a18', muted: '#6b6b50' },
        // shadcn semantic tokens mapped to gateway palette
        background: '#f2ead8',
        foreground: '#1e2a18',
        primary:   { DEFAULT: '#2d5a27', foreground: '#faf6ec' },
        secondary: { DEFAULT: '#e6dcc4', foreground: '#1e2a18' },
        accent:    { DEFAULT: '#c8501a', foreground: '#ffffff' },
        destructive: { DEFAULT: '#b91c1c', foreground: '#ffffff' },
        border: '#c4b492',
        input:  '#c4b492',
        ring:   '#2d5a27',
        muted:  { DEFAULT: '#e6dcc4', foreground: '#6b6b50' },
        card:   { DEFAULT: '#faf6ec', foreground: '#1e2a18' },
        popover:{ DEFAULT: '#faf6ec', foreground: '#1e2a18' },
      },
      fontFamily: {
        serif: ['Georgia', '"Times New Roman"', 'serif'],
        mono:  ['"Courier New"', 'monospace'],
      },
      borderRadius: {
        lg: '0.5rem',
        md: '0.375rem',
        sm: '0.25rem',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
} satisfies Config;
```

- [ ] **Step 3: Install `tailwindcss-animate`** (required by shadcn)

```bash
npm install -D tailwindcss-animate
```

- [ ] **Step 4: Replace `src/styles/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  body { @apply bg-background text-foreground font-serif; }
}
```

- [ ] **Step 5: Wire `globals.css` into `main.tsx`**

```tsx
// remote-gateway/admin-ui/src/main.tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from '@/App';
import '@/styles/globals.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
);
```

Delete the auto-generated `src/index.css` and `src/App.css` if Vite created them.

- [ ] **Step 6: Verify Tailwind works**

Replace `App.tsx` body with `<div className="bg-cream text-moss font-serif p-8">tailwind works</div>`, run `npm run dev`, confirm the cream background and moss-green text. Then revert `App.tsx`.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/admin-ui/
git commit -m "feat(admin-ui): wire Tailwind with gateway palette"
```

---

## Task 3: Initialize shadcn/ui CLI and install primitives

**Files:**
- Create: `remote-gateway/admin-ui/components.json`, `remote-gateway/admin-ui/src/lib/utils.ts`
- Generated: `remote-gateway/admin-ui/src/components/ui/*.tsx` (multiple files)

- [ ] **Step 1: Initialize shadcn**

```bash
cd remote-gateway/admin-ui
npx shadcn@latest init
```

Answer prompts:
- Style: `Default`
- Base color: `Slate` (will be overridden by our Tailwind config)
- CSS variables: `No` (we map colors via Tailwind config, not CSS vars)
- `tailwind.config.ts`: confirm
- `globals.css`: `src/styles/globals.css`
- Path alias for components: `@/components`
- Path alias for utils: `@/lib/utils`
- React Server Components: `No`

This creates `components.json` and `src/lib/utils.ts`.

- [ ] **Step 2: Install all needed primitives in one batch**

```bash
npx shadcn@latest add button input label textarea select checkbox switch \
  card table tabs dialog sheet drawer popover dropdown-menu \
  form sonner skeleton badge separator alert \
  command tooltip scroll-area breadcrumb
```

When prompted to overwrite `utils.ts`, accept. Each component gets copied into `src/components/ui/`.

- [ ] **Step 3: Verify primitives compile**

```bash
npx tsc --noEmit
```

Expected: no type errors. If any shadcn primitive imports a missing dependency (e.g., `@radix-ui/react-...`), shadcn's installer should have added it; if not, install manually.

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/admin-ui/
git commit -m "feat(admin-ui): install shadcn primitives"
```

---

## Task 4: Install runtime dependencies

**Files:**
- Modify: `remote-gateway/admin-ui/package.json`

- [ ] **Step 1: Install runtime deps**

```bash
cd remote-gateway/admin-ui
npm install \
  react-router-dom@^6 \
  @tanstack/react-query@^5 \
  @tanstack/react-table@^8 \
  react-hook-form@^7 \
  @hookform/resolvers@^3 \
  zod@^3 \
  recharts@^2 \
  date-fns@^3 \
  lucide-react@latest
```

- [ ] **Step 2: Install dev deps**

```bash
npm install -D \
  vitest@^1 \
  @testing-library/react@^14 \
  @testing-library/jest-dom@^6 \
  jsdom@^24 \
  eslint@^8 \
  eslint-plugin-react@^7 \
  eslint-plugin-react-hooks@^4 \
  @typescript-eslint/parser@^7 \
  @typescript-eslint/eslint-plugin@^7
```

- [ ] **Step 3: Verify install**

```bash
npm run build
```

Expected: build completes without errors (output: `dist/index.html` + `dist/assets/`).

- [ ] **Step 4: Commit**

```bash
git add remote-gateway/admin-ui/package.json remote-gateway/admin-ui/package-lock.json
git commit -m "feat(admin-ui): add runtime and dev dependencies"
```

---

## Task 5: Create the API client and auth helpers

**Files:**
- Create: `remote-gateway/admin-ui/src/lib/auth.ts`, `remote-gateway/admin-ui/src/lib/api.ts`
- Create: `remote-gateway/admin-ui/src/lib/api.test.ts`

- [ ] **Step 1: Write the failing tests for `api.ts` and `auth.ts`**

```ts
// remote-gateway/admin-ui/src/lib/api.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ApiError, api } from './api';
import { getToken, setToken, captureTokenFromUrl } from './auth';

describe('auth', () => {
  beforeEach(() => sessionStorage.clear());

  it('captures and strips token from URL', () => {
    history.replaceState(null, '', '/admin/dashboard?token=abc&foo=bar');
    captureTokenFromUrl();
    expect(getToken()).toBe('abc');
    expect(window.location.search).toBe('?foo=bar');
  });

  it('persists set token in sessionStorage', () => {
    setToken('xyz');
    expect(sessionStorage.getItem('admin_token')).toBe('xyz');
    expect(getToken()).toBe('xyz');
  });
});

describe('api', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('appends token query param', async () => {
    (fetch as any).mockResolvedValue({ ok: true, json: async () => ({ ok: 1 }) });
    await api.get('/admin/api/stats');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/admin\/api\/stats\?token=tkn$/),
      expect.any(Object),
    );
  });

  it('throws ApiError on non-2xx', async () => {
    (fetch as any).mockResolvedValue({
      ok: false, status: 500,
      json: async () => ({ error: 'boom' }),
    });
    await expect(api.get('/admin/api/stats')).rejects.toBeInstanceOf(ApiError);
  });
});
```

- [ ] **Step 2: Add Vitest config**

Append to `remote-gateway/admin-ui/vite.config.ts` (inside `defineConfig`):

```ts
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: ['./src/setupTests.ts'],
},
```

Create `remote-gateway/admin-ui/src/setupTests.ts`:

```ts
import '@testing-library/jest-dom/vitest';
```

Add to `package.json` scripts:

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 3: Run the tests — expect failures**

```bash
npm test
```

Expected: tests fail because `api.ts` and `auth.ts` don't exist yet.

- [ ] **Step 4: Implement `auth.ts`**

```ts
// remote-gateway/admin-ui/src/lib/auth.ts
const KEY = 'admin_token';

export function getToken(): string | null {
  return sessionStorage.getItem(KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(KEY);
}

/** Read ?token=... from URL, persist to sessionStorage, strip from URL. */
export function captureTokenFromUrl(): void {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('token');
  if (!token) return;
  setToken(token);
  params.delete('token');
  const qs = params.toString();
  const newUrl = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash;
  window.history.replaceState(null, '', newUrl);
}
```

- [ ] **Step 5: Implement `api.ts`**

```ts
// remote-gateway/admin-ui/src/lib/api.ts
import { getToken } from './auth';

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, params?: Params): string {
  const url = new URL(path, window.location.origin);
  const token = getToken();
  if (token) url.searchParams.set('token', token);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
}

async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  const res = await fetch(buildUrl(path, params), {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let parsed: unknown = null;
  try { parsed = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    if (res.status === 403 && !window.location.pathname.endsWith('/login')) {
      window.location.href = '/admin/login';
    }
    const msg = (parsed as any)?.error ?? `${method} ${path} → ${res.status}`;
    throw new ApiError(res.status, msg, parsed);
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>('GET', path, undefined, params),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put:  <T>(path: string, body?: unknown) => request<T>('PUT',  path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
};
```

- [ ] **Step 6: Run tests — expect pass**

```bash
npm test
```

Expected: all tests in `api.test.ts` pass.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/admin-ui/
git commit -m "feat(admin-ui): add typed api client + auth helpers"
```

---

## Task 6: Create the TanStack Query client and provider

**Files:**
- Create: `remote-gateway/admin-ui/src/lib/queryClient.ts`

- [ ] **Step 1: Create the query client**

```ts
// remote-gateway/admin-ui/src/lib/queryClient.ts
import { QueryClient } from '@tanstack/react-query';
import { ApiError } from './api';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
        return failureCount < 1;
      },
    },
    mutations: { retry: false },
  },
});
```

- [ ] **Step 2: Commit**

```bash
git add remote-gateway/admin-ui/src/lib/queryClient.ts
git commit -m "feat(admin-ui): add TanStack Query client with retry policy"
```

---

## Task 7: Create branding constants (Copier-templated)

**Files:**
- Create: `remote-gateway/admin-ui/src/lib/branding.ts`
- Modify: `remote-gateway/admin-ui/index.html`
- Modify: `copier.yml`

- [ ] **Step 1: Add Copier question**

In `copier.yml`, append:

```yaml
admin_ui_title:
  type: str
  help: "Title shown in the admin dashboard sidebar/topbar"
  default: "[[ project_name ]] Admin"
```

- [ ] **Step 2: Create branding.ts (uses Copier delimiters with template-branch fallbacks)**

```ts
// remote-gateway/admin-ui/src/lib/branding.ts
// The literal strings on the right are Jinja templates that Copier renders at
// `copier copy` time. On the template branch itself (no Copier render), the
// strings remain raw (e.g. "[[ project_name ]]") — the fallback below detects
// that and substitutes generic defaults so local template-branch dev shows
// readable text instead of the literal placeholder syntax.
const TPL_NAME  = "[[ project_name ]]";
const TPL_TITLE = "[[ admin_ui_title ]]";

const looksUnrendered = (s: string) => s.startsWith("[[");

export const BRAND_NAME    = looksUnrendered(TPL_NAME)  ? "Gateway"       : TPL_NAME;
export const BRAND_TAGLINE = looksUnrendered(TPL_TITLE) ? "Gateway Admin" : TPL_TITLE;
```

Note: `[[ ]]` are Copier's Jinja delimiters per `CLAUDE.md`.

- [ ] **Step 3: Template `index.html` title**

```html
<!-- remote-gateway/admin-ui/index.html — update <title> -->
<title>[[ admin_ui_title ]]</title>
```

- [ ] **Step 4: Update package.json name**

```json
"name": "[[ project_slug ]]-admin-ui",
```

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/admin-ui/ copier.yml
git commit -m "feat(admin-ui): add Copier-templated branding constants"
```

---

## Task 8: Build the shared layout (AppShell, Sidebar, TopBar)

**Files:**
- Create: `src/components/layout/AppShell.tsx`, `Sidebar.tsx`, `TopBar.tsx`, `PageHeader.tsx`, `EmptyState.tsx`

- [ ] **Step 1: Sidebar with grouped nav**

```tsx
// remote-gateway/admin-ui/src/components/layout/Sidebar.tsx
import { NavLink } from 'react-router-dom';
import { BRAND_NAME } from '@/lib/branding';
import {
  LayoutDashboard, Activity, ListTodo, Users, Wrench,
  Sparkles, MessageSquareWarning, Settings,
} from 'lucide-react';

type NavItem = { to: string; label: string; icon: React.ComponentType<{ className?: string }> };
type NavGroup = { label?: string; items: NavItem[] };

const groups: NavGroup[] = [
  { items: [{ to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard }] },
  {
    label: 'Activity',
    items: [
      { to: '/tool-calls', label: 'Tool Calls', icon: Activity },
      { to: '/tasks',      label: 'Tasks',      icon: ListTodo },
      { to: '/operators',  label: 'Operators',  icon: Users },
    ],
  },
  {
    label: 'Registry',
    items: [
      { to: '/tools',      label: 'Tools',      icon: Wrench },
      { to: '/skills',     label: 'Skills',     icon: Sparkles },
      { to: '/tool-hints', label: 'Tool Hints', icon: MessageSquareWarning },
    ],
  },
  { items: [{ to: '/settings', label: 'Settings', icon: Settings }] },
];

export function Sidebar() {
  return (
    <aside className="w-60 border-r border-border bg-cream-light flex flex-col">
      <div className="h-14 px-4 flex items-center border-b border-border">
        <span className="font-serif font-bold tracking-widest uppercase text-sm">
          {BRAND_NAME}
        </span>
      </div>
      <nav className="flex-1 overflow-y-auto py-4">
        {groups.map((g, i) => (
          <div key={i} className="mb-4">
            {g.label && (
              <div className="px-4 mb-1 text-xs font-bold uppercase tracking-wider text-ink-muted">
                {g.label}
              </div>
            )}
            {g.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-4 py-2 text-sm hover:bg-cream-dark ${
                    isActive ? 'bg-cream-dark border-l-2 border-ember font-bold' : ''
                  }`
                }
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}
```

- [ ] **Step 2: TopBar with refresh button placeholder**

```tsx
// remote-gateway/admin-ui/src/components/layout/TopBar.tsx
import { Button } from '@/components/ui/button';
import { RefreshCw } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';

export function TopBar({ title }: { title: string }) {
  const qc = useQueryClient();
  return (
    <header className="h-14 px-6 border-b border-border bg-moss text-cream-light flex items-center justify-between">
      <h1 className="font-serif font-bold text-base tracking-wider uppercase">{title}</h1>
      <Button
        size="sm"
        variant="secondary"
        onClick={() => qc.invalidateQueries()}
        className="gap-2"
      >
        <RefreshCw className="w-3 h-3" /> Refresh
      </Button>
    </header>
  );
}
```

- [ ] **Step 3: PageHeader (sticky h2 + action slot)**

```tsx
// remote-gateway/admin-ui/src/components/layout/PageHeader.tsx
export function PageHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="sticky top-0 z-10 bg-background py-4 border-b border-border flex items-center justify-between mb-6">
      <h2 className="font-serif text-2xl font-bold">{title}</h2>
      {action}
    </div>
  );
}
```

- [ ] **Step 4: EmptyState**

```tsx
// remote-gateway/admin-ui/src/components/layout/EmptyState.tsx
import type { LucideIcon } from 'lucide-react';

export function EmptyState({
  icon: Icon, title, body, action,
}: { icon: LucideIcon; title: string; body: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <Icon className="w-12 h-12 text-ink-muted mb-4" />
      <h3 className="font-serif text-lg font-bold mb-1">{title}</h3>
      <p className="text-sm text-ink-muted max-w-sm mb-4">{body}</p>
      {action}
    </div>
  );
}
```

- [ ] **Step 5: AppShell composes them**

```tsx
// remote-gateway/admin-ui/src/components/layout/AppShell.tsx
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

const TITLES: Record<string, string> = {
  '/dashboard':  'Dashboard',
  '/tool-calls': 'Tool Calls',
  '/tasks':      'Tasks',
  '/operators':  'Operators',
  '/tools':      'Tools',
  '/skills':     'Skills',
  '/tool-hints': 'Tool Hints',
  '/settings':   'Settings',
};

export function AppShell() {
  const { pathname } = useLocation();
  const title = TITLES[pathname] ?? 'Gateway';
  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <TopBar title={title} />
        <main className="flex-1 overflow-y-auto px-6 pb-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/admin-ui/src/components/layout/
git commit -m "feat(admin-ui): add AppShell, Sidebar, TopBar layout"
```

---

## Task 9: Wire React Router with placeholder routes

**Files:**
- Create: `src/routes/*.tsx` (8 placeholder pages + `LoginPage.tsx`)
- Modify: `src/App.tsx`

- [ ] **Step 1: Create one placeholder helper, used by all 8 pages**

```tsx
// remote-gateway/admin-ui/src/routes/_Placeholder.tsx
import { PageHeader } from '@/components/layout/PageHeader';

export function Placeholder({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <p className="text-ink-muted">Coming soon — this page is under construction.</p>
    </>
  );
}
```

- [ ] **Step 2: Create the 8 placeholder pages (each is 3 lines)**

For each of `DashboardPage`, `ToolCallsPage`, `TasksPage`, `OperatorsPage`, `ToolsPage`, `SkillsPage`, `ToolHintsPage`, `SettingsPage`:

```tsx
// remote-gateway/admin-ui/src/routes/DashboardPage.tsx (replicate for each)
import { Placeholder } from './_Placeholder';
export default function DashboardPage() { return <Placeholder title="Dashboard" />; }
```

- [ ] **Step 3: Create the LoginPage**

```tsx
// remote-gateway/admin-ui/src/routes/LoginPage.tsx
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { setToken } from '@/lib/auth';

export default function LoginPage() {
  const [t, setT] = useState('');
  return (
    <div className="flex h-screen items-center justify-center">
      <form
        className="bg-cream-light border border-border p-8 max-w-sm w-full space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          setToken(t);
          window.location.href = '/admin/dashboard';
        }}
      >
        <h1 className="font-serif text-xl font-bold">Admin Token</h1>
        <Input value={t} onChange={(e) => setT(e.target.value)} placeholder="Paste admin token" />
        <Button type="submit" className="w-full">Continue</Button>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Wire the router in App.tsx**

```tsx
// remote-gateway/admin-ui/src/App.tsx
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from '@/components/ui/sonner';
import { queryClient } from '@/lib/queryClient';
import { captureTokenFromUrl } from '@/lib/auth';
import { AppShell } from '@/components/layout/AppShell';
import DashboardPage from '@/routes/DashboardPage';
import ToolCallsPage from '@/routes/ToolCallsPage';
import TasksPage from '@/routes/TasksPage';
import OperatorsPage from '@/routes/OperatorsPage';
import ToolsPage from '@/routes/ToolsPage';
import SkillsPage from '@/routes/SkillsPage';
import ToolHintsPage from '@/routes/ToolHintsPage';
import SettingsPage from '@/routes/SettingsPage';
import LoginPage from '@/routes/LoginPage';

captureTokenFromUrl();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/admin">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard"  element={<DashboardPage />} />
            <Route path="/tool-calls" element={<ToolCallsPage />} />
            <Route path="/tasks"      element={<TasksPage />} />
            <Route path="/operators"  element={<OperatorsPage />} />
            <Route path="/tools"      element={<ToolsPage />} />
            <Route path="/skills"     element={<SkillsPage />} />
            <Route path="/tool-hints" element={<ToolHintsPage />} />
            <Route path="/settings"   element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster richColors position="top-right" />
    </QueryClientProvider>
  );
}
```

- [ ] **Step 5: Verify the dev build**

```bash
cd remote-gateway/admin-ui
npm run build
```

Expected: build succeeds. `dist/index.html` exists, `dist/assets/` has hashed JS/CSS.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/admin-ui/
git commit -m "feat(admin-ui): wire router with placeholder routes"
```

---

## Task 10: Update `admin_api.py` to serve the SPA + keep legacy at `/legacy`

**Files:**
- Modify: `remote-gateway/core/admin_api.py`

- [ ] **Step 1: Read current admin_api.py route table**

Open `remote-gateway/core/admin_api.py`. Locate the `routes = [...]` block at the end of `create_admin_app`. Note the existing `Route("/", dashboard)` at the top and the structure.

- [ ] **Step 2: Replace the routes table with the new layout**

Replace the existing `routes = [...]` block (around line 332) with:

```python
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse

DIST = Path(__file__).parent.parent / "admin-ui" / "dist"

async def _serve_spa(request: Request) -> Response:
    if not _is_authorized(request):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Invalid or missing admin token.</p>",
            status_code=403,
        )
    index = DIST / "index.html"
    if not index.exists():
        return HTMLResponse(
            "<h1>admin-ui not built</h1>"
            "<p>Run <code>cd remote-gateway/admin-ui &amp;&amp; npm run build</code> "
            "or use <code>./dev.sh</code> for development.</p>",
            status_code=503,
        )
    return FileResponse(index)

# Mount the assets directory only if the build exists, so dev mode (no dist/) still boots.
asset_routes: list[Mount] = []
if (DIST / "assets").exists():
    asset_routes.append(
        Mount("/assets", app=StaticFiles(directory=DIST / "assets"), name="admin-assets")
    )

routes = [
    Route("/legacy", dashboard),  # OLD HTML — removed in Phase 8
    Route("/api/stats", api_stats),
    Route("/api/sessions", api_sessions),
    Route("/api/users", api_users_list, methods=["GET"]),
    Route("/api/users", api_users_create, methods=["POST"]),
    Route("/api/users/{user_id}", api_users_delete, methods=["DELETE"]),
    Route("/api/permissions/{user_id}", api_permissions_get, methods=["GET"]),
    Route("/api/permissions/{user_id}/{tool_name:path}", api_permissions_set, methods=["PUT"]),
    Route("/api/timeline", api_timeline),
    Route("/api/tools", api_tools),
    Route("/api/logs", api_logs),
    Route("/api/org-profile", api_org_profile_get, methods=["GET"]),
    Route("/api/org-profile", api_org_profile_update, methods=["PUT"]),
    Route("/api/skills", api_skills_list, methods=["GET"]),
    Route("/api/skills", api_skills_create, methods=["POST"]),
    Route("/api/skills/{name}", api_skills_update, methods=["PUT"]),
    Route("/api/skills/{name}", api_skills_delete, methods=["DELETE"]),
    Route("/api/tool-hints", api_hints_list, methods=["GET"]),
    Route("/api/tool-hints/{tool_name:path}", api_hints_upsert, methods=["PUT"]),
    Route("/api/tasks", api_tasks, methods=["GET"]),
    *asset_routes,
    Route("/{path:path}", _serve_spa),  # SPA catch-all — MUST be last
]
```

Add the imports at the top of the file:

```python
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse
```

- [ ] **Step 3: Add a Python test that the legacy route still works**

```python
# remote-gateway/tests/test_admin_routes.py
from pathlib import Path
from starlette.testclient import TestClient
from remote_gateway.core.admin_api import create_admin_app


def test_legacy_route_serves_html_dashboard(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    app = create_admin_app(telemetry=_FakeTelemetry())
    client = TestClient(app)
    res = client.get("/legacy?token=test-token")
    assert res.status_code == 200
    assert "<title>Gateway Admin</title>" in res.text


def test_spa_fallback_returns_503_when_dist_missing(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    app = create_admin_app(telemetry=_FakeTelemetry())
    client = TestClient(app)
    res = client.get("/dashboard?token=test-token")
    # When dist/ doesn't exist, the SPA fallback returns 503 with the helpful message.
    assert res.status_code == 503
    assert "admin-ui not built" in res.text


def test_unauthorized_returns_403(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    app = create_admin_app(telemetry=_FakeTelemetry())
    client = TestClient(app)
    res = client.get("/dashboard")  # no token
    assert res.status_code == 403


class _FakeTelemetry:
    _enabled = False
    def _connect(self): raise RuntimeError("not used")
```

- [ ] **Step 4: Run Python tests**

```bash
cd /path/to/repo
pytest remote-gateway/tests/test_admin_routes.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/admin_api.py remote-gateway/tests/test_admin_routes.py
git commit -m "feat(admin): serve admin-ui SPA at /admin/ with legacy fallback at /admin/legacy"
```

---

## Task 11: Create `dev.sh` to run Python + Vite together

**Files:**
- Create: `dev.sh` (repo root)

- [ ] **Step 1: Write dev.sh**

```bash
#!/usr/bin/env bash
# dev.sh — run the Remote Gateway and the admin-ui Vite dev server together.
# Ctrl-C kills both. See docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md.
set -euo pipefail

cleanup() {
  echo
  echo "[dev.sh] shutting down…"
  if [[ -n "${PY_PID:-}" ]] && kill -0 "$PY_PID" 2>/dev/null; then kill "$PY_PID" || true; fi
  if [[ -n "${UI_PID:-}" ]] && kill -0 "$UI_PID" 2>/dev/null; then kill "$UI_PID" || true; fi
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "[dev.sh] starting Python gateway on :8000"
python remote-gateway/core/mcp_server.py &
PY_PID=$!

if [[ ! -d remote-gateway/admin-ui/node_modules ]]; then
  echo "[dev.sh] installing admin-ui deps"
  (cd remote-gateway/admin-ui && npm install)
fi

echo "[dev.sh] starting Vite on :5173"
(cd remote-gateway/admin-ui && npm run dev) &
UI_PID=$!

echo
echo "[dev.sh] gateway:  http://localhost:8000"
echo "[dev.sh] admin-ui: http://localhost:5173/admin"
echo "[dev.sh] (Ctrl-C to stop both)"

wait "$PY_PID" "$UI_PID"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x dev.sh
```

- [ ] **Step 3: Smoke test**

```bash
./dev.sh
```

Wait ~5 seconds. Open `http://localhost:5173/admin/dashboard`. Expected: sidebar visible, "Dashboard" page shows the "Coming soon" placeholder. Stop with Ctrl-C — verify both processes exit cleanly.

- [ ] **Step 4: Commit**

```bash
git add dev.sh
git commit -m "feat: add dev.sh to run gateway + admin-ui together"
```

---

## Task 12: Update Dockerfile for the admin-ui build stage

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Inspect existing Dockerfile**

Open `Dockerfile`. Note that Node 20 is already installed (lines 8, 22-25) and there's an existing `npm install` for vendor dependencies.

- [ ] **Step 2: Add admin-ui build steps**

After the existing `RUN npm install --prefix remote-gateway/vendor ...` line (around line 40), add:

```dockerfile
# Build the admin-ui (React + Vite) — Node 20 is already installed above.
COPY remote-gateway/admin-ui/package*.json /app/remote-gateway/admin-ui/
WORKDIR /app/remote-gateway/admin-ui
RUN npm install
COPY remote-gateway/admin-ui /app/remote-gateway/admin-ui
RUN npm run build
WORKDIR /app
```

The two-step COPY (package files → install → full copy → build) keeps the `npm install` layer cached when only source files change.

- [ ] **Step 3: Verify Docker build**

```bash
docker build -t gateway-test .
```

Expected: build completes, `npm run build` succeeds. If you don't have Docker locally, skip this step — CI will catch failures.

- [ ] **Step 4: Verify the bundle is in the image**

```bash
docker run --rm gateway-test ls /app/remote-gateway/admin-ui/dist
```

Expected: `index.html`, `assets/`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile
git commit -m "build: add admin-ui build stage to Dockerfile"
```

---

## Task 13: Update `.gitignore`, root `package.json`, and env examples

**Files:**
- Modify: `.gitignore`, `package.json`, `remote-gateway/admin-ui/.env.example`, `.env.example`

- [ ] **Step 1: Append admin-ui ignores to `.gitignore`**

```
# admin-ui
remote-gateway/admin-ui/node_modules/
remote-gateway/admin-ui/dist/
remote-gateway/admin-ui/.env.local
remote-gateway/admin-ui/coverage/
```

- [ ] **Step 2: Add convenience scripts to root `package.json`**

In the existing root `package.json`, add to `scripts`:

```json
"dev": "./dev.sh",
"build:ui": "cd remote-gateway/admin-ui && npm install && npm run build",
"lint:ui": "cd remote-gateway/admin-ui && npm run lint",
"test:ui": "cd remote-gateway/admin-ui && npm test"
```

- [ ] **Step 3: Create `remote-gateway/admin-ui/.env.example`**

```
# Local dev token. Vite injects this so you don't have to pass ?token=... by hand.
# Must match the ADMIN_TOKEN env var used by the Python gateway.
VITE_ADMIN_TOKEN=inform-admin-2026
```

- [ ] **Step 4: Make Vite proxy inject the token**

Update `remote-gateway/admin-ui/vite.config.ts` proxy block:

```ts
proxy: {
  '/admin/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (path) => {
      const tok = process.env.VITE_ADMIN_TOKEN;
      if (!tok) return path;
      const sep = path.includes('?') ? '&' : '?';
      return `${path}${sep}token=${tok}`;
    },
  },
  '/mcp': { target: 'http://localhost:8000', changeOrigin: true },
},
```

This makes the dev experience seamless: any call from Vite-proxied React to `/admin/api/*` gets the token appended.

- [ ] **Step 5: Verify root `.env.example` mentions ADMIN_TOKEN**

Open `.env.example`. If `ADMIN_TOKEN` isn't documented, add:

```
# Token required to access /admin (dashboard + admin API).
ADMIN_TOKEN=inform-admin-2026
```

- [ ] **Step 6: Commit**

```bash
git add .gitignore package.json remote-gateway/admin-ui/.env.example .env.example remote-gateway/admin-ui/vite.config.ts
git commit -m "chore: gitignore admin-ui artifacts, add root scripts, document VITE_ADMIN_TOKEN"
```

---

## Task 14: Update documentation

**Files:**
- Modify: `CLAUDE.md`, `remote-gateway/CLAUDE.md`, `README.md`
- Create: `remote-gateway/admin-ui/README.md`

- [ ] **Step 1: Update root `CLAUDE.md`**

Add a new section after "Core Commands":

```markdown
## Admin Dashboard

The admin dashboard is a React + Vite + TypeScript + Tailwind + shadcn app at
`remote-gateway/admin-ui/`. It is built into `dist/` at Docker build time and
served by Starlette from `/admin/` (same port as the MCP gateway).

### Local development

```bash
./dev.sh
# Python gateway on :8000, Vite dev server on :5173
# Open http://localhost:5173/admin
```

The Vite dev server proxies `/admin/api/*` to the Python gateway and injects
`VITE_ADMIN_TOKEN` (from `remote-gateway/admin-ui/.env.local`) automatically.

### Building once

```bash
npm run build:ui
python remote-gateway/core/mcp_server.py
# Open http://localhost:8000/admin?token=<ADMIN_TOKEN>
```

### Legacy HTML dashboard

The pre-React HTML dashboard remains available at `/admin/legacy?token=<ADMIN_TOKEN>`
through Phase 8 of the migration as a safety net.
```

- [ ] **Step 2: Update `remote-gateway/CLAUDE.md`**

Add to the existing "Core Infrastructure" section:

```markdown
### Admin Dashboard
- React app at `admin-ui/`, built to `admin-ui/dist/` and served from `/admin/`.
- Local dev: `./dev.sh` from repo root.
- Spec: `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`.
```

- [ ] **Step 3: Update `README.md`**

Add a "Quickstart — Admin Dashboard" subsection under any existing dev/getting-started section. Reuse the snippet from Step 1.

- [ ] **Step 4: Create `remote-gateway/admin-ui/README.md`**

```markdown
# Gateway Admin UI

React + Vite + TypeScript + Tailwind + shadcn dashboard for the Remote Gateway.

## Develop

```bash
# From repo root:
./dev.sh
```

Then open http://localhost:5173/admin. Vite proxies `/admin/api/*` to the
Python gateway on :8000.

## Build

```bash
npm install
npm run build
# Output: dist/
```

The Python gateway serves `dist/` from `/admin/` in production.

## Test

```bash
npm test
```

## Configure

Copy `.env.example` to `.env.local` and adjust:

```
VITE_ADMIN_TOKEN=inform-admin-2026  # must match the Python ADMIN_TOKEN
```

## Spec

See `../../docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md remote-gateway/CLAUDE.md README.md remote-gateway/admin-ui/README.md
git commit -m "docs: document admin-ui dev workflow and structure"
```

---

## Task 15: Add CI checks

**Files:**
- Modify: `.github/workflows/qa_agent_review.yml` (or whichever workflow runs on PRs)

- [ ] **Step 1: Inspect existing PR workflow**

```bash
cat .github/workflows/qa_agent_review.yml
```

Identify the job(s) that run on `pull_request`. We'll add UI build + lint as a new job alongside.

- [ ] **Step 2: Add a `admin-ui` job**

Append to the workflow:

```yaml
  admin-ui:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: remote-gateway/admin-ui/package-lock.json
      - name: Install
        working-directory: remote-gateway/admin-ui
        run: npm ci
      - name: Type check
        working-directory: remote-gateway/admin-ui
        run: npx tsc --noEmit
      - name: Build
        working-directory: remote-gateway/admin-ui
        run: npm run build
      - name: Test
        working-directory: remote-gateway/admin-ui
        run: npm test
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/qa_agent_review.yml
git commit -m "ci: add admin-ui build, type-check, and test job"
```

---

## Task 16: End-to-end verification

- [ ] **Step 1: Build everything from scratch**

```bash
cd remote-gateway/admin-ui
rm -rf node_modules dist
npm install
npm run build
```

Expected: clean install + clean build, no errors.

- [ ] **Step 2: Boot the Python gateway against the built bundle**

```bash
ADMIN_TOKEN=test python remote-gateway/core/mcp_server.py
```

In another terminal:

```bash
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8000/admin/dashboard?token=test"
# Expected: 200

curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8000/admin/dashboard"
# Expected: 403

curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8000/admin/legacy?token=test"
# Expected: 200
```

- [ ] **Step 2.5: Open the dashboard in a browser**

Visit `http://localhost:8000/admin/dashboard?token=test`. Verify:
- Sidebar shows all 8 items in 4 groups (Dashboard / ACTIVITY / REGISTRY / Settings).
- Top bar shows "Dashboard" title and a Refresh button.
- Main content shows "Coming soon — this page is under construction."
- Click each sidebar item — page title updates, URL updates, no console errors.
- Visit `/admin/legacy?token=test` — old HTML dashboard renders.

Stop the Python server.

- [ ] **Step 3: Test the dev.sh loop**

```bash
cp remote-gateway/admin-ui/.env.example remote-gateway/admin-ui/.env.local
./dev.sh
```

Visit `http://localhost:5173/admin`. Verify same behavior. Edit `Sidebar.tsx`, change a label, save — confirm HMR updates the browser in <500ms. Revert. Stop with Ctrl-C, verify both processes exit.

- [ ] **Step 4: Run Python tests**

```bash
pytest remote-gateway/tests/test_admin_routes.py -v
ruff check .
```

Expected: all pass.

- [ ] **Step 5: Run UI tests + lint**

```bash
cd remote-gateway/admin-ui
npm test
npx tsc --noEmit
```

Expected: 4 tests pass (the api/auth tests from Task 5), no type errors.

- [ ] **Step 6: Final commit if anything was tweaked, then push**

```bash
git status
# If clean, no commit needed. If there are stragglers, commit them.
```

---

## Out of scope for this phase

These belong to later phases — do NOT implement here:
- Real data fetching for any page (placeholders only)
- TanStack Query hooks per resource
- DataTable component (built in Phase 2 — Operators)
- Recharts wrappers (built in Phase 7 — Dashboard)
- CommandPalette interactive content (shell only — no real commands)
- Form components (built in Phase 1 — Settings)

## Acceptance criteria

- [ ] `./dev.sh` boots Python + Vite, both reachable.
- [ ] `npm run build` produces `dist/`.
- [ ] `docker build` succeeds; image contains `admin-ui/dist/`.
- [ ] Visiting `/admin/<any-path>?token=<TOKEN>` after a build shows the React shell with sidebar + topbar.
- [ ] Visiting `/admin/legacy?token=<TOKEN>` shows the old HTML dashboard.
- [ ] Visiting `/admin/dashboard` (no token) returns 403.
- [ ] CI runs `tsc --noEmit`, `npm run build`, and `npm test` for admin-ui.
- [ ] No D3 references introduced (recharts is the only chart lib added).
- [ ] All edits to admin-ui/ files use Copier delimiters `[[ ]]` only where templated (`branding.ts`, `index.html` `<title>`, `package.json` `name`).
