# Admin UI — Phase 3: Tools Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy "Tools" tab with a real Tools page: a sortable DataTable of every registered tool with per-row global on/off `<Switch>`. Click a row to open a `<Sheet>` showing the full tool description and any per-user permission overrides.

**Architecture:** Reuses `<DataTable>` from Phase 2. Reuses `useSetPermission` from Phase 2 with the sentinel `userId="*"` (the wildcard global toggle path documented in `CLAUDE.md` — `PUT /api/permissions/*/{tool_name}`). Pulls metadata from `/admin/api/tools`, stats from `/admin/api/stats`, and global enabled state from `/admin/api/permissions/*`. The Sheet detail view also lists which users have *explicit* per-user overrides (computed client-side from sampling user permissions — keep it simple for now).

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`
**Phase 2 Plan:** `2026-05-06-admin-ui-phase-2-operators.md` (DataTable + permissions hooks live there)

---

## Backend API (already exists, do not change)

**GET `/admin/api/tools`** → `[{name: string, description: string}]`. May 503 if `list_tools_fn` wasn't passed to the admin app — handle gracefully (show `<EmptyState>`).

**GET `/admin/api/stats`** → `{ tools: ToolStat[], summary: {...} }` where `ToolStat` is:
```ts
{
  name: string;
  call_count: number;
  error_count: number;
  error_rate: string;        // "0.0%" — pre-formatted
  last_called: string | null; // "2026-05-06T14:30Z" or null
  avg_duration_ms: number;
  max_duration_ms: number;
  avg_response_size: number;
  max_response_size: number;
  avg_input_size: number;
  max_input_size: number;
}
```
Stats only include tools that have been called. Rows with no stats: render `—` for stats columns.

**GET `/admin/api/permissions/*`** — works like the per-user endpoint, but the `*` sentinel means "global toggles." Returns `{user_id: "*", permissions: [{tool_name, enabled}]}` where `enabled: false` means the tool is globally disabled.

**PUT `/admin/api/permissions/*/{tool_name}`** — body `{enabled: bool}`. Same response shape as the per-user PUT.

The existing `useSetPermission(userId)` and `usePermissions(userId)` hooks from Phase 2 already handle this — just pass `'*'` as the user_id.

---

## File Structure

### New files
```
remote-gateway/admin-ui/src/
├── hooks/
│   ├── useTools.ts                ← list registered tools
│   ├── useTools.test.ts
│   ├── useToolStats.ts            ← /api/stats wrapper
│   └── useToolStats.test.ts
└── routes/tools/
    ├── ToolsPage.tsx              ← REPLACES the placeholder; orchestrates table + sheet
    ├── ToolsTable.tsx             ← columns + DataTable
    └── ToolDetailSheet.tsx        ← right-side Sheet with description + override summary
```

### Files modified
- Move `src/routes/ToolsPage.tsx` → `src/routes/tools/ToolsPage.tsx` and update App.tsx import (mirrors the Operators pattern).

---

## Task 1: Tools + ToolStats hooks (TDD)

**Files:**
- Create: `src/hooks/useTools.ts`, `src/hooks/useTools.test.ts`
- Create: `src/hooks/useToolStats.ts`, `src/hooks/useToolStats.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// src/hooks/useTools.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useTools } from './useTools';

function wrapper(qc: QueryClient) {
  return function W({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('useTools', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches the tool list', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => [
        { name: 'attio__search', description: 'Search Attio' },
        { name: 'exa__web_search', description: 'Web search via Exa' },
      ],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useTools(), { wrapper: wrapper(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
  });

  it('returns empty array on 503 (tool listing not configured)', async () => {
    (fetch as any).mockResolvedValue({
      ok: false, status: 503,
      json: async () => ({ error: 'tool listing not configured' }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useTools(), { wrapper: wrapper(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
```

```ts
// src/hooks/useToolStats.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useToolStats } from './useToolStats';

function wrapper(qc: QueryClient) {
  return function W({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('useToolStats', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches stats and returns the tools array', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({
        tools: [
          { name: 'attio__search', call_count: 42, error_count: 0,
            error_rate: '0.0%', last_called: '2026-05-06T14:30Z',
            avg_duration_ms: 120, max_duration_ms: 300,
            avg_response_size: 5_000, max_response_size: 12_000,
            avg_input_size: 200, max_input_size: 800 },
        ],
        summary: { total_calls: 42 },
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useToolStats(), { wrapper: wrapper(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].name).toBe('attio__search');
  });

  it('returns empty array if telemetry returned an error shape', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ error: 'telemetry disabled', tools: [] }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useToolStats(), { wrapper: wrapper(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
```

Run: `npm test`. Expect failures.

- [ ] **Step 2: Implement**

```ts
// src/hooks/useTools.ts
import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';

export type ToolMeta = { name: string; description: string };

export function useTools() {
  return useQuery({
    queryKey: ['tools'],
    queryFn: async (): Promise<ToolMeta[]> => {
      try {
        return await api.get<ToolMeta[]>('/admin/api/tools');
      } catch (err) {
        // 503 means list_tools_fn isn't wired — treat as empty rather than error.
        if (err instanceof ApiError && err.status === 503) return [];
        throw err;
      }
    },
  });
}
```

```ts
// src/hooks/useToolStats.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type ToolStat = {
  name: string;
  call_count: number;
  error_count: number;
  error_rate: string;
  last_called: string | null;
  avg_duration_ms: number;
  max_duration_ms: number;
  avg_response_size: number;
  max_response_size: number;
  avg_input_size: number;
  max_input_size: number;
};

type StatsResponse = { tools: ToolStat[]; summary?: unknown; error?: string };

export function useToolStats() {
  return useQuery({
    queryKey: ['toolStats'],
    queryFn: async (): Promise<ToolStat[]> => {
      const res = await api.get<StatsResponse>('/admin/api/stats');
      return res.tools ?? [];
    },
  });
}
```

Run tests. Expect pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/hooks/useTools.ts remote-gateway/admin-ui/src/hooks/useTools.test.ts remote-gateway/admin-ui/src/hooks/useToolStats.ts remote-gateway/admin-ui/src/hooks/useToolStats.test.ts
git commit -m "feat(admin-ui): add useTools and useToolStats hooks"
```

---

## Task 2: Tools detail Sheet

**File:** `src/routes/tools/ToolDetailSheet.tsx`

Shows when a row is clicked. Has the full description and a section listing per-user overrides for this tool (queried lazily when the sheet opens).

```tsx
// src/routes/tools/ToolDetailSheet.tsx
import { useEffect, useState } from 'react';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useOperators } from '@/hooks/useOperators';
import type { ToolMeta } from '@/hooks/useTools';
import type { ToolStat } from '@/hooks/useToolStats';

type Props = {
  tool: (ToolMeta & Partial<ToolStat>) | null;
  onOpenChange: (open: boolean) => void;
};

type UserPermission = { user_id: string; enabled: boolean };

/**
 * Lazy: only when the sheet is open AND we have an operator list,
 * fan out a permissions GET per user and surface those whose explicit
 * row for this tool differs from the implicit default (enabled: true).
 */
function usePerUserOverrides(toolName: string | null) {
  const { data: operators } = useOperators();
  return useQuery({
    enabled: !!toolName && !!operators?.length,
    queryKey: ['toolOverrides', toolName],
    queryFn: async (): Promise<UserPermission[]> => {
      if (!toolName || !operators) return [];
      const results = await Promise.all(
        operators.map(async (op) => {
          const res = await api.get<{ permissions: { tool_name: string; enabled: boolean }[] }>(
            `/admin/api/permissions/${encodeURIComponent(op.user_id)}`,
          );
          const row = res.permissions.find((p) => p.tool_name === toolName);
          return { user_id: op.user_id, enabled: row?.enabled ?? true };
        }),
      );
      return results.filter((r) => r.enabled === false); // only explicit disables
    },
  });
}

export function ToolDetailSheet({ tool, onOpenChange }: Props) {
  // Cache the last non-null tool so the sheet content doesn't blank out during the close animation.
  const [staged, setStaged] = useState(tool);
  useEffect(() => { if (tool) setStaged(tool); }, [tool]);
  const display = tool ?? staged;

  const overrides = usePerUserOverrides(tool?.name ?? null);

  return (
    <Sheet open={!!tool} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="font-mono text-sm">{display?.name}</SheetTitle>
          <SheetDescription>{display?.description || 'No description.'}</SheetDescription>
        </SheetHeader>

        {display && (
          <div className="space-y-6 mt-6">
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Activity
              </h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">Calls</dt>
                <dd>{display.call_count ?? 0}</dd>
                <dt className="text-muted-foreground">Error rate</dt>
                <dd>{display.error_rate ?? '0.0%'}</dd>
                <dt className="text-muted-foreground">Avg latency</dt>
                <dd>{display.avg_duration_ms != null ? `${display.avg_duration_ms} ms` : '—'}</dd>
                <dt className="text-muted-foreground">Last called</dt>
                <dd>{display.last_called ?? '—'}</dd>
              </dl>
            </section>

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Per-user overrides
              </h3>
              {overrides.isLoading ? (
                <Skeleton className="h-12 w-full" />
              ) : overrides.data?.length ? (
                <div className="space-y-1">
                  {overrides.data.map((u) => (
                    <div key={u.user_id} className="flex justify-between items-center text-sm">
                      <span className="font-mono text-xs">{u.user_id}</span>
                      <Badge variant="destructive">disabled</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No per-user overrides — this tool follows the global toggle.
                </p>
              )}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

No commit yet — combined with Tasks 3-5 below.

---

## Task 3: ToolsTable

**File:** `src/routes/tools/ToolsTable.tsx`

```tsx
// src/routes/tools/ToolsTable.tsx
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Switch } from '@/components/ui/switch';
import { DataTable } from '@/components/data-table/DataTable';
import { Skeleton } from '@/components/ui/skeleton';
import { useTools, type ToolMeta } from '@/hooks/useTools';
import { useToolStats, type ToolStat } from '@/hooks/useToolStats';
import { usePermissions, useSetPermission } from '@/hooks/usePermissions';
import { toast } from 'sonner';

export type MergedTool = ToolMeta & Partial<ToolStat> & { enabled: boolean };

const GLOBAL = '*';

export function ToolsTable({ onRowClick }: { onRowClick: (tool: MergedTool) => void }) {
  const tools = useTools();
  const stats = useToolStats();
  const globals = usePermissions(GLOBAL);
  const setGlobal = useSetPermission(GLOBAL);

  const merged: MergedTool[] = useMemo(() => {
    const statsByName = new Map((stats.data ?? []).map((s) => [s.name, s]));
    const enabledByName = new Map((globals.data ?? []).map((p) => [p.tool_name, p.enabled]));
    return (tools.data ?? []).map((t) => ({
      ...t,
      ...statsByName.get(t.name),
      enabled: enabledByName.get(t.name) ?? true,
    }));
  }, [tools.data, stats.data, globals.data]);

  const columns = useMemo<ColumnDef<MergedTool>[]>(() => [
    { accessorKey: 'name', header: 'Tool',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
    {
      accessorKey: 'description',
      header: 'Description',
      cell: (c) => {
        const v = c.getValue<string>();
        return v ? <span className="text-sm">{v}</span> : <span className="text-muted-foreground">—</span>;
      },
    },
    { accessorKey: 'call_count', header: 'Calls',
      cell: (c) => c.getValue<number | undefined>() ?? <span className="text-muted-foreground">—</span> },
    { accessorKey: 'error_rate', header: 'Errors',
      cell: (c) => c.getValue<string | undefined>() ?? <span className="text-muted-foreground">—</span> },
    { accessorKey: 'last_called', header: 'Last Called',
      cell: (c) => c.getValue<string | null | undefined>() ?? <span className="text-muted-foreground">—</span> },
    {
      id: 'enabled',
      header: 'Global',
      cell: ({ row }) => (
        <Switch
          checked={row.original.enabled}
          onClick={(e) => e.stopPropagation()}
          onCheckedChange={(enabled) => {
            setGlobal.mutate(
              { tool_name: row.original.name, enabled },
              {
                onSuccess: () =>
                  toast.success(`${row.original.name} ${enabled ? 'enabled' : 'disabled'}`),
                onError: (err) =>
                  toast.error(err instanceof Error ? err.message : 'Failed to toggle'),
              },
            );
          }}
        />
      ),
    },
  ], [setGlobal]);

  if (tools.isLoading || globals.isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <DataTable
      columns={columns}
      data={merged}
      getRowId={(t) => t.name}
      onRowClick={onRowClick}
      emptyMessage="No tools registered. Configure mcp_connections.json to add proxied integrations."
      pageSize={50}
      initialSorting={[{ id: 'call_count', desc: true }]}
    />
  );
}
```

No commit yet.

---

## Task 4: ToolsPage + delete placeholder + update App.tsx

**Files:**
- Create: `src/routes/tools/ToolsPage.tsx`
- Delete: `src/routes/ToolsPage.tsx` (placeholder)
- Modify: `src/App.tsx` (import path)

```tsx
// src/routes/tools/ToolsPage.tsx
import { useState } from 'react';
import { PageHeader } from '@/components/layout/PageHeader';
import { ToolsTable, type MergedTool } from './ToolsTable';
import { ToolDetailSheet } from './ToolDetailSheet';

export default function ToolsPage() {
  const [selected, setSelected] = useState<MergedTool | null>(null);
  return (
    <>
      <PageHeader title="Tools" />
      <ToolsTable onRowClick={setSelected} />
      <ToolDetailSheet tool={selected} onOpenChange={(open) => { if (!open) setSelected(null); }} />
    </>
  );
}
```

Delete + update import:

```bash
git rm remote-gateway/admin-ui/src/routes/ToolsPage.tsx
```

In `src/App.tsx`, change:

```tsx
import ToolsPage from '@/routes/ToolsPage';
```

to:

```tsx
import ToolsPage from '@/routes/tools/ToolsPage';
```

That is the only App.tsx edit.

---

## Task 5: Verify build + commit Tasks 2-4 together

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm run build
```

Expected: clean. Bundle stays roughly the same size (no major new deps — we reuse existing primitives).

Commit:

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/routes/tools/ remote-gateway/admin-ui/src/App.tsx
git commit -m "feat(admin-ui): build Tools page (table + global toggles + detail sheet)"
```

---

## Task 6: Manual smoke (deferred)

When `./dev.sh` is running, verify at `/admin/tools`:

- [ ] Table loads with all registered tools (or shows the empty-state message if `mcp_connections.json` is empty).
- [ ] Stats columns populate for tools with call history; show `—` otherwise.
- [ ] Sort by Calls (default) puts the most-called tools at the top. Click "Tool" header → sorts by name. Click again → reverses.
- [ ] Toggle the Global switch on a tool. Toast appears. Refresh — state persists.
- [ ] Click a row (not the switch). Sheet opens from the right with description + activity dl + per-user overrides section. The overrides section starts in skeleton state, then either lists users or says "No per-user overrides."
- [ ] Close the Sheet via Escape or the X button. Selection clears.

---

## Task 7: Final verification

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test          # expect ~21 tests pass (Phases 0-2 baseline + 4 new from Task 1)
npx tsc -b        # clean
npm run build     # clean
cd ../..
pytest remote-gateway/tests/test_admin_routes.py -v  # 3 pass
```

```bash
git log --oneline | head -5
```

Expected: 2 new commits since Phase 2:
1. feat(admin-ui): add useTools and useToolStats hooks
2. feat(admin-ui): build Tools page (table + global toggles + detail sheet)

---

## Out of Scope

- Per-tool drill-down (raw call logs filtered by this tool) — that's the **Tool Calls** page, Phase 5.
- Changing tool descriptions or metadata — those come from the registered tools, edited in code.
- Bulk enable/disable. Not in spec.
- A "newest tools first" or "recently changed" filter — current sort by call_count covers the common need.
- Per-user override editing inline in the sheet — that's the Operators page workflow.

---

## Acceptance Criteria

- [ ] `useTools` and `useToolStats` exist with passing tests including the 503 / error-shape edge cases.
- [ ] `/admin/tools` shows a table with columns: Tool, Description, Calls, Errors, Last Called, Global.
- [ ] Default sort is Calls descending.
- [ ] Per-row Global Switch toggles `PUT /admin/api/permissions/*/{tool_name}`. Switch click does NOT open the row sheet (event propagation stopped).
- [ ] Row click opens a right-side Sheet with description, activity stats, and per-user overrides section.
- [ ] Per-user override section lazily fetches one permissions request per operator and lists only those with explicit `enabled: false` for this tool.
- [ ] Empty state when no tools registered (e.g. fresh template install with empty `mcp_connections.json`) is friendly.
- [ ] `npm test`, `npx tsc -b`, `npm run build`, `pytest test_admin_routes.py` all pass.
