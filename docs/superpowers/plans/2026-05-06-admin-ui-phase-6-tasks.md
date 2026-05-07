# Admin UI — Phase 6: Tasks Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy "Tasks" tab with a Tasks page: filterable DataTable of tasks (active/complete/all), with row-click opening a Sheet that shows the task's metadata, outcome, and a nested table of every tool call attributed to it (`task_id` filter on `/admin/api/logs`).

**Architecture:** Reuses `<DataTable>` (Phase 2), `useToolCalls` from Phase 5 with a `task_id` filter for the nested table, and the Sheet/ScrollArea patterns established in Tools and Tool Calls. URL search param drives the status filter so views are deep-linkable.

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`

---

## Backend API (already exists, do not change)

**GET `/admin/api/tasks`** — query: `status?` (`"active"|"complete"`), `limit?` (1..500, default 100), `org_id?`.
Response: `{ org_id, tasks: Task[], count }`

**Task shape:**
```ts
{
  task_id: string;
  user_id: string;
  org_id: string;
  goal: string;
  steps: unknown[] | null;     // server returns parsed JSON or null
  status: 'active' | 'complete';
  outcome: string | null;
  created_at: number | string;
  completed_at: number | string | null;
}
```

Tool calls for a single task come via the existing `useToolCalls({task_id})` from Phase 5.

---

## File Structure

### New files
```
remote-gateway/admin-ui/src/
├── hooks/
│   ├── useTasks.ts
│   └── useTasks.test.ts
└── routes/tasks/
    ├── TasksPage.tsx            ← REPLACES placeholder
    ├── TasksTable.tsx
    └── TaskDetailSheet.tsx
```

### Files modified
- Move `src/routes/TasksPage.tsx` → `src/routes/tasks/TasksPage.tsx`
- `src/App.tsx` — update import path

---

## Task 1: useTasks hook (TDD)

**Files:** `src/hooks/useTasks.ts`, `src/hooks/useTasks.test.ts`

- [ ] **Step 1: Failing tests**

```ts
// src/hooks/useTasks.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useTasks } from './useTasks';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useTasks', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches and unwraps the tasks array from the envelope', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        org_id: 'default',
        tasks: [{
          task_id: 't1', user_id: 'u', org_id: 'default', goal: 'do thing',
          steps: null, status: 'active', outcome: null,
          created_at: 1, completed_at: null,
        }],
        count: 1,
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useTasks({}), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].task_id).toBe('t1');
  });

  it('passes status filter as query param when set', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => ({ org_id: 'default', tasks: [], count: 0 }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useTasks({ status: 'active' }), { wrapper: wrap(qc) });
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('status=active');
  });

  it('omits status param when filter is empty', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => ({ org_id: 'default', tasks: [], count: 0 }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useTasks({}), { wrapper: wrap(qc) });
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).not.toContain('status=');
  });
});
```

- [ ] **Step 2: Implement**

```ts
// src/hooks/useTasks.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type Task = {
  task_id: string;
  user_id: string;
  org_id: string;
  goal: string;
  steps: unknown[] | null;
  status: 'active' | 'complete';
  outcome: string | null;
  created_at: number | string;
  completed_at: number | string | null;
};

type TasksResponse = { org_id: string; tasks: Task[]; count: number };

export type TasksFilters = {
  status?: 'active' | 'complete' | '';
  limit?: number;
};

export function useTasks(filters: TasksFilters) {
  const params: Record<string, string | number> = {};
  if (filters.status) params.status = filters.status;
  if (filters.limit) params.limit = filters.limit;

  return useQuery({
    queryKey: ['tasks', filters],
    queryFn: async () => {
      const res = await api.get<TasksResponse>('/admin/api/tasks', params);
      return res.tasks;
    },
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
git add remote-gateway/admin-ui/src/hooks/useTasks.ts remote-gateway/admin-ui/src/hooks/useTasks.test.ts
git commit -m "feat(admin-ui): add useTasks hook with status filter"
```

---

## Task 2: TaskDetailSheet (with nested tool-calls table)

**File:** `src/routes/tasks/TaskDetailSheet.tsx`

```tsx
// src/routes/tasks/TaskDetailSheet.tsx
import { useEffect, useState } from 'react';
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import { CheckCircle2, XCircle } from 'lucide-react';
import { useToolCalls } from '@/hooks/useToolCalls';
import type { Task } from '@/hooks/useTasks';

type Props = {
  task: Task | null;
  onOpenChange: (open: boolean) => void;
};

function formatTs(ts: number | string | null): string {
  if (ts == null) return '—';
  if (typeof ts === 'string') return ts;
  return new Date(ts * 1000).toISOString().replace('.000Z', 'Z');
}

function durationStr(start: number | string, end: number | string | null): string {
  if (end == null) return 'in progress';
  const s = typeof start === 'string' ? Date.parse(start) / 1000 : start;
  const e = typeof end === 'string' ? Date.parse(end) / 1000 : end;
  const sec = Math.max(0, Math.round(e - s));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

export function TaskDetailSheet({ task, onOpenChange }: Props) {
  const [staged, setStaged] = useState(task);
  useEffect(() => { if (task) setStaged(task); }, [task]);
  const t = task ?? staged;

  const calls = useToolCalls({
    limit: 100,
    offset: 0,
    task_id: t?.task_id,
  });

  return (
    <Sheet open={!!task} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {t?.goal ?? 'Task'}
            {t?.status === 'active' && <Badge>active</Badge>}
            {t?.status === 'complete' && <Badge variant="secondary">complete</Badge>}
          </SheetTitle>
          <SheetDescription>
            {t?.user_id ?? '—'} · {t?.task_id ?? '—'}
          </SheetDescription>
        </SheetHeader>

        {t && (
          <div className="space-y-6 mt-6 text-sm">
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Timeline
              </h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
                <dt className="text-muted-foreground">Created</dt>
                <dd className="font-mono text-xs">{formatTs(t.created_at)}</dd>
                <dt className="text-muted-foreground">Completed</dt>
                <dd className="font-mono text-xs">{formatTs(t.completed_at)}</dd>
                <dt className="text-muted-foreground">Duration</dt>
                <dd>{durationStr(t.created_at, t.completed_at)}</dd>
              </dl>
            </section>

            {t.outcome && (
              <section>
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  Outcome
                </h3>
                <ScrollArea className="max-h-32 rounded border border-border">
                  <p className="p-3 text-sm whitespace-pre-wrap">{t.outcome}</p>
                </ScrollArea>
              </section>
            )}

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Tool calls ({calls.data?.length ?? 0})
              </h3>
              {calls.isLoading ? (
                <Skeleton className="h-32 w-full" />
              ) : !calls.data?.length ? (
                <p className="text-sm text-muted-foreground">
                  No tool calls recorded for this task.
                </p>
              ) : (
                <div className="rounded border border-border divide-y divide-border max-h-96 overflow-y-auto">
                  {calls.data.map((c) => (
                    <div key={c.id} className="px-3 py-2 flex items-center gap-3 text-xs">
                      {c.success
                        ? <CheckCircle2 className="w-3 h-3 text-moss-light shrink-0" />
                        : <XCircle className="w-3 h-3 text-destructive shrink-0" />}
                      <span className="font-mono truncate flex-1">{c.tool_name}</span>
                      <span className="text-muted-foreground">{c.duration_ms}ms</span>
                      <span className="text-muted-foreground font-mono">{c.called_at}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

No commit yet.

---

## Task 3: TasksTable + TasksPage + delete placeholder

**Files:**
- Create: `src/routes/tasks/TasksTable.tsx`, `src/routes/tasks/TasksPage.tsx`
- Delete: `src/routes/TasksPage.tsx`
- Modify: `src/App.tsx` import path

### TasksTable.tsx

```tsx
// src/routes/tasks/TasksTable.tsx
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { DataTable } from '@/components/data-table/DataTable';
import { useTasks, type Task, type TasksFilters } from '@/hooks/useTasks';

function formatRel(ts: number | string): string {
  const t = typeof ts === 'string' ? Date.parse(ts) / 1000 : ts;
  const diff = Math.round(Date.now() / 1000 - t);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function durationStr(start: number | string, end: number | string | null): string {
  if (end == null) return '—';
  const s = typeof start === 'string' ? Date.parse(start) / 1000 : start;
  const e = typeof end === 'string' ? Date.parse(end) / 1000 : end;
  const sec = Math.max(0, Math.round(e - s));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

export function TasksTable({
  filters,
  onRowClick,
}: {
  filters: TasksFilters;
  onRowClick: (t: Task) => void;
}) {
  const { data, isLoading } = useTasks(filters);

  const columns = useMemo<ColumnDef<Task>[]>(() => [
    {
      accessorKey: 'goal',
      header: 'Goal',
      cell: (c) => <span className="text-sm">{c.getValue<string>()}</span>,
    },
    {
      accessorKey: 'user_id',
      header: 'User',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span>,
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) =>
        row.original.status === 'active'
          ? <Badge>active</Badge>
          : <Badge variant="secondary">complete</Badge>,
    },
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: (c) => <span className="text-muted-foreground text-xs">{formatRel(c.getValue<number | string>())}</span>,
    },
    {
      id: 'duration',
      header: 'Duration',
      cell: ({ row }) => (
        <span className="text-muted-foreground text-xs">
          {durationStr(row.original.created_at, row.original.completed_at)}
        </span>
      ),
    },
  ], []);

  if (isLoading) return <Skeleton className="h-96 w-full" />;
  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      getRowId={(t) => t.task_id}
      onRowClick={onRowClick}
      emptyMessage="No tasks match the current filter."
      pageSize={50}
    />
  );
}
```

### TasksPage.tsx

```tsx
// src/routes/tasks/TasksPage.tsx
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageHeader } from '@/components/layout/PageHeader';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { TasksTable } from './TasksTable';
import { TaskDetailSheet } from './TaskDetailSheet';
import type { Task } from '@/hooks/useTasks';

const ALL = '__all__';

export default function TasksPage() {
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<Task | null>(null);

  const status = (params.get('status') ?? '') as '' | 'active' | 'complete';

  const setStatus = (next: string) => {
    const p = new URLSearchParams(params);
    if (next && next !== ALL) p.set('status', next); else p.delete('status');
    setParams(p, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Tasks"
        action={
          <Select value={status || ALL} onValueChange={(v) => setStatus(v ?? '')}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="complete">Complete</SelectItem>
            </SelectContent>
          </Select>
        }
      />
      <TasksTable filters={{ status: status || undefined, limit: 200 }} onRowClick={setSelected} />
      <TaskDetailSheet
        task={selected}
        onOpenChange={(open) => { if (!open) setSelected(null); }}
      />
    </>
  );
}
```

Delete placeholder + update App.tsx:

```bash
git rm remote-gateway/admin-ui/src/routes/TasksPage.tsx
```

In `src/App.tsx`, change `from '@/routes/TasksPage'` to `from '@/routes/tasks/TasksPage'`.

---

## Task 4: Verify build + commit Tasks 2-3 together

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm run build
```

Expected: clean.

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/routes/tasks/ remote-gateway/admin-ui/src/App.tsx
git commit -m "feat(admin-ui): build Tasks page (filterable table + nested tool-calls sheet)"
```

---

## Task 5: Manual smoke (deferred)

When `./dev.sh` is running, visit `/admin/tasks`:

- [ ] Table loads with recent tasks (active + complete intermixed). Empty-state if none.
- [ ] Status filter (top-right Select) defaults to "All". Switch to "Active" — URL updates with `?status=active`, table refetches.
- [ ] Click a task row. Sheet opens with timeline (created/completed/duration), outcome (if present), and a nested table of tool calls for that task.
- [ ] Tool-calls section shows green ✓ / red ✕ icon per call.
- [ ] Sheet's outcome ScrollArea scrolls if the outcome is long.
- [ ] Refresh with `?status=active` set — filter persists.

---

## Task 6: Final verification

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test           # expect 30 baseline + 3 new = 33
npx tsc -b
npm run build
cd ../..
pytest remote-gateway/tests/test_admin_routes.py -v
```

Expected: 33 Vitest tests pass, tsc clean, build clean, 3 pytest pass.

```bash
git log --oneline | head -3
```

Expected: 2 new commits.

---

## Out of Scope

- Task search by goal text. Backend doesn't support; UI search would only work over the current page.
- Triggering / cancelling tasks from the UI. Tasks are written by agents via `declare_intent` / `complete_task`.
- Re-running a task. Out of scope.
- Filtering by user. Easy follow-up if asked.
- Showing the `steps` field. Backend stores it, but the spec didn't call for it; revisit when needed.

---

## Acceptance Criteria

- [ ] `useTasks(filters)` exists with passing tests covering envelope unwrap and status param shaping.
- [ ] `/admin/tasks` shows a 5-column DataTable: Goal · User · Status · Created · Duration.
- [ ] Status Select in the page header drives a URL `?status=` param.
- [ ] Row click opens a Sheet with timeline, outcome (if any), and a nested table of every tool call attributed to the task (uses `useToolCalls` with `task_id` filter).
- [ ] All tests + tsc + build + Python tests pass.
