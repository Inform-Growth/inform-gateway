# Admin UI — Phase 4: Skills + Tool Hints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy "Skills" and "Tool Hints" tabs with two real pages that share one CRUD pattern: DataTable + Dialog + react-hook-form/zod. They're done in one phase because they share the entire pattern; only the schema and the API verbs differ.

**Architecture:** For each page, a top-level page component composes a DataTable (Phase 2 reuse) with row actions, plus a single Dialog component that handles both Create and Edit modes (driven by an "editing" prop — null means create, an object means edit). Sonner toasts for save/delete feedback. **System skills are immutable** — the backend rejects PUT/DELETE on `is_system: 1` rows, and the UI must hide the Edit/Delete actions on those rows.

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md`
**Phase 2 Plan:** `2026-05-06-admin-ui-phase-2-operators.md` (DataTable lives there)
**Phase 1 Plan:** `2026-05-06-admin-ui-phase-1-settings.md` (Form + Toast pattern reference)

---

## Backend API (already exists, do not change)

### Skills

Each skill (DB row): `{ id, name, description, prompt_template, is_system, created_by, created_at, updated_at }`. `is_system` is `0|1` from SQLite — treat both `0` / `1` and `false` / `true` as the same.

| Verb / Path | Body | Returns |
|---|---|---|
| GET `/admin/api/skills` | — | `Skill[]` |
| POST `/admin/api/skills` | `{name, description, prompt_template}` | 201 `Skill` |
| PUT `/admin/api/skills/{name}` | `{description?, prompt_template?}` | `Skill` (200) or 404 if not found OR is system |
| DELETE `/admin/api/skills/{name}` | — | `{deleted: name}` (200) or 404 if not found OR is system |

**System skills are immutable.** The backend returns 404 with `error: "skill 'X' not found or is a system skill"` when you try to PUT/DELETE one. Hide the Edit/Delete actions for `is_system` rows in the UI.

### Tool Hints

Each hint: `{ tool_name, interpretation_hint, usage_rules, data_sensitivity }`. `tool_name` is the primary key. `data_sensitivity` defaults to `"internal"` server-side.

| Verb / Path | Body | Returns |
|---|---|---|
| GET `/admin/api/tool-hints` | — | `Hint[]` |
| PUT `/admin/api/tool-hints/{tool_name}` | `{interpretation_hint?, usage_rules?, data_sensitivity?}` | `Hint` |

**No POST and no DELETE.** PUT is upsert: same Dialog handles both "new tool name" and "edit existing tool's hint." There's no UI-side delete; if the user wants to clear a hint, they edit it to empty strings.

---

## File Structure

### New files
```
remote-gateway/admin-ui/src/
├── hooks/
│   ├── useSkills.ts              ← list / create / update / delete
│   ├── useSkills.test.ts
│   ├── useToolHints.ts           ← list / upsert
│   └── useToolHints.test.ts
├── lib/
│   ├── skillSchema.ts            ← zod schema for the Skill form
│   └── toolHintSchema.ts
└── routes/
    ├── skills/
    │   ├── SkillsPage.tsx        ← REPLACES placeholder; orchestrates table + dialog
    │   ├── SkillsTable.tsx
    │   └── SkillDialog.tsx       ← create + edit (single dialog driven by `editing`)
    └── tool-hints/
        ├── ToolHintsPage.tsx     ← REPLACES placeholder
        ├── ToolHintsTable.tsx
        └── ToolHintDialog.tsx
```

### Files modified
- Move `src/routes/SkillsPage.tsx` → `src/routes/skills/SkillsPage.tsx`
- Move `src/routes/ToolHintsPage.tsx` → `src/routes/tool-hints/ToolHintsPage.tsx`
- `src/App.tsx` — update both import paths

---

## Task 1: Skills hooks (TDD)

**Files:** `src/hooks/useSkills.ts`, `src/hooks/useSkills.test.ts`, `src/lib/skillSchema.ts`

- [ ] **Step 1: zod schema**

```ts
// src/lib/skillSchema.ts
import { z } from 'zod';

export const skillSchema = z.object({
  name: z
    .string()
    .min(1, 'Required')
    .max(80, 'Keep it under 80 chars')
    .regex(/^[a-z0-9_]+$/, 'lowercase letters, digits, and underscores only'),
  description: z.string().min(1, 'Required').max(200),
  prompt_template: z.string().min(1, 'Required').max(8000),
});

export type SkillInput = z.infer<typeof skillSchema>;

export type Skill = SkillInput & {
  id: string;
  is_system: 0 | 1 | boolean;
  created_by: string | null;
  created_at: string | number;
  updated_at: string | number;
};

export const isSystemSkill = (s: Skill) => s.is_system === 1 || s.is_system === true;
```

- [ ] **Step 2: Failing tests**

```ts
// src/hooks/useSkills.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useSkills, useCreateSkill, useUpdateSkill, useDeleteSkill } from './useSkills';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useSkills', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches the list', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => [
        { id: '1', name: 'a', description: 'd', prompt_template: 't',
          is_system: 0, created_by: null, created_at: 1, updated_at: 1 },
      ],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useSkills(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});

describe('useCreateSkill', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('POSTs and invalidates', async () => {
    (fetch as any).mockResolvedValue({
      ok: true, json: async () => ({ id: '2', name: 'b', description: 'd',
        prompt_template: 't', is_system: 0, created_by: null,
        created_at: 1, updated_at: 1 }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const inv = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useCreateSkill(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'b', description: 'd', prompt_template: 't' });
    });
    const [, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ name: 'b', description: 'd', prompt_template: 't' });
    expect(inv).toHaveBeenCalledWith({ queryKey: ['skills'] });
  });
});

describe('useUpdateSkill', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('PUTs description+prompt_template only (name is the path)', async () => {
    (fetch as any).mockResolvedValue({
      ok: true, json: async () => ({ id: '1', name: 'a', description: 'd2',
        prompt_template: 't2', is_system: 0, created_by: null,
        created_at: 1, updated_at: 2 }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { result } = renderHook(() => useUpdateSkill(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        name: 'a', description: 'd2', prompt_template: 't2',
      });
    });
    const [url, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('PUT');
    expect(url).toContain('/admin/api/skills/a');
    expect(JSON.parse(init.body)).toEqual({ description: 'd2', prompt_template: 't2' });
  });
});

describe('useDeleteSkill', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('DELETEs by name and invalidates', async () => {
    (fetch as any).mockResolvedValue({
      ok: true, json: async () => ({ deleted: 'a' }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const inv = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useDeleteSkill(), { wrapper: wrap(qc) });
    await act(async () => { await result.current.mutateAsync('a'); });
    const [url, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('DELETE');
    expect(url).toContain('/admin/api/skills/a');
    expect(inv).toHaveBeenCalledWith({ queryKey: ['skills'] });
  });
});
```

- [ ] **Step 3: Implement hooks**

```ts
// src/hooks/useSkills.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Skill, SkillInput } from '@/lib/skillSchema';

const QK = ['skills'] as const;

export function useSkills() {
  return useQuery({
    queryKey: QK,
    queryFn: () => api.get<Skill[]>('/admin/api/skills'),
  });
}

export function useCreateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SkillInput) => api.post<Skill>('/admin/api/skills', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}

export function useUpdateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, description, prompt_template }: SkillInput) =>
      api.put<Skill>(`/admin/api/skills/${encodeURIComponent(name)}`, {
        description,
        prompt_template,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.delete<{ deleted: string }>(`/admin/api/skills/${encodeURIComponent(name)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
```

Expected: 4 new tests pass.

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/hooks/useSkills.ts remote-gateway/admin-ui/src/hooks/useSkills.test.ts remote-gateway/admin-ui/src/lib/skillSchema.ts
git commit -m "feat(admin-ui): add useSkills hooks + zod schema"
```

---

## Task 2: Tool Hints hooks (TDD)

**Files:** `src/hooks/useToolHints.ts`, `src/hooks/useToolHints.test.ts`, `src/lib/toolHintSchema.ts`

- [ ] **Step 1: zod schema**

```ts
// src/lib/toolHintSchema.ts
import { z } from 'zod';

export const SENSITIVITIES = ['public', 'internal', 'sensitive'] as const;

export const toolHintSchema = z.object({
  tool_name: z.string().min(1, 'Required').max(120),
  interpretation_hint: z.string().max(2000).default(''),
  usage_rules: z.string().max(2000).default(''),
  data_sensitivity: z.enum(SENSITIVITIES).default('internal'),
});

export type ToolHintInput = z.infer<typeof toolHintSchema>;
export type ToolHint = ToolHintInput;
```

- [ ] **Step 2: Failing tests**

```ts
// src/hooks/useToolHints.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useToolHints, useUpsertToolHint } from './useToolHints';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useToolHints', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches the list', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => [{
        tool_name: 'attio__search', interpretation_hint: 'be terse',
        usage_rules: '', data_sensitivity: 'internal',
      }],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useToolHints(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});

describe('useUpsertToolHint', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('PUTs to the tool_name path with the body fields', async () => {
    (fetch as any).mockResolvedValue({
      ok: true, json: async () => ({
        tool_name: 'attio__search', interpretation_hint: 'be terse',
        usage_rules: 'no PII', data_sensitivity: 'sensitive',
      }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const inv = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useUpsertToolHint(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        tool_name: 'attio__search', interpretation_hint: 'be terse',
        usage_rules: 'no PII', data_sensitivity: 'sensitive',
      });
    });
    const [url, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('PUT');
    expect(url).toContain('/admin/api/tool-hints/attio__search');
    expect(JSON.parse(init.body)).toEqual({
      interpretation_hint: 'be terse',
      usage_rules: 'no PII',
      data_sensitivity: 'sensitive',
    });
    expect(inv).toHaveBeenCalledWith({ queryKey: ['toolHints'] });
  });
});
```

- [ ] **Step 3: Implement**

```ts
// src/hooks/useToolHints.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ToolHint, ToolHintInput } from '@/lib/toolHintSchema';

const QK = ['toolHints'] as const;

export function useToolHints() {
  return useQuery({
    queryKey: QK,
    queryFn: () => api.get<ToolHint[]>('/admin/api/tool-hints'),
  });
}

export function useUpsertToolHint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ tool_name, interpretation_hint, usage_rules, data_sensitivity }: ToolHintInput) =>
      api.put<ToolHint>(`/admin/api/tool-hints/${encodeURI(tool_name)}`, {
        interpretation_hint,
        usage_rules,
        data_sensitivity,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
```

Expected: 2 new tests pass.

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/hooks/useToolHints.ts remote-gateway/admin-ui/src/hooks/useToolHints.test.ts remote-gateway/admin-ui/src/lib/toolHintSchema.ts
git commit -m "feat(admin-ui): add useToolHints hooks + zod schema"
```

---

## Task 3: SkillDialog (create + edit in one)

**File:** `src/routes/skills/SkillDialog.tsx`

The single Dialog handles both modes:
- `editing` is `null` → Create. Form starts empty. Submits via `useCreateSkill`. The `name` field is editable.
- `editing` is a `Skill` → Edit. Form pre-populates. Submits via `useUpdateSkill`. The `name` field is **read-only** (it's the URL path; renaming is not supported by the API).

```tsx
// src/routes/skills/SkillDialog.tsx
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form';
import { skillSchema, type Skill, type SkillInput } from '@/lib/skillSchema';
import { useCreateSkill, useUpdateSkill } from '@/hooks/useSkills';

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null → create mode; Skill → edit mode. */
  editing: Skill | null;
};

const EMPTY: SkillInput = { name: '', description: '', prompt_template: '' };

export function SkillDialog({ open, onOpenChange, editing }: Props) {
  const create = useCreateSkill();
  const update = useUpdateSkill();
  const isEdit = editing !== null;

  const form = useForm<SkillInput>({
    resolver: zodResolver(skillSchema),
    defaultValues: EMPTY,
  });

  // Hydrate when editing changes; reset to empty when switching to create.
  useEffect(() => {
    form.reset(
      editing
        ? { name: editing.name, description: editing.description, prompt_template: editing.prompt_template }
        : EMPTY,
    );
  }, [editing, form]);

  const onSubmit = (values: SkillInput) => {
    const mut = isEdit ? update : create;
    mut.mutate(values, {
      onSuccess: () => {
        toast.success(isEdit ? 'Skill updated' : 'Skill created');
        onOpenChange(false);
      },
      onError: (err) => toast.error(err instanceof Error ? err.message : 'Save failed'),
    });
  };

  const pending = create.isPending || update.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${editing.name}` : 'New Skill'}</DialogTitle>
          <DialogDescription>
            Skills are prompt templates rendered at <code>run_skill</code> call time. Use{' '}
            <code>{'{variable}'}</code> placeholders for runtime substitution.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input
                      readOnly={isEdit}
                      placeholder="daily_briefing"
                      className={isEdit ? 'bg-muted text-muted-foreground' : undefined}
                      {...field}
                    />
                  </FormControl>
                  {isEdit && <FormDescription>Renaming requires recreating the skill.</FormDescription>}
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl><Input {...field} /></FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="prompt_template"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Prompt Template</FormLabel>
                  <FormControl>
                    <Textarea rows={8} className="font-mono text-xs" {...field} />
                  </FormControl>
                  <FormDescription>
                    Use <code>{'{variable}'}</code> placeholders, filled by the caller of <code>run_skill</code>.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                {pending ? 'Saving…' : isEdit ? 'Save' : 'Create'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
```

No commit yet — combined with Tasks 4-5.

---

## Task 4: SkillsTable + SkillsPage

**Files:** `src/routes/skills/SkillsTable.tsx`, `src/routes/skills/SkillsPage.tsx`

### SkillsTable.tsx

```tsx
// src/routes/skills/SkillsTable.tsx
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { DataTable } from '@/components/data-table/DataTable';
import { useSkills, useDeleteSkill } from '@/hooks/useSkills';
import { isSystemSkill, type Skill } from '@/lib/skillSchema';
import { toast } from 'sonner';

export function SkillsTable({ onEdit }: { onEdit: (s: Skill) => void }) {
  const { data, isLoading } = useSkills();
  const del = useDeleteSkill();

  const columns = useMemo<ColumnDef<Skill>[]>(() => [
    {
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <span className="font-mono text-xs flex items-center gap-2">
          {row.original.name}
          {isSystemSkill(row.original) && (
            <Badge variant="secondary" className="gap-1">
              <ShieldCheck className="w-3 h-3" /> system
            </Badge>
          )}
        </span>
      ),
    },
    { accessorKey: 'description', header: 'Description' },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => {
        const s = row.original;
        if (isSystemSkill(s)) {
          return <span className="text-xs text-muted-foreground">read-only</span>;
        }
        return (
          <div className="flex justify-end gap-1">
            <Button variant="ghost" size="icon-sm" onClick={(e) => { e.stopPropagation(); onEdit(s); }}>
              <Pencil className="w-3 h-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={(e) => {
                e.stopPropagation();
                if (!confirm(`Delete skill "${s.name}"? This cannot be undone.`)) return;
                del.mutate(s.name, {
                  onSuccess: () => toast.success(`Skill ${s.name} deleted`),
                  onError: (err) =>
                    toast.error(err instanceof Error ? err.message : 'Delete failed'),
                });
              }}
            >
              <Trash2 className="w-3 h-3" />
            </Button>
          </div>
        );
      },
    },
  ], [del, onEdit]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      getRowId={(s) => s.name}
      onRowClick={(s) => !isSystemSkill(s) && onEdit(s)}
      emptyMessage="No skills yet — click + New Skill to create your first."
      pageSize={50}
    />
  );
}
```

### SkillsPage.tsx

```tsx
// src/routes/skills/SkillsPage.tsx
import { useState } from 'react';
import { Plus } from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/button';
import { SkillsTable } from './SkillsTable';
import { SkillDialog } from './SkillDialog';
import type { Skill } from '@/lib/skillSchema';

export default function SkillsPage() {
  const [editing, setEditing] = useState<Skill | null>(null);
  const [open, setOpen] = useState(false);

  const openCreate = () => { setEditing(null); setOpen(true); };
  const openEdit = (s: Skill) => { setEditing(s); setOpen(true); };

  return (
    <>
      <PageHeader
        title="Skills"
        action={
          <Button onClick={openCreate}>
            <Plus className="w-4 h-4 mr-1" /> New Skill
          </Button>
        }
      />
      <SkillsTable onEdit={openEdit} />
      <SkillDialog open={open} onOpenChange={setOpen} editing={editing} />
    </>
  );
}
```

No commit yet — combined with Tasks 5-7.

---

## Task 5: ToolHintDialog + ToolHintsTable + ToolHintsPage

Same pattern, different schema. Hints have no DELETE (the upsert IS the create-or-edit operation).

### ToolHintDialog.tsx

```tsx
// src/routes/tool-hints/ToolHintDialog.tsx
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form';
import {
  toolHintSchema, type ToolHint, type ToolHintInput, SENSITIVITIES,
} from '@/lib/toolHintSchema';
import { useUpsertToolHint } from '@/hooks/useToolHints';

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: ToolHint | null;  // null → new tool name, ToolHint → edit existing
};

const EMPTY: ToolHintInput = {
  tool_name: '', interpretation_hint: '', usage_rules: '', data_sensitivity: 'internal',
};

export function ToolHintDialog({ open, onOpenChange, editing }: Props) {
  const upsert = useUpsertToolHint();
  const isEdit = editing !== null;

  const form = useForm<ToolHintInput>({
    resolver: zodResolver(toolHintSchema),
    defaultValues: EMPTY,
  });

  useEffect(() => {
    form.reset(editing ?? EMPTY);
  }, [editing, form]);

  const onSubmit = (values: ToolHintInput) => {
    upsert.mutate(values, {
      onSuccess: () => {
        toast.success(isEdit ? 'Hint updated' : 'Hint created');
        onOpenChange(false);
      },
      onError: (err) => toast.error(err instanceof Error ? err.message : 'Save failed'),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit hint — ${editing.tool_name}` : 'New Tool Hint'}</DialogTitle>
          <DialogDescription>
            Hints are injected into tool responses to guide agent interpretation.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="tool_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tool Name</FormLabel>
                  <FormControl>
                    <Input
                      readOnly={isEdit}
                      className={isEdit ? 'bg-muted text-muted-foreground font-mono text-xs' : 'font-mono text-xs'}
                      placeholder="attio__search_records"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="interpretation_hint"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Interpretation Hint</FormLabel>
                  <FormControl><Textarea rows={3} {...field} /></FormControl>
                  <FormDescription>How should the agent read this tool's output?</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="usage_rules"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Usage Rules</FormLabel>
                  <FormControl><Textarea rows={3} {...field} /></FormControl>
                  <FormDescription>When and how to call this tool.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="data_sensitivity"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Data Sensitivity</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {SENSITIVITIES.map((s) => (
                        <SelectItem key={s} value={s}>{s}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={upsert.isPending}>
                {upsert.isPending ? 'Saving…' : isEdit ? 'Save' : 'Create'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
```

### ToolHintsTable.tsx

```tsx
// src/routes/tool-hints/ToolHintsTable.tsx
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { DataTable } from '@/components/data-table/DataTable';
import { useToolHints } from '@/hooks/useToolHints';
import type { ToolHint } from '@/lib/toolHintSchema';

const sensitivityVariant: Record<string, 'default' | 'secondary' | 'destructive'> = {
  public: 'secondary',
  internal: 'default',
  sensitive: 'destructive',
};

export function ToolHintsTable({ onEdit }: { onEdit: (h: ToolHint) => void }) {
  const { data, isLoading } = useToolHints();

  const columns = useMemo<ColumnDef<ToolHint>[]>(() => [
    { accessorKey: 'tool_name', header: 'Tool',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
    {
      accessorKey: 'interpretation_hint',
      header: 'Interpretation',
      cell: (c) => {
        const v = c.getValue<string>();
        return v ? <span className="text-sm">{v}</span> : <span className="text-muted-foreground">—</span>;
      },
    },
    {
      accessorKey: 'data_sensitivity',
      header: 'Sensitivity',
      cell: (c) => {
        const v = c.getValue<string>();
        return <Badge variant={sensitivityVariant[v] ?? 'default'}>{v}</Badge>;
      },
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <div className="flex justify-end">
          <Button variant="ghost" size="icon-sm" onClick={(e) => { e.stopPropagation(); onEdit(row.original); }}>
            <Pencil className="w-3 h-3" />
          </Button>
        </div>
      ),
    },
  ], [onEdit]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      getRowId={(h) => h.tool_name}
      onRowClick={onEdit}
      emptyMessage="No tool hints yet. Add one to guide agent interpretation."
      pageSize={50}
    />
  );
}
```

### ToolHintsPage.tsx

```tsx
// src/routes/tool-hints/ToolHintsPage.tsx
import { useState } from 'react';
import { Plus } from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/button';
import { ToolHintsTable } from './ToolHintsTable';
import { ToolHintDialog } from './ToolHintDialog';
import type { ToolHint } from '@/lib/toolHintSchema';

export default function ToolHintsPage() {
  const [editing, setEditing] = useState<ToolHint | null>(null);
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Tool Hints"
        action={
          <Button onClick={() => { setEditing(null); setOpen(true); }}>
            <Plus className="w-4 h-4 mr-1" /> Add Hint
          </Button>
        }
      />
      <ToolHintsTable onEdit={(h) => { setEditing(h); setOpen(true); }} />
      <ToolHintDialog open={open} onOpenChange={setOpen} editing={editing} />
    </>
  );
}
```

No commit yet — combined with Task 6.

---

## Task 6: Delete placeholders, update App.tsx, build, commit Tasks 3-6 together

```bash
git rm remote-gateway/admin-ui/src/routes/SkillsPage.tsx
git rm remote-gateway/admin-ui/src/routes/ToolHintsPage.tsx
```

In `src/App.tsx`, change:

```tsx
import SkillsPage from '@/routes/SkillsPage';
import ToolHintsPage from '@/routes/ToolHintsPage';
```

to:

```tsx
import SkillsPage from '@/routes/skills/SkillsPage';
import ToolHintsPage from '@/routes/tool-hints/ToolHintsPage';
```

Verify build:

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm run build
```

Expected: clean.

Commit:

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/routes/skills/ remote-gateway/admin-ui/src/routes/tool-hints/ remote-gateway/admin-ui/src/App.tsx
git commit -m "feat(admin-ui): build Skills + Tool Hints CRUD pages"
```

---

## Task 7: Manual smoke (deferred)

When `./dev.sh` is running:

**Skills (`/admin/settings → /admin/skills`):**
- [ ] Table loads (or shows empty state).
- [ ] System skills (if any) show a "system" badge and "read-only" label instead of action buttons.
- [ ] Click `+ New Skill`. Dialog opens, all fields empty.
- [ ] Try submitting an empty form — see inline `Required` errors.
- [ ] Try a name with a space — see "lowercase letters, digits, and underscores only".
- [ ] Submit a valid skill. Toast appears. Dialog closes. Row appears in table.
- [ ] Click the pencil on a non-system row. Dialog opens, fields pre-populated, name field grayed out and read-only.
- [ ] Edit description, save. Toast. Table reflects the change.
- [ ] Click trash on a non-system row. Confirm. Toast. Row vanishes.
- [ ] Try editing a system skill via the URL — UI hides the actions, so this requires manual API hacking; just confirm the UI guards are present.

**Tool Hints (`/admin/tool-hints`):**
- [ ] Table loads with three columns: Tool, Interpretation, Sensitivity.
- [ ] Click `+ Add Hint`. Dialog opens with a Select for sensitivity (3 options).
- [ ] Submit a hint with all four fields. Toast. Row appears.
- [ ] Click pencil. Dialog pre-populates; tool_name is read-only.
- [ ] Change sensitivity to `sensitive`. Save. Badge in the table updates color (destructive variant).

---

## Task 8: Final verification

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test           # expect 21 baseline + 4 (skills) + 2 (hints) = 27
npx tsc -b
npm run build
cd ../..
pytest remote-gateway/tests/test_admin_routes.py -v
```

```bash
git log --oneline | head -5
```

Expected: 3 new commits since Phase 3:
1. feat(admin-ui): add useSkills hooks + zod schema
2. feat(admin-ui): add useToolHints hooks + zod schema
3. feat(admin-ui): build Skills + Tool Hints CRUD pages

---

## Out of Scope

- Renaming a skill (the API doesn't support it; rename = delete + recreate).
- Deleting a hint (the API doesn't expose DELETE; clearing is "edit to empty strings").
- Skill versioning / history. Not in spec.
- Test-running a skill from the UI. Not in spec — agents call `run_skill` directly.
- Tool Hint preview ("show me what this hint looks like injected into a response"). Future polish.
- Importing/exporting skills as YAML. Not in spec.
- A confirmation `AlertDialog` for delete (using `confirm()` for now per Phase 2 precedent).

---

## Acceptance Criteria

- [ ] `useSkills`, `useCreateSkill`, `useUpdateSkill`, `useDeleteSkill` all exist with passing tests.
- [ ] `useToolHints`, `useUpsertToolHint` exist with passing tests.
- [ ] `/admin/skills` shows a table; system skills are visually distinct and read-only.
- [ ] `+ New Skill` and pencil edit both reuse `<SkillDialog>`; `name` is read-only in edit mode.
- [ ] zod validation for `name` enforces `^[a-z0-9_]+$` and surfaces inline.
- [ ] Successful save shows toast and closes dialog; failed save shows toast and keeps dialog open.
- [ ] Delete uses `confirm()` and shows toast.
- [ ] `/admin/tool-hints` mirrors the Skills UX, minus delete.
- [ ] `data_sensitivity` Select uses the three values; the column renders a colored Badge.
- [ ] No new files outside the file list in this plan.
- [ ] All tests + tsc + build + Python tests pass.
