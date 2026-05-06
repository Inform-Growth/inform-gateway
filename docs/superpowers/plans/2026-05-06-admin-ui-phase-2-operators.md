# Admin UI — Phase 2: Operators Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy "Ops" tab with a real Operators page: a master/detail layout where the left side lists users (operators) in a sortable shadcn DataTable, the right side shows the selected operator's per-tool permissions, and a `+ Add Operator` Dialog reveals a fresh API key once.

**Architecture:** Reusable `<DataTable>` built on TanStack Table + shadcn `Table` (this same component will power Tools / Skills / Tool Hints / Tool Calls / Tasks in subsequent phases — get the API right here). Master/detail layout. Optimistic mutations for permission toggles. API-key reveal uses an inline `<Alert>` with a copy button (the key is only returned once by the backend).

**Tech Stack:** Same as Phase 1, plus `@tanstack/react-table` 8 (already installed). No backend changes.

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`
**Phase 0 Plan:** `2026-05-05-admin-ui-phase-0-scaffolding.md`
**Phase 1 Plan:** `2026-05-06-admin-ui-phase-1-settings.md`

---

## Backend API (already exists, do not change)

### Users

**GET `/admin/api/users`** → array. The free-form shape from `telemetry.list_users()` includes (at minimum) the columns the legacy HTML rendered: `user_id`, `key`, `call_count`, `last_active`. The `key` is a redacted preview (e.g. `sk-…abc123`); the FULL plaintext key is only returned once at creation time. Treat unknown extra fields as opaque pass-through.

**POST `/admin/api/users`** — body `{ "user_id": "alice@example.com" }` → 201 `{ "user_id": "alice@example.com", "key": "sk-FULL-PLAINTEXT-HERE" }`. **The full key is ONLY in this response — show it once, copy-now-or-lose-it.**

**DELETE `/admin/api/users/{user_id}`** → `{ "deleted": 1, "user_id": "..." }` or 404 `{ "error": "user not found" }`.

### Permissions

**GET `/admin/api/permissions/{user_id}`** →
```json
{
  "user_id": "alice@example.com",
  "permissions": [
    { "tool_name": "attio__search_records", "enabled": true },
    { "tool_name": "exa__web_search", "enabled": false },
    ...
  ]
}
```
The endpoint MERGES the explicit per-user permissions table with the live registered-tools list (every tool gets a row, defaulting to `enabled: true` if no explicit row exists).

**PUT `/admin/api/permissions/{user_id}/{tool_name}`** — body `{ "enabled": true|false }` → `{ "ok": true, "user_id", "tool_name", "enabled" }`. Path param `tool_name` may contain `__` and slashes (the route uses `{tool_name:path}`).

### Tools (used for ordering / search)

**GET `/admin/api/tools`** → `[ { "name": "attio__search_records", "description": "..." }, ... ]` (all registered tools, including proxied ones), OR 503 `{ "error": "tool listing not configured" }` when the gateway didn't pass `list_tools_fn` to the admin app. The Operators page only needs the permissions endpoint (which already merges in tool names), so `useTools` is OPTIONAL here — defer to Phase 3 (Tools page) if it adds friction.

---

## File Structure

### New files
```
remote-gateway/admin-ui/src/
├── components/data-table/
│   ├── DataTable.tsx              ← reusable TanStack Table + shadcn Table wrapper
│   └── DataTable.test.tsx         ← basic interaction tests
├── hooks/
│   ├── useOperators.ts            ← list / create / delete
│   ├── useOperators.test.ts
│   ├── usePermissions.ts          ← get / set (optimistic)
│   └── usePermissions.test.ts
└── routes/operators/
    ├── OperatorsPage.tsx          ← REPLACES the placeholder; orchestrates layout
    ├── OperatorsTable.tsx         ← columns + DataTable wiring
    ├── PermissionsPanel.tsx       ← right pane: search + toggles
    └── AddOperatorDialog.tsx      ← Dialog + form + key-reveal Alert
```

### Files modified
- `src/routes/OperatorsPage.tsx` — replace the 3-line placeholder with the real page.

The existing placeholder lives at `src/routes/OperatorsPage.tsx`. Move the file into `src/routes/operators/OperatorsPage.tsx` and update the import path in `src/App.tsx` accordingly. (See Task 5 for the exact App.tsx edit.)

---

## Task 1: Build the reusable DataTable component

**Files:**
- Create: `src/components/data-table/DataTable.tsx`
- Create: `src/components/data-table/DataTable.test.tsx`

This component is the foundation for every future table page. Get the API right.

- [ ] **Step 1: Write failing tests**

```tsx
// src/components/data-table/DataTable.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataTable } from './DataTable';

type Row = { id: string; name: string; calls: number };

const columns: ColumnDef<Row>[] = [
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'calls', header: 'Calls' },
];

const data: Row[] = [
  { id: '1', name: 'Alice', calls: 10 },
  { id: '2', name: 'Bob',   calls: 3 },
];

describe('DataTable', () => {
  it('renders rows from data', () => {
    render(<DataTable columns={columns} data={data} getRowId={(r) => r.id} />);
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
  });

  it('renders empty state when no rows', () => {
    render(
      <DataTable columns={columns} data={[]} getRowId={(r) => r.id} emptyMessage="Nothing here" />
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });

  it('calls onRowClick with the row when a row is clicked', () => {
    let clicked: Row | null = null;
    render(
      <DataTable
        columns={columns}
        data={data}
        getRowId={(r) => r.id}
        onRowClick={(r) => { clicked = r; }}
      />,
    );
    fireEvent.click(screen.getByText('Alice'));
    expect(clicked).toEqual(data[0]);
  });

  it('highlights the selected row when selectedRowId is provided', () => {
    const { container } = render(
      <DataTable
        columns={columns}
        data={data}
        getRowId={(r) => r.id}
        selectedRowId="2"
      />,
    );
    const selected = container.querySelector('[data-selected="true"]');
    expect(selected?.textContent).toContain('Bob');
  });
});
```

Run: `npm test`. Tests should fail because `DataTable` doesn't exist yet.

- [ ] **Step 2: Implement DataTable**

```tsx
// src/components/data-table/DataTable.tsx
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { useState } from 'react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

type DataTableProps<T> = {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  getRowId: (row: T) => string;
  /** Called when a row is clicked. Omit for non-interactive tables. */
  onRowClick?: (row: T) => void;
  /** ID of the currently-selected row (highlights via data-selected). */
  selectedRowId?: string;
  /** Page size for pagination. Set 0 to disable pagination. */
  pageSize?: number;
  /** Shown when data is empty. */
  emptyMessage?: string;
  /** Initial sort state. */
  initialSorting?: SortingState;
};

export function DataTable<T>({
  columns,
  data,
  getRowId,
  onRowClick,
  selectedRowId,
  pageSize = 25,
  emptyMessage = 'No results.',
  initialSorting = [],
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: pageSize > 0 ? getPaginationRowModel() : undefined,
    getRowId: (row) => getRowId(row as T),
    initialState: pageSize > 0 ? { pagination: { pageSize } } : undefined,
  });

  return (
    <div className="space-y-2">
      <div className="rounded-md border border-border overflow-hidden">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => {
                  const sort = header.column.getIsSorted();
                  return (
                    <TableHead
                      key={header.id}
                      onClick={header.column.getCanSort() ? header.column.getToggleSortingHandler() : undefined}
                      className={cn(header.column.getCanSort() && 'cursor-pointer select-none')}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                      {sort === 'asc' && ' ↑'}
                      {sort === 'desc' && ' ↓'}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                  {emptyMessage}
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => {
                const isSelected = row.id === selectedRowId;
                return (
                  <TableRow
                    key={row.id}
                    data-selected={isSelected}
                    className={cn(
                      onRowClick && 'cursor-pointer hover:bg-secondary',
                      isSelected && 'bg-secondary',
                    )}
                    onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {pageSize > 0 && table.getPageCount() > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
          </span>
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronLeft className="w-3 h-3" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              <ChevronRight className="w-3 h-3" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Run tests — expect pass**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
```

Expected: 4 new DataTable tests pass + 7 existing = 11 total.

- [ ] **Step 4: Commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/components/data-table/
git commit -m "feat(admin-ui): add reusable DataTable on TanStack Table"
```

---

## Task 2: Operators hooks (TDD)

**Files:**
- Create: `src/hooks/useOperators.ts`
- Create: `src/hooks/useOperators.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// src/hooks/useOperators.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useOperators, useCreateOperator, useDeleteOperator } from './useOperators';

function wrapper(qc: QueryClient) {
  return function W({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('useOperators', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches the user list', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => [
        { user_id: 'a', key: 'sk-…aaa', call_count: 5, last_active: '2026-05-01' },
      ],
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useOperators(), { wrapper: wrapper(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].user_id).toBe('a');
  });
});

describe('useCreateOperator', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('POSTs user_id and returns the new key, then invalidates the list', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ user_id: 'alice', key: 'sk-FULL-PLAINTEXT' }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useCreateOperator(), { wrapper: wrapper(qc) });

    let returned: { user_id: string; key: string } | undefined;
    await act(async () => {
      returned = await result.current.mutateAsync('alice');
    });

    expect(returned).toEqual({ user_id: 'alice', key: 'sk-FULL-PLAINTEXT' });
    const [, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ user_id: 'alice' });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['operators'] });
  });
});

describe('useDeleteOperator', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('DELETEs the user and invalidates the list', async () => {
    (fetch as any).mockResolvedValue({
      ok: true, json: async () => ({ deleted: 1, user_id: 'alice' }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useDeleteOperator(), { wrapper: wrapper(qc) });

    await act(async () => { await result.current.mutateAsync('alice'); });

    const [url, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('DELETE');
    expect(url).toMatch(/\/admin\/api\/users\/alice\?token=tkn$/);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['operators'] });
  });
});
```

Run: `npm test`. Should fail (hook file missing).

- [ ] **Step 2: Implement**

```ts
// src/hooks/useOperators.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type Operator = {
  user_id: string;
  key: string;          // redacted preview
  call_count: number;
  last_active: string | null;
  [extra: string]: unknown;
};

export type CreateOperatorResponse = {
  user_id: string;
  key: string;          // FULL plaintext — only present in this response
};

const QUERY_KEY = ['operators'] as const;

export function useOperators() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => api.get<Operator[]>('/admin/api/users'),
  });
}

export function useCreateOperator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (user_id: string) =>
      api.post<CreateOperatorResponse>('/admin/api/users', { user_id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useDeleteOperator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (user_id: string) =>
      api.delete<{ deleted: number; user_id: string }>(
        `/admin/api/users/${encodeURIComponent(user_id)}`,
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}
```

Run tests. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/admin-ui/src/hooks/useOperators.ts remote-gateway/admin-ui/src/hooks/useOperators.test.ts
git commit -m "feat(admin-ui): add useOperators hooks (list/create/delete)"
```

---

## Task 3: Permissions hooks with optimistic updates (TDD)

**Files:**
- Create: `src/hooks/usePermissions.ts`
- Create: `src/hooks/usePermissions.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// src/hooks/usePermissions.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { usePermissions, useSetPermission } from './usePermissions';

function wrapper(qc: QueryClient) {
  return function W({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('usePermissions', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches permissions for a user', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({
        user_id: 'alice',
        permissions: [
          { tool_name: 'attio__search', enabled: true },
          { tool_name: 'exa__search',   enabled: false },
        ],
      }),
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => usePermissions('alice'), { wrapper: wrapper(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
  });

  it('does not fetch when user_id is null (disabled query)', () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => usePermissions(null), { wrapper: wrapper(qc) });
    expect(result.current.fetchStatus).toBe('idle');
    expect((fetch as any).mock?.calls?.length ?? 0).toBe(0);
  });
});

describe('useSetPermission', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('PUTs the new value and optimistically updates cache', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, user_id: 'alice', tool_name: 'attio__search', enabled: false }),
    });

    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    qc.setQueryData(['permissions', 'alice'], [
      { tool_name: 'attio__search', enabled: true },
      { tool_name: 'exa__search',   enabled: false },
    ]);

    const { result } = renderHook(() => useSetPermission('alice'), { wrapper: wrapper(qc) });

    await act(async () => {
      await result.current.mutateAsync({ tool_name: 'attio__search', enabled: false });
    });

    const cached = qc.getQueryData<{ tool_name: string; enabled: boolean }[]>(
      ['permissions', 'alice'],
    );
    expect(cached?.find((p) => p.tool_name === 'attio__search')?.enabled).toBe(false);

    const [url, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('PUT');
    expect(url).toContain('/admin/api/permissions/alice/attio__search');
    expect(JSON.parse(init.body)).toEqual({ enabled: false });
  });
});
```

Run: `npm test`. Should fail.

- [ ] **Step 2: Implement**

```ts
// src/hooks/usePermissions.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type Permission = { tool_name: string; enabled: boolean };

type PermissionsResponse = { user_id: string; permissions: Permission[] };

const KEY = (userId: string) => ['permissions', userId] as const;

export function usePermissions(userId: string | null) {
  return useQuery({
    queryKey: userId ? KEY(userId) : ['permissions', '__none__'],
    enabled: !!userId,
    queryFn: async (): Promise<Permission[]> => {
      const res = await api.get<PermissionsResponse>(
        `/admin/api/permissions/${encodeURIComponent(userId!)}`,
      );
      return res.permissions;
    },
  });
}

export function useSetPermission(userId: string) {
  const qc = useQueryClient();
  const queryKey = KEY(userId);

  return useMutation({
    mutationFn: ({ tool_name, enabled }: Permission) =>
      api.put(
        `/admin/api/permissions/${encodeURIComponent(userId)}/${encodeURI(tool_name)}`,
        { enabled },
      ),
    onMutate: async ({ tool_name, enabled }) => {
      await qc.cancelQueries({ queryKey });
      const previous = qc.getQueryData<Permission[]>(queryKey);
      if (previous) {
        qc.setQueryData<Permission[]>(
          queryKey,
          previous.map((p) => (p.tool_name === tool_name ? { ...p, enabled } : p)),
        );
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKey, ctx.previous);
    },
    onSettled: () => qc.invalidateQueries({ queryKey }),
  });
}
```

Run tests. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add remote-gateway/admin-ui/src/hooks/usePermissions.ts remote-gateway/admin-ui/src/hooks/usePermissions.test.ts
git commit -m "feat(admin-ui): add usePermissions hooks with optimistic updates"
```

---

## Task 4: Add Operator dialog with key reveal

**File:** `src/routes/operators/AddOperatorDialog.tsx`

```tsx
// src/routes/operators/AddOperatorDialog.tsx
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { toast } from 'sonner';
import { Copy, Plus, Check } from 'lucide-react';
import { useCreateOperator } from '@/hooks/useOperators';

export function AddOperatorDialog() {
  const [open, setOpen] = useState(false);
  const [userId, setUserId] = useState('');
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const create = useCreateOperator();

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    create.mutate(userId, {
      onSuccess: ({ key }) => setCreatedKey(key),
      onError: (err) =>
        toast.error(err instanceof Error ? err.message : 'Failed to create operator'),
    });
  };

  const reset = () => {
    setUserId('');
    setCreatedKey(null);
    setCopied(false);
  };

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) reset();
  };

  const copyKey = async () => {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button><Plus className="w-4 h-4 mr-1" /> Add Operator</Button>
      </DialogTrigger>
      <DialogContent>
        {createdKey ? (
          <>
            <DialogHeader>
              <DialogTitle>Operator created</DialogTitle>
              <DialogDescription>
                Copy this API key now — it won't be shown again.
              </DialogDescription>
            </DialogHeader>
            <Alert>
              <AlertTitle className="font-mono break-all text-xs">{createdKey}</AlertTitle>
              <AlertDescription>
                Provide this key to the operator out of band (1Password, Slack DM, etc).
              </AlertDescription>
            </Alert>
            <DialogFooter>
              <Button variant="outline" onClick={copyKey}>
                {copied ? <Check className="w-4 h-4 mr-1" /> : <Copy className="w-4 h-4 mr-1" />}
                {copied ? 'Copied' : 'Copy key'}
              </Button>
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={onSubmit}>
            <DialogHeader>
              <DialogTitle>Add operator</DialogTitle>
              <DialogDescription>
                The operator will get a fresh API key for connecting to the gateway.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-2 my-4">
              <Label htmlFor="op-user-id">User ID</Label>
              <Input
                id="op-user-id"
                autoFocus
                placeholder="alice@example.com"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!userId.trim() || create.isPending}>
                {create.isPending ? 'Creating…' : 'Create'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

No commit yet — Tasks 4-6 commit together once the page boots.

---

## Task 5: Permissions panel + Operators table + page wiring

**Files:**
- Create: `src/routes/operators/OperatorsTable.tsx`
- Create: `src/routes/operators/PermissionsPanel.tsx`
- Create: `src/routes/operators/OperatorsPage.tsx` (NEW location)
- Delete: `src/routes/OperatorsPage.tsx` (the placeholder)
- Modify: `src/App.tsx` (update import path)

### 5.1: OperatorsTable.tsx

```tsx
// src/routes/operators/OperatorsTable.tsx
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/data-table/DataTable';
import { useOperators, useDeleteOperator, type Operator } from '@/hooks/useOperators';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';

export function OperatorsTable({
  selectedUserId,
  onSelect,
}: {
  selectedUserId: string | null;
  onSelect: (userId: string) => void;
}) {
  const { data, isLoading } = useOperators();
  const del = useDeleteOperator();

  const columns = useMemo<ColumnDef<Operator>[]>(() => [
    { accessorKey: 'user_id', header: 'User ID' },
    { accessorKey: 'key', header: 'Key', cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
    { accessorKey: 'call_count', header: 'Calls' },
    {
      accessorKey: 'last_active',
      header: 'Last Active',
      cell: (c) => {
        const v = c.getValue<string | null>();
        return v ?? <span className="text-muted-foreground">—</span>;
      },
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={(e) => {
            e.stopPropagation();
            const id = row.original.user_id;
            if (!confirm(`Revoke API access for ${id}? This cannot be undone.`)) return;
            del.mutate(id, {
              onSuccess: () => toast.success(`Operator ${id} revoked`),
              onError: (err) => toast.error(err instanceof Error ? err.message : 'Revoke failed'),
            });
          }}
        >
          <Trash2 className="w-3 h-3" />
        </Button>
      ),
    },
  ], [del]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;

  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      getRowId={(o) => o.user_id}
      onRowClick={(o) => onSelect(o.user_id)}
      selectedRowId={selectedUserId ?? undefined}
      emptyMessage="No operators yet — add one to get started."
      pageSize={25}
    />
  );
}
```

### 5.2: PermissionsPanel.tsx

```tsx
// src/routes/operators/PermissionsPanel.tsx
import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/skeleton';
import { usePermissions, useSetPermission } from '@/hooks/usePermissions';
import { toast } from 'sonner';

export function PermissionsPanel({ userId }: { userId: string | null }) {
  const [filter, setFilter] = useState('');
  const { data, isLoading } = usePermissions(userId);
  const setPerm = useSetPermission(userId ?? '');

  const filtered = useMemo(() => {
    const list = data ?? [];
    const q = filter.toLowerCase();
    return q ? list.filter((p) => p.tool_name.toLowerCase().includes(q)) : list;
  }, [data, filter]);

  if (!userId) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          Select an operator to manage their tool permissions.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Permissions — {userId}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input
          placeholder="Filter tools…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : filtered.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            {filter ? 'No tools match the filter.' : 'No tools registered.'}
          </div>
        ) : (
          <div className="divide-y divide-border max-h-[60vh] overflow-y-auto">
            {filtered.map((p) => (
              <div key={p.tool_name} className="flex items-center justify-between py-2">
                <span className="font-mono text-xs">{p.tool_name}</span>
                <Switch
                  checked={p.enabled}
                  onCheckedChange={(enabled) => {
                    setPerm.mutate(
                      { tool_name: p.tool_name, enabled },
                      {
                        onError: (err) =>
                          toast.error(
                            err instanceof Error ? err.message : 'Failed to update permission',
                          ),
                      },
                    );
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

### 5.3: OperatorsPage.tsx (NEW location)

```tsx
// src/routes/operators/OperatorsPage.tsx
import { useState } from 'react';
import { PageHeader } from '@/components/layout/PageHeader';
import { OperatorsTable } from './OperatorsTable';
import { PermissionsPanel } from './PermissionsPanel';
import { AddOperatorDialog } from './AddOperatorDialog';

export default function OperatorsPage() {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Operators" action={<AddOperatorDialog />} />
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_24rem] gap-6">
        <OperatorsTable selectedUserId={selected} onSelect={setSelected} />
        <PermissionsPanel userId={selected} />
      </div>
    </>
  );
}
```

### 5.4: Delete the placeholder + update App.tsx

```bash
rm remote-gateway/admin-ui/src/routes/OperatorsPage.tsx
```

Then in `src/App.tsx`, change:

```tsx
import OperatorsPage from '@/routes/OperatorsPage';
```

to:

```tsx
import OperatorsPage from '@/routes/operators/OperatorsPage';
```

(That's the only change to App.tsx — leave everything else.)

### 5.5: Verify build

```bash
npm run build
```

Expected: clean. Bundle size will grow further (~30-50kB JS for tanstack-table + the new components).

### 5.6: Commit Tasks 4 + 5 together

```bash
git add remote-gateway/admin-ui/src/routes/operators/ remote-gateway/admin-ui/src/App.tsx
git rm remote-gateway/admin-ui/src/routes/OperatorsPage.tsx
git commit -m "feat(admin-ui): build Operators page (table + permissions panel + add dialog)"
```

---

## Task 6: Manual smoke test (deferred to human)

This task has no commit. List of things to verify when running `./dev.sh`:

- [ ] Navigate to `/admin/operators`. Sidebar highlights "Operators".
- [ ] User table loads (or shows empty state). Header has `+ Add Operator` button.
- [ ] Click `+ Add Operator`. Dialog opens with one input.
- [ ] Submit a new user_id (e.g., `smoke-test-1`). Expected: dialog content swaps to show the full plaintext API key in an Alert with a Copy button. Click Copy. Click Done.
- [ ] Back on the table, the new operator appears as a row (the redacted `key` preview only, never the plaintext).
- [ ] Click the new operator's row. Right side panel populates with the permissions list.
- [ ] Toggle a switch. Refresh — the toggle persists.
- [ ] Click trash icon on the new row. Confirm. Operator vanishes from table; right panel returns to "Select an operator…" if it was selected.
- [ ] Filter input on the permissions panel narrows the tool list.

---

## Task 7: Final verification

- [ ] **Step 1: Run all tests + lint**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
npx tsc -b
npm run build
```

Expected: 11 (Phase 0–1) + 4 (DataTable) + 3 (useOperators) + 3 (usePermissions) = ~21 tests pass. `tsc -b` clean. `npm run build` clean.

- [ ] **Step 2: Python tests still green**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
pytest remote-gateway/tests/test_admin_routes.py -v
```

Expected: 3 pass (no Python changes in this phase).

- [ ] **Step 3: Sanity-check commits**

```bash
git log --oneline | head -10
```

Expected: 4 new commits since the Phase 1 final commit:
1. feat(admin-ui): add reusable DataTable on TanStack Table
2. feat(admin-ui): add useOperators hooks (list/create/delete)
3. feat(admin-ui): add usePermissions hooks with optimistic updates
4. feat(admin-ui): build Operators page (table + permissions panel + add dialog)

---

## Out of Scope for This Phase

- Tools page (Phase 3) — uses the same DataTable + Switch pattern but for global tool toggles.
- Skills / Tool Hints (Phase 4) — DataTable + Dialog form CRUD pattern.
- Tool Calls (Phase 5) — DataTable with filters + Sheet drawer.
- Per-user **edits** beyond create/delete/toggle-permission — out of scope. (No display name change, no key rotation, no role assignment.)
- Bulk permission changes (toggle all-on / all-off for a user). Easy to add later — not in spec.
- Role-based permission templates (e.g. "read-only operator preset"). Not in spec.
- Audit log of who toggled what permission. Not in spec.

---

## Acceptance Criteria

- [ ] `<DataTable>` is reusable: takes columns + data + optional `onRowClick` / `selectedRowId` / `pageSize` / `emptyMessage` / `initialSorting`.
- [ ] DataTable tests cover render, empty state, click handler, selected highlight.
- [ ] `useOperators`, `useCreateOperator`, `useDeleteOperator` work with passing tests.
- [ ] `usePermissions` and `useSetPermission` (with optimistic update + rollback on error) work with passing tests.
- [ ] `/admin/operators` shows a master/detail layout: table on the left, permissions panel on the right.
- [ ] `+ Add Operator` opens a Dialog; on success it reveals the full plaintext key in an `Alert` with a Copy button. Copy button gives visual feedback (Check icon for 2s).
- [ ] Permission toggles update immediately (optimistic) and revert if the PUT fails.
- [ ] Delete confirms via `confirm()` and shows toast on success/error.
- [ ] Filter input narrows the permissions list as you type.
- [ ] No new files outside the file list in this plan.
- [ ] `npm test`, `npx tsc -b`, `npm run build`, `pytest test_admin_routes.py` all pass.
