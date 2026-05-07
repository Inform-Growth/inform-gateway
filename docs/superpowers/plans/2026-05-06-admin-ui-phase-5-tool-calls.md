# Admin UI — Phase 5: Tool Calls Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy "Logs" tab with a Tool Calls page: server-side-filtered + paginated DataTable of tool calls (newest first), with row-click opening a Sheet that shows the full input body and response preview for one call.

**Architecture:** Reuses `<DataTable>` from Phase 2, but bypasses its client-side pagination (`pageSize={0}`) and adds external `← →` controls driven by a server-side `offset` cursor (the backend returns plain arrays with no total-count metadata, so we can only show "Page N", not "Page N of M"). Filters live in URL search params so views are deep-linkable. The detail Sheet pretty-prints `input_body` and `response_preview` in a `<ScrollArea>`.

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`
**Phase 2 Plan:** `2026-05-06-admin-ui-phase-2-operators.md` (DataTable + Sheet patterns)

---

## Backend API (already exists, do not change)

**GET `/admin/api/logs`** — query params:
- `limit` (1..1000, default 100)
- `offset` (default 0)
- `tool` (optional, exact match on `tool_name`)
- `user` (optional, exact match on `user_id`)
- `success` (`"true"` | `"false"`)
- `error_type` (optional)
- `task_id` (optional)

**Response:** array of `ToolCall`. **No total-count metadata, no envelope.** Pagination is opaque cursor-style: a returned array shorter than `limit` means there's no next page.

**ToolCall shape:**
```ts
{
  id: number;
  tool_name: string;
  called_at: string | null;        // "2026-05-06T14:30:00Z"
  duration_ms: number;
  success: boolean;
  error_type: string | null;
  error_message: string | null;
  user_id: string | null;
  request_id: string | null;
  response_size: number | null;
  input_size: number | null;
  input_body: string | null;        // JSON-encoded request
  response_preview: string | null;  // truncated response
  task_id: string | null;
}
```

**Note:** the legacy HTML had a `success=blocked` filter option in the dropdown; the backend doesn't support this — the existing JS filtered client-side after fetching. Skipping `blocked` for now to keep the page server-side-pure; revisit in a later polish pass if anyone asks.

---

## File Structure

### New files
```
remote-gateway/admin-ui/src/
├── hooks/
│   ├── useToolCalls.ts             ← server-side filters + offset pagination
│   └── useToolCalls.test.ts
└── routes/tool-calls/
    ├── ToolCallsPage.tsx           ← REPLACES placeholder; orchestrates filters + table + sheet
    ├── ToolCallsTable.tsx          ← columns + DataTable
    ├── ToolCallsFilters.tsx        ← inputs + select wired to URL search params
    └── ToolCallDetailSheet.tsx     ← right Sheet with metadata + JSON viewer
```

### Files modified
- Move `src/routes/ToolCallsPage.tsx` → `src/routes/tool-calls/ToolCallsPage.tsx`
- `src/App.tsx` — update import path

---

## Task 1: useToolCalls hook (TDD)

**Files:** `src/hooks/useToolCalls.ts`, `src/hooks/useToolCalls.test.ts`

- [ ] **Step 1: Failing tests**

```ts
// src/hooks/useToolCalls.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useToolCalls } from './useToolCalls';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useToolCalls', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('passes limit + offset query params', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => [],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useToolCalls({ limit: 25, offset: 50 }), { wrapper: wrap(qc) });
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('limit=25');
    expect(url).toContain('offset=50');
  });

  it('omits empty filter params and includes provided ones', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => [],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(
      () => useToolCalls({
        limit: 100, offset: 0, tool: 'attio__search', user: '', success: 'false',
      }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('tool=attio__search');
    expect(url).toContain('success=false');
    expect(url).not.toContain('user=');
  });

  it('returns the array as data', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => [{
        id: 1, tool_name: 'x', called_at: '2026-05-06T14:00:00Z', duration_ms: 100,
        success: true, error_type: null, error_message: null, user_id: 'u',
        request_id: 'r', response_size: 1, input_size: 2, input_body: null,
        response_preview: null, task_id: null,
      }],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useToolCalls({ limit: 100, offset: 0 }), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Implement**

```ts
// src/hooks/useToolCalls.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type ToolCall = {
  id: number;
  tool_name: string;
  called_at: string | null;
  duration_ms: number;
  success: boolean;
  error_type: string | null;
  error_message: string | null;
  user_id: string | null;
  request_id: string | null;
  response_size: number | null;
  input_size: number | null;
  input_body: string | null;
  response_preview: string | null;
  task_id: string | null;
};

export type ToolCallFilters = {
  limit: number;
  offset: number;
  tool?: string;
  user?: string;
  success?: 'true' | 'false' | '';
  error_type?: string;
  task_id?: string;
};

export function useToolCalls(filters: ToolCallFilters) {
  return useQuery({
    queryKey: ['toolCalls', filters],
    queryFn: () => api.get<ToolCall[]>('/admin/api/logs', filters),
    placeholderData: (prev) => prev, // keep last page during navigation for smooth UX
  });
}
```

- [ ] **Step 3: Verify + commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
```

Expected: 3 new tests pass.

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/hooks/useToolCalls.ts remote-gateway/admin-ui/src/hooks/useToolCalls.test.ts
git commit -m "feat(admin-ui): add useToolCalls hook with server-side filters"
```

---

## Task 2: ToolCallDetailSheet

**File:** `src/routes/tool-calls/ToolCallDetailSheet.tsx`

```tsx
// src/routes/tool-calls/ToolCallDetailSheet.tsx
import { useEffect, useState } from 'react';
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import type { ToolCall } from '@/hooks/useToolCalls';

type Props = {
  call: ToolCall | null;
  onOpenChange: (open: boolean) => void;
};

function tryPretty(json: string | null): string {
  if (!json) return '—';
  try { return JSON.stringify(JSON.parse(json), null, 2); } catch { return json; }
}

export function ToolCallDetailSheet({ call, onOpenChange }: Props) {
  // Stage the last non-null call so the close animation doesn't flash blank.
  const [staged, setStaged] = useState(call);
  useEffect(() => { if (call) setStaged(call); }, [call]);
  const c = call ?? staged;

  return (
    <Sheet open={!!call} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="font-mono text-sm flex items-center gap-2">
            {c?.tool_name}
            {c?.success === false && <Badge variant="destructive">error</Badge>}
            {c?.success === true && <Badge variant="secondary">ok</Badge>}
          </SheetTitle>
          <SheetDescription>
            {c?.called_at ?? '—'} · {c?.duration_ms ?? 0}ms · user {c?.user_id ?? '—'}
          </SheetDescription>
        </SheetHeader>

        {c && (
          <div className="space-y-6 mt-6 text-sm">
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Metadata
              </h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
                <dt className="text-muted-foreground">Request ID</dt>
                <dd className="font-mono text-xs">{c.request_id ?? '—'}</dd>
                <dt className="text-muted-foreground">Task ID</dt>
                <dd className="font-mono text-xs">{c.task_id ?? '—'}</dd>
                <dt className="text-muted-foreground">Input size</dt>
                <dd>{c.input_size ?? '—'} bytes</dd>
                <dt className="text-muted-foreground">Response size</dt>
                <dd>{c.response_size ?? '—'} bytes</dd>
              </dl>
            </section>

            {c.success === false && (
              <section>
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  Error
                </h3>
                <div className="p-3 bg-destructive/10 text-destructive font-mono text-xs rounded">
                  <div className="font-bold">{c.error_type ?? 'unknown'}</div>
                  <div className="mt-1 whitespace-pre-wrap">{c.error_message ?? '(no message)'}</div>
                </div>
              </section>
            )}

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Request body
              </h3>
              <ScrollArea className="h-48 rounded border border-border">
                <pre className="p-3 font-mono text-xs whitespace-pre-wrap break-all">
                  {tryPretty(c.input_body)}
                </pre>
              </ScrollArea>
            </section>

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Response preview
              </h3>
              <ScrollArea className="h-48 rounded border border-border">
                <pre className="p-3 font-mono text-xs whitespace-pre-wrap break-all">
                  {c.response_preview ?? '—'}
                </pre>
              </ScrollArea>
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

No commit yet — combined later.

---

## Task 3: ToolCallsFilters (URL-synced)

**File:** `src/routes/tool-calls/ToolCallsFilters.tsx`

Filters live in URL `?tool=...&user=...&success=...` so views are deep-linkable.

```tsx
// src/routes/tool-calls/ToolCallsFilters.tsx
import { useSearchParams } from 'react-router-dom';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import type { ToolCallFilters } from '@/hooks/useToolCalls';

const ALL = '__all__';

export function useToolCallsFilters(): {
  filters: ToolCallFilters;
  setFilter: (key: 'tool' | 'user' | 'success', value: string) => void;
  page: number;
  setPage: (n: number) => void;
} {
  const [params, setParams] = useSearchParams();

  const tool = params.get('tool') ?? '';
  const user = params.get('user') ?? '';
  const success = (params.get('success') ?? '') as '' | 'true' | 'false';
  const page = Number(params.get('page') ?? '0');
  const pageSize = 50;

  const setFilter = (key: 'tool' | 'user' | 'success', value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    next.delete('page'); // reset paging when filters change
    setParams(next, { replace: true });
  };

  const setPage = (n: number) => {
    const next = new URLSearchParams(params);
    if (n > 0) next.set('page', String(n)); else next.delete('page');
    setParams(next, { replace: true });
  };

  return {
    filters: {
      limit: pageSize,
      offset: page * pageSize,
      tool: tool || undefined,
      user: user || undefined,
      success: success || undefined,
    },
    setFilter,
    page,
    setPage,
  };
}

export function ToolCallsFilters({
  filters,
  setFilter,
}: {
  filters: ToolCallFilters;
  setFilter: (key: 'tool' | 'user' | 'success', value: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      <Input
        placeholder="Filter by tool…"
        defaultValue={filters.tool ?? ''}
        onBlur={(e) => setFilter('tool', e.target.value.trim())}
        onKeyDown={(e) => {
          if (e.key === 'Enter') setFilter('tool', (e.target as HTMLInputElement).value.trim());
        }}
        className="font-mono text-xs max-w-xs"
      />
      <Input
        placeholder="Filter by user…"
        defaultValue={filters.user ?? ''}
        onBlur={(e) => setFilter('user', e.target.value.trim())}
        onKeyDown={(e) => {
          if (e.key === 'Enter') setFilter('user', (e.target as HTMLInputElement).value.trim());
        }}
        className="font-mono text-xs max-w-xs"
      />
      <Select
        value={filters.success || ALL}
        onValueChange={(v) => setFilter('success', v === ALL ? '' : v)}
      >
        <SelectTrigger className="w-40">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All statuses</SelectItem>
          <SelectItem value="true">Success only</SelectItem>
          <SelectItem value="false">Errors only</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
```

`onBlur` + `Enter` trigger filter changes — avoids hitting the API on every keystroke. Plain UX choice; revisit if it feels sluggish.

No commit yet.

---

## Task 4: ToolCallsTable

**File:** `src/routes/tool-calls/ToolCallsTable.tsx`

```tsx
// src/routes/tool-calls/ToolCallsTable.tsx
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { CheckCircle2, XCircle } from 'lucide-react';
import { DataTable } from '@/components/data-table/DataTable';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ToolCall } from '@/hooks/useToolCalls';

type Props = {
  data: ToolCall[];
  isLoading: boolean;
  pageSize: number;
  page: number;
  onPage: (n: number) => void;
  onRowClick: (c: ToolCall) => void;
};

export function ToolCallsTable({ data, isLoading, pageSize, page, onPage, onRowClick }: Props) {
  const columns = useMemo<ColumnDef<ToolCall>[]>(() => [
    {
      accessorKey: 'called_at',
      header: 'Time',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string | null>() ?? '—'}</span>,
    },
    {
      accessorKey: 'tool_name',
      header: 'Tool',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span>,
    },
    {
      accessorKey: 'user_id',
      header: 'User',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string | null>() ?? '—'}</span>,
    },
    {
      accessorKey: 'duration_ms',
      header: 'Duration',
      cell: (c) => `${c.getValue<number>()}ms`,
    },
    {
      accessorKey: 'response_size',
      header: 'Out',
      cell: (c) => {
        const v = c.getValue<number | null>();
        return v == null ? <span className="text-muted-foreground">—</span> : <span>{v}B</span>;
      },
    },
    {
      id: 'status',
      header: 'Status',
      cell: ({ row }) =>
        row.original.success
          ? <CheckCircle2 className="w-4 h-4 text-moss-light" />
          : <XCircle className="w-4 h-4 text-destructive" />,
    },
  ], []);

  if (isLoading && data.length === 0) return <Skeleton className="h-96 w-full" />;

  // The backend returns no count; "next" is enabled when the page is full.
  const hasNext = data.length === pageSize;
  const hasPrev = page > 0;

  return (
    <div className="space-y-2">
      <DataTable
        columns={columns}
        data={data}
        getRowId={(r) => String(r.id)}
        onRowClick={onRowClick}
        pageSize={0}
        emptyMessage="No tool calls match the current filters."
      />
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>Page {page + 1}</span>
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={() => onPage(page - 1)} disabled={!hasPrev}>
            <ChevronLeft className="w-3 h-3" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => onPage(page + 1)} disabled={!hasNext}>
            <ChevronRight className="w-3 h-3" />
          </Button>
        </div>
      </div>
    </div>
  );
}
```

No commit yet.

---

## Task 5: ToolCallsPage + delete placeholder + update App.tsx

**File:** `src/routes/tool-calls/ToolCallsPage.tsx`

```tsx
// src/routes/tool-calls/ToolCallsPage.tsx
import { useState } from 'react';
import { PageHeader } from '@/components/layout/PageHeader';
import { useToolCalls, type ToolCall } from '@/hooks/useToolCalls';
import { ToolCallsFilters, useToolCallsFilters } from './ToolCallsFilters';
import { ToolCallsTable } from './ToolCallsTable';
import { ToolCallDetailSheet } from './ToolCallDetailSheet';

export default function ToolCallsPage() {
  const { filters, setFilter, page, setPage } = useToolCallsFilters();
  const { data, isLoading } = useToolCalls(filters);
  const [selected, setSelected] = useState<ToolCall | null>(null);

  return (
    <>
      <PageHeader title="Tool Calls" />
      <ToolCallsFilters filters={filters} setFilter={setFilter} />
      <ToolCallsTable
        data={data ?? []}
        isLoading={isLoading}
        pageSize={filters.limit}
        page={page}
        onPage={setPage}
        onRowClick={setSelected}
      />
      <ToolCallDetailSheet
        call={selected}
        onOpenChange={(open) => { if (!open) setSelected(null); }}
      />
    </>
  );
}
```

Delete placeholder + update App.tsx:

```bash
git rm remote-gateway/admin-ui/src/routes/ToolCallsPage.tsx
```

In `src/App.tsx`, change:

```tsx
import ToolCallsPage from '@/routes/ToolCallsPage';
```

to:

```tsx
import ToolCallsPage from '@/routes/tool-calls/ToolCallsPage';
```

---

## Task 6: Verify build + commit Tasks 2-5 together

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm run build
```

Expected: clean.

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/routes/tool-calls/ remote-gateway/admin-ui/src/App.tsx
git commit -m "feat(admin-ui): build Tool Calls page (filters + paginated table + detail sheet)"
```

---

## Task 7: Manual smoke (deferred)

When `./dev.sh` is running, navigate to `/admin/tool-calls`:

- [ ] Table loads with recent tool calls (newest first), 50 per page.
- [ ] Status icon column shows green ✓ for success, red ✕ for error.
- [ ] Filter by tool: type a name, blur (or Enter). URL updates with `?tool=...`. Table refetches.
- [ ] Filter by user: same.
- [ ] Status select: switch to "Errors only". Table shows only failed calls. URL has `?success=false`.
- [ ] Paginate: click `→`. URL has `?page=1`. Filters preserved.
- [ ] Click a row. Sheet opens with metadata, error block (if applicable), pretty-printed request body, response preview. Both `<ScrollArea>`s scroll independently.
- [ ] Close sheet via Escape. Selection clears, URL unchanged.
- [ ] Refresh the page with all filters set. State persists from URL.
- [ ] Filters reset paging: change tool while on page 3 → returns to page 0.

---

## Task 8: Final verification

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test           # expect 27 baseline + 3 new = 30
npx tsc -b
npm run build
cd ../..
pytest remote-gateway/tests/test_admin_routes.py -v
```

```bash
git log --oneline | head -3
```

Expected: 2 new commits since Phase 4:
1. feat(admin-ui): add useToolCalls hook with server-side filters
2. feat(admin-ui): build Tool Calls page (filters + paginated table + detail sheet)

---

## Out of Scope

- `success=blocked` filter (legacy HTML had it, backend doesn't support it; client-side post-filter would muddy the pagination story).
- Real-time tail mode (auto-refresh while looking at recent calls). Could be a Phase 7+ polish.
- Filtering by date range / time window. Backend doesn't support; would require new endpoint params.
- Exporting to CSV. Not in spec.
- Highlighting rows from the same `request_id` group. Could be useful but not in spec.
- Linking from a row to the Operators page (filtered by user) or Tools page (filtered by tool name). Easy follow-up.
- Linking from `task_id` to the Tasks page. Phase 6 will introduce that surface.

---

## Acceptance Criteria

- [ ] `useToolCalls(filters)` exists with passing tests covering query-param shaping.
- [ ] `/admin/tool-calls` shows a table with columns: Time · Tool · User · Duration · Out · Status.
- [ ] Status column renders green check or red X icon.
- [ ] Three filter controls (tool, user, success) wired to URL search params; refresh preserves state.
- [ ] Filters reset `?page=0`.
- [ ] Pagination via external prev/next buttons; "next" disabled when fewer than `limit` rows returned.
- [ ] `placeholderData` keeps the last page on screen during pagination so the UI doesn't flash blank.
- [ ] Row click opens a Sheet with metadata, error block (when `success=false`), pretty-printed request body, and response preview.
- [ ] Both ScrollAreas in the Sheet scroll independently.
- [ ] All tests + tsc + build + Python tests pass.
