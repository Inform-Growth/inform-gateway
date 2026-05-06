# Admin UI — Phase 7: Dashboard Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy "Executive" tab with a Dashboard page: 4 KPI cards (total calls, tools tracked, high-error tools, avg latency), three recharts visuals (Sankey for tool flow, LineChart for activity timeline, BarChart for user adoption), and a Tool Health DataTable. This is the home page (`/admin/dashboard`) — the first thing operators see.

**Architecture:** All visuals are **recharts** components (no D3). Each chart is a small, self-contained component that takes pre-shaped data. Data fetching uses three new hooks (`useStats`, `useSessions`, `useTimeline`) plus the existing `useToolStats` from Phase 3 for the Tool Health table. Charts gracefully render an empty state when there's no data.

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`

---

## Backend API (already exists, do not change)

### `/admin/api/stats`

Returns `{ tools: ToolStat[], summary: { total_calls: number, total_tools_seen: number, high_error_rate: string[] } }`. Phase 3's `useToolStats` already wraps this and returns `tools`. We need a parallel hook (`useStatsSummary`) that returns `summary`.

### `/admin/api/sessions`

```ts
{
  sankey: {
    nodes: { id: string; name: string }[];
    links: { source: string; target: string; value: number }[];
  };
  user_breakdown: Record<string, number>;   // user_id → total calls all-time
  recent_sequences: Record<string, unknown>; // not used here
}
```

The Sankey block is server-shaped to be recharts-compatible: nodes have a stable `name` and links use `source`/`target` strings (recharts accepts string ids).

### `/admin/api/timeline?days=N`

```ts
{
  users: string[];                           // distinct user_ids in the period
  days: { day: string; [user_id: string]: number | string }[];  // 0 if absent
}
```

`day` is `"YYYY-MM-DD"`. For the LineChart we'll compute a `total` per day client-side. For the BarChart we'll use `user_breakdown` from `/sessions` (it's already aggregated all-time).

---

## File Structure

### New files
```
remote-gateway/admin-ui/src/
├── hooks/
│   ├── useStatsSummary.ts          ← reads /api/stats, returns summary block
│   ├── useStatsSummary.test.ts
│   ├── useSessions.ts              ← reads /api/sessions
│   ├── useSessions.test.ts
│   ├── useTimeline.ts              ← reads /api/timeline?days=N
│   └── useTimeline.test.ts
└── routes/dashboard/
    ├── DashboardPage.tsx           ← REPLACES placeholder
    ├── KPICards.tsx                ← 4 cards in a grid
    ├── ToolFlowSankey.tsx          ← recharts <Sankey>
    ├── ActivityTimeline.tsx        ← recharts <LineChart> total calls/day
    ├── UserAdoptionChart.tsx       ← recharts <BarChart> per user
    └── ToolHealthTable.tsx         ← reuses Phase 3 useToolStats + DataTable
```

### Files modified
- Move `src/routes/DashboardPage.tsx` → `src/routes/dashboard/DashboardPage.tsx`
- `src/App.tsx` — update import path

---

## Task 1: Three new hooks (TDD)

**Files:** `src/hooks/{useStatsSummary,useSessions,useTimeline}.ts` + matching `.test.ts`

- [ ] **Step 1: Failing tests**

```ts
// src/hooks/useStatsSummary.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useStatsSummary } from './useStatsSummary';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useStatsSummary', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('extracts the summary block', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        tools: [{ name: 'a', call_count: 100, avg_duration_ms: 50 }],
        summary: { total_calls: 100, total_tools_seen: 1, high_error_rate: ['x'] },
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useStatsSummary(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      total_calls: 100, total_tools_seen: 1, high_error_rate: ['x'],
    });
  });

  it('returns zeroed defaults when telemetry returned an error shape', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ error: 'telemetry disabled', tools: [] }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useStatsSummary(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      total_calls: 0, total_tools_seen: 0, high_error_rate: [],
    });
  });
});
```

```ts
// src/hooks/useSessions.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useSessions } from './useSessions';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useSessions', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('returns sankey + user_breakdown', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        sankey: {
          nodes: [{ id: 'a', name: 'a' }, { id: 'b', name: 'b' }],
          links: [{ source: 'a', target: 'b', value: 5 }],
        },
        user_breakdown: { alice: 10, bob: 3 },
        recent_sequences: {},
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useSessions(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.sankey.links).toHaveLength(1);
    expect(result.current.data?.user_breakdown).toEqual({ alice: 10, bob: 3 });
  });
});
```

```ts
// src/hooks/useTimeline.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useTimeline } from './useTimeline';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useTimeline', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('passes the days query param', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => ({ users: [], days: [] }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useTimeline(7), { wrapper: wrap(qc) });
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('days=7');
  });

  it('computes total per day across users', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        users: ['alice', 'bob'],
        days: [
          { day: '2026-05-01', alice: 3, bob: 2 },
          { day: '2026-05-02', alice: 0, bob: 1 },
        ],
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useTimeline(30), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.totals).toEqual([
      { day: '2026-05-01', total: 5 },
      { day: '2026-05-02', total: 1 },
    ]);
    expect(result.current.data?.users).toEqual(['alice', 'bob']);
  });
});
```

- [ ] **Step 2: Implement**

```ts
// src/hooks/useStatsSummary.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type StatsSummary = {
  total_calls: number;
  total_tools_seen: number;
  high_error_rate: string[];
};

type StatsResponse = {
  tools?: unknown[];
  summary?: Partial<StatsSummary>;
  error?: string;
};

const EMPTY: StatsSummary = { total_calls: 0, total_tools_seen: 0, high_error_rate: [] };

export function useStatsSummary() {
  return useQuery({
    queryKey: ['statsSummary'],
    queryFn: async (): Promise<StatsSummary> => {
      const res = await api.get<StatsResponse>('/admin/api/stats');
      const s = res.summary;
      if (!s) return EMPTY;
      return {
        total_calls: s.total_calls ?? 0,
        total_tools_seen: s.total_tools_seen ?? 0,
        high_error_rate: s.high_error_rate ?? [],
      };
    },
  });
}
```

```ts
// src/hooks/useSessions.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type SankeyNode = { id: string; name: string };
export type SankeyLink = { source: string; target: string; value: number };

export type SessionsData = {
  sankey: { nodes: SankeyNode[]; links: SankeyLink[] };
  user_breakdown: Record<string, number>;
};

export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: async (): Promise<SessionsData> => {
      const res = await api.get<{
        sankey?: { nodes?: SankeyNode[]; links?: SankeyLink[] };
        user_breakdown?: Record<string, number>;
      }>('/admin/api/sessions');
      return {
        sankey: {
          nodes: res.sankey?.nodes ?? [],
          links: res.sankey?.links ?? [],
        },
        user_breakdown: res.user_breakdown ?? {},
      };
    },
  });
}
```

```ts
// src/hooks/useTimeline.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

type TimelineRow = { day: string; [user: string]: number | string };
type TimelineResponse = { users: string[]; days: TimelineRow[] };

export type TimelineData = {
  users: string[];
  rows: TimelineRow[];                      // raw per-user breakdown (kept for future use)
  totals: { day: string; total: number }[]; // sum across users per day
};

export function useTimeline(days: number) {
  return useQuery({
    queryKey: ['timeline', days],
    queryFn: async (): Promise<TimelineData> => {
      const res = await api.get<TimelineResponse>('/admin/api/timeline', { days });
      const totals = res.days.map((row) => {
        let sum = 0;
        for (const user of res.users) {
          const v = row[user];
          if (typeof v === 'number') sum += v;
        }
        return { day: row.day, total: sum };
      });
      return { users: res.users, rows: res.days, totals };
    },
  });
}
```

- [ ] **Step 3: Verify + commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
```

Expected: 5 new tests pass.

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/hooks/useStatsSummary.ts remote-gateway/admin-ui/src/hooks/useStatsSummary.test.ts \
        remote-gateway/admin-ui/src/hooks/useSessions.ts remote-gateway/admin-ui/src/hooks/useSessions.test.ts \
        remote-gateway/admin-ui/src/hooks/useTimeline.ts remote-gateway/admin-ui/src/hooks/useTimeline.test.ts
git commit -m "feat(admin-ui): add useStatsSummary, useSessions, useTimeline hooks"
```

---

## Task 2: KPI Cards

**File:** `src/routes/dashboard/KPICards.tsx`

```tsx
// src/routes/dashboard/KPICards.tsx
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useStatsSummary } from '@/hooks/useStatsSummary';
import { useToolStats } from '@/hooks/useToolStats';

function KPI({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">{label}</div>
        <div className="text-3xl font-serif font-bold">{value}</div>
        {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
      </CardContent>
    </Card>
  );
}

export function KPICards() {
  const summary = useStatsSummary();
  const stats = useToolStats();

  if (summary.isLoading || stats.isLoading) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
      </div>
    );
  }

  const totalCalls = summary.data?.total_calls ?? 0;
  const toolsSeen = summary.data?.total_tools_seen ?? 0;
  const highErrorCount = summary.data?.high_error_rate.length ?? 0;
  const avgLatency = (() => {
    const tools = stats.data ?? [];
    if (tools.length === 0) return 0;
    const totalCallsWeighted = tools.reduce((s, t) => s + (t.avg_duration_ms ?? 0) * t.call_count, 0);
    const totalCallsAll = tools.reduce((s, t) => s + t.call_count, 0);
    return totalCallsAll > 0 ? Math.round(totalCallsWeighted / totalCallsAll) : 0;
  })();

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      <KPI label="Total Calls" value={totalCalls.toLocaleString()} />
      <KPI label="Tools Tracked" value={toolsSeen} />
      <KPI
        label="High Error Rate"
        value={highErrorCount}
        hint={highErrorCount > 0 ? 'tools with ≥5% errors' : 'no problem tools'}
      />
      <KPI label="Avg Latency" value={`${avgLatency}ms`} hint="weighted by call count" />
    </div>
  );
}
```

No commit yet — combined later.

---

## Task 3: Three chart components

**Files:** `src/routes/dashboard/{ToolFlowSankey,ActivityTimeline,UserAdoptionChart}.tsx`

### ToolFlowSankey.tsx

```tsx
// src/routes/dashboard/ToolFlowSankey.tsx
import { Sankey, ResponsiveContainer, Tooltip } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useSessions } from '@/hooks/useSessions';

export function ToolFlowSankey() {
  const { data, isLoading } = useSessions();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Tool Flow Patterns</CardTitle>
      </CardHeader>
      <CardContent className="h-80">
        {isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : !data?.sankey.links.length ? (
          <p className="text-sm text-muted-foreground py-8 text-center">
            Not enough data to draw a flow yet — keep using the gateway.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <Sankey
              data={data.sankey}
              nodePadding={20}
              link={{ stroke: 'var(--moss-mid)' }}
              node={{
                fill: 'var(--primary)',
                stroke: 'var(--border)',
              } as never /* recharts types are loose here */}
            >
              <Tooltip />
            </Sankey>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
```

### ActivityTimeline.tsx

```tsx
// src/routes/dashboard/ActivityTimeline.tsx
import {
  LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useTimeline } from '@/hooks/useTimeline';

export function ActivityTimeline() {
  const { data, isLoading } = useTimeline(30);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Activity — Last 30 Days</CardTitle>
      </CardHeader>
      <CardContent className="h-72">
        {isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : !data?.totals.length ? (
          <p className="text-sm text-muted-foreground py-8 text-center">No calls in the last 30 days.</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.totals} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <YAxis stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="total" stroke="var(--primary)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
```

### UserAdoptionChart.tsx

```tsx
// src/routes/dashboard/UserAdoptionChart.tsx
import {
  BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useSessions } from '@/hooks/useSessions';

export function UserAdoptionChart() {
  const { data, isLoading } = useSessions();
  const breakdown = Object.entries(data?.user_breakdown ?? {})
    .map(([user, calls]) => ({ user, calls }))
    .sort((a, b) => b.calls - a.calls)
    .slice(0, 10); // top 10 users

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">User Adoption</CardTitle>
      </CardHeader>
      <CardContent className="h-72">
        {isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : breakdown.length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">No user activity yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={breakdown} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="user" stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <YAxis stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="calls" fill="var(--accent)" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
```

No commit yet.

---

## Task 4: ToolHealthTable

**File:** `src/routes/dashboard/ToolHealthTable.tsx`

```tsx
// src/routes/dashboard/ToolHealthTable.tsx
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/data-table/DataTable';
import { useToolStats, type ToolStat } from '@/hooks/useToolStats';

export function ToolHealthTable() {
  const { data, isLoading } = useToolStats();

  const columns = useMemo<ColumnDef<ToolStat>[]>(() => [
    { accessorKey: 'name', header: 'Tool',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
    { accessorKey: 'call_count', header: 'Calls' },
    { accessorKey: 'error_count', header: 'Errors' },
    {
      accessorKey: 'error_rate',
      header: 'Error Rate',
      cell: ({ row }) => {
        const rate = row.original.error_rate ?? '0.0%';
        const numeric = parseFloat(rate);
        return numeric >= 5
          ? <Badge variant="destructive">{rate}</Badge>
          : <span className="text-sm">{rate}</span>;
      },
    },
    { accessorKey: 'avg_duration_ms', header: 'Avg ms' },
    { accessorKey: 'max_duration_ms', header: 'Max ms' },
    {
      accessorKey: 'last_called',
      header: 'Last Called',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string | null>() ?? '—'}</span>,
    },
  ], []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Tool Health</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <DataTable
            columns={columns}
            data={data ?? []}
            getRowId={(t) => t.name}
            emptyMessage="No tool calls recorded yet."
            pageSize={25}
            initialSorting={[{ id: 'call_count', desc: true }]}
          />
        )}
      </CardContent>
    </Card>
  );
}
```

No commit yet.

---

## Task 5: DashboardPage + delete placeholder + update App.tsx

**File:** `src/routes/dashboard/DashboardPage.tsx`

```tsx
// src/routes/dashboard/DashboardPage.tsx
import { PageHeader } from '@/components/layout/PageHeader';
import { KPICards } from './KPICards';
import { ToolFlowSankey } from './ToolFlowSankey';
import { ActivityTimeline } from './ActivityTimeline';
import { UserAdoptionChart } from './UserAdoptionChart';
import { ToolHealthTable } from './ToolHealthTable';

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="Dashboard" />
      <KPICards />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
        <ToolFlowSankey />
        <UserAdoptionChart />
      </div>
      <div className="mb-8">
        <ActivityTimeline />
      </div>
      <ToolHealthTable />
    </>
  );
}
```

Delete + update import:

```bash
git rm remote-gateway/admin-ui/src/routes/DashboardPage.tsx
```

In `src/App.tsx`, change `from '@/routes/DashboardPage'` to `from '@/routes/dashboard/DashboardPage'`.

---

## Task 6: Verify build + commit Tasks 2-5 together

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm run build
```

Expected: clean. Bundle will jump notably (+~80kB) because recharts pulls in its own SVG plumbing.

If TS complains about the `Sankey` component's `node`/`link` props being incorrectly typed (recharts has loose types here), the plan already includes an `as never` cast on `node`. Add a similar cast on `link` if needed.

Commit:

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/routes/dashboard/ remote-gateway/admin-ui/src/App.tsx
git commit -m "feat(admin-ui): build Dashboard page (KPI cards + recharts visuals + tool health)"
```

---

## Task 7: Manual smoke (deferred)

When `./dev.sh` is running, visit `/admin/dashboard`:

- [ ] Four KPI cards render with real numbers (or zeros if telemetry has no data).
- [ ] Sankey card shows the tool flow if data exists, else a friendly "Not enough data" message.
- [ ] User Adoption BarChart shows top 10 users.
- [ ] Activity Timeline LineChart shows daily totals over 30 days.
- [ ] Tool Health table sorts by call count desc by default. Tools with ≥5% error rate show their rate as a destructive Badge.
- [ ] Refreshing the page (Cmd-R) re-renders without errors. The TopBar Refresh button invalidates all queries.

---

## Task 8: Final verification

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test            # expect 33 baseline + 5 new = 38
npx tsc -b
npm run build
cd ../..
pytest remote-gateway/tests/test_admin_routes.py -v
```

Expected: 38 Vitest tests pass, tsc clean, build clean, 3 pytest pass.

```bash
git log --oneline | head -3
```

Expected: 2 new commits.

---

## Out of Scope

- Per-user adoption time series (we'd need to overlay `useTimeline.rows`'s per-user keys as multiple `<Line>`s — easy but cosmetic).
- Configurable timeline window (7 / 30 / 90 days). Hardcoded to 30 for now.
- Drill-down from the Tool Health table into the Tools page (would be a nice link).
- Sankey customization (colors per node, hover detail). Default recharts styling is good enough for v1.
- A "today vs yesterday" comparison or sparkline per KPI.
- Caching strategy for stats (currently 10s staleTime from the global query client).

---

## Acceptance Criteria

- [ ] `useStatsSummary`, `useSessions`, `useTimeline` exist with passing tests.
- [ ] `/admin/dashboard` shows KPI cards, two charts in a 2-col grid, full-width timeline, tool health table.
- [ ] All charts render an empty-state message when their data is empty.
- [ ] All charts use recharts (no D3 imports anywhere in the new code).
- [ ] `noUnusedLocals` doesn't trip on chart imports — only import what's used.
- [ ] All tests + tsc + build + Python tests pass.
