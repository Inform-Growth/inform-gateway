# Admin UI — Phase 1: Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy "Org Profile" form with a real React Settings page (the first real page of the migration). Validates the Form + Toast + `api.put` + `useQuery` patterns end-to-end so subsequent pages can copy them.

**Architecture:** Single shadcn `Card` per logical section, `react-hook-form` + `zod` for state/validation, TanStack Query hook for fetch + mutation, Sonner toasts for save feedback. Explicit Save button (no auto-save on blur).

**Tech Stack:** React 19, TanStack Query 5, react-hook-form 7, zod 3, shadcn Form/Input/Textarea/Card/Button, Sonner.

**Spec:** `docs/superpowers/specs/2026-05-05-admin-ui-react-port-design.md` (Settings section under "Per-page component plan")
**Phase 0 Plan:** `docs/superpowers/plans/2026-05-05-admin-ui-phase-0-scaffolding.md` (the scaffolding this plan builds on)

---

## Backend API (already exists, do not change)

**GET `/admin/api/org-profile`**
Response shape:
```json
{ "org_id": "default", "initialized": true, "profile": { ... } }
```
The `profile` is a free-form JSON object. The legacy HTML uses these keys:
- `display_name` (string)
- `tone` (string)
- `icp` (string)
- `vocab_rules` (string)

Profile may be `null` or `{}` for an uninitialized org.

**PUT `/admin/api/org-profile`**
Request body: any JSON object (becomes the new profile via `telemetry.update_org_profile(org_id, body)`).
Response shape: `{ "org_id": "default", "profile": { ... } }` (the updated profile).

**Org id selection:** the API derives `org_id` from `?org_id=...` query param if provided, else picks the first initialized org via `_get_primary_org_id(telemetry)`. The Settings page does NOT need to manage org_id — let the backend default.

---

## File Structure

### New files
```
remote-gateway/admin-ui/src/
├── hooks/
│   ├── useOrgProfile.ts        ← TanStack Query hook (get + mutate)
│   └── useOrgProfile.test.ts   ← Vitest tests for the hook
├── routes/
│   └── SettingsPage.tsx        ← REPLACES the Phase 0 placeholder
└── lib/
    └── orgProfileSchema.ts     ← zod schema + TypeScript types
```

### Files modified
- `src/routes/SettingsPage.tsx` — replace the 3-line placeholder with the real form.

That's it. No backend changes, no other frontend files touched.

---

## Task 1: Define the org profile zod schema and types

**Files:**
- Create: `remote-gateway/admin-ui/src/lib/orgProfileSchema.ts`

- [ ] **Step 1: Create the schema**

```ts
// remote-gateway/admin-ui/src/lib/orgProfileSchema.ts
import { z } from 'zod';

/**
 * Shape used by the Settings form. The backend stores org_profile as free-form
 * JSON; this schema is what the UI commits to. Adding a field here = adding a
 * field to the form. The PUT endpoint accepts whatever we send.
 */
export const orgProfileSchema = z.object({
  display_name: z.string().max(120, 'Keep it under 120 characters').default(''),
  tone:         z.string().max(200).default(''),
  icp:          z.string().max(200).default(''),
  vocab_rules:  z.string().max(2000).default(''),
});

export type OrgProfile = z.infer<typeof orgProfileSchema>;

/** Response shape for GET /admin/api/org-profile */
export type OrgProfileResponse = {
  org_id: string;
  initialized: boolean;
  profile: Partial<OrgProfile> | null;
};

/** Response shape for PUT /admin/api/org-profile */
export type OrgProfileUpdateResponse = {
  org_id: string;
  profile: OrgProfile;
};

/** Coerce an unknown server profile to a fully-populated form value. */
export function profileFromServer(p: Partial<OrgProfile> | null | undefined): OrgProfile {
  return orgProfileSchema.parse({
    display_name: p?.display_name ?? '',
    tone:         p?.tone ?? '',
    icp:          p?.icp ?? '',
    vocab_rules:  p?.vocab_rules ?? '',
  });
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npx tsc -b
```

Expected: clean (no output, exit 0).

- [ ] **Step 3: Commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/lib/orgProfileSchema.ts
git commit -m "feat(admin-ui): add org profile zod schema"
```

---

## Task 2: Write the failing useOrgProfile hook tests (TDD)

**Files:**
- Create: `remote-gateway/admin-ui/src/hooks/useOrgProfile.test.ts`

- [ ] **Step 1: Write the tests**

```ts
// remote-gateway/admin-ui/src/hooks/useOrgProfile.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useOrgProfile, useUpdateOrgProfile } from './useOrgProfile';

function wrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('useOrgProfile', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches and normalizes the profile (missing fields → empty strings)', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({
        org_id: 'default',
        initialized: true,
        profile: { display_name: 'Acme' }, // tone/icp/vocab_rules missing
      }),
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useOrgProfile(), { wrapper: wrapper(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      display_name: 'Acme',
      tone: '',
      icp: '',
      vocab_rules: '',
    });
  });

  it('handles null profile (uninitialized org) → all empty strings', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ org_id: 'default', initialized: false, profile: null }),
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useOrgProfile(), { wrapper: wrapper(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      display_name: '', tone: '', icp: '', vocab_rules: '',
    });
  });
});

describe('useUpdateOrgProfile', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('PUTs the profile and invalidates the query', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({
        org_id: 'default',
        profile: { display_name: 'Acme', tone: 'crisp', icp: 'B2B', vocab_rules: '' },
      }),
    });

    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');

    const { result } = renderHook(() => useUpdateOrgProfile(), { wrapper: wrapper(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        display_name: 'Acme', tone: 'crisp', icp: 'B2B', vocab_rules: '',
      });
    });

    // Verify PUT body
    const [, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({
      display_name: 'Acme', tone: 'crisp', icp: 'B2B', vocab_rules: '',
    });

    // Verify cache invalidation
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['orgProfile'] });
  });
});
```

- [ ] **Step 2: Run tests — expect failures**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
```

Expected: tests fail because `useOrgProfile.ts` doesn't exist yet.

- [ ] **Step 3: Commit failing tests**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/hooks/useOrgProfile.test.ts
git commit -m "test(admin-ui): failing tests for useOrgProfile hook"
```

---

## Task 3: Implement useOrgProfile hook

**Files:**
- Create: `remote-gateway/admin-ui/src/hooks/useOrgProfile.ts`

- [ ] **Step 1: Implement**

```ts
// remote-gateway/admin-ui/src/hooks/useOrgProfile.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import {
  type OrgProfile,
  type OrgProfileResponse,
  type OrgProfileUpdateResponse,
  profileFromServer,
} from '@/lib/orgProfileSchema';

const QUERY_KEY = ['orgProfile'] as const;

export function useOrgProfile() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async (): Promise<OrgProfile> => {
      const res = await api.get<OrgProfileResponse>('/admin/api/org-profile');
      return profileFromServer(res.profile);
    },
  });
}

export function useUpdateOrgProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (next: OrgProfile) =>
      api.put<OrgProfileUpdateResponse>('/admin/api/org-profile', next),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
```

- [ ] **Step 2: Run tests — expect pass**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
```

Expected: all 7 tests pass (4 from Phase 0 + 3 new).

- [ ] **Step 3: Commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/hooks/useOrgProfile.ts
git commit -m "feat(admin-ui): add useOrgProfile + useUpdateOrgProfile hooks"
```

---

## Task 4: Build the SettingsPage form

**Files:**
- Modify: `remote-gateway/admin-ui/src/routes/SettingsPage.tsx` (currently a 3-line placeholder)

- [ ] **Step 1: Replace the placeholder with the form**

```tsx
// remote-gateway/admin-ui/src/routes/SettingsPage.tsx
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';
import { PageHeader } from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form';
import { useOrgProfile, useUpdateOrgProfile } from '@/hooks/useOrgProfile';
import { orgProfileSchema, type OrgProfile } from '@/lib/orgProfileSchema';

export default function SettingsPage() {
  const { data, isLoading, isError } = useOrgProfile();
  const update = useUpdateOrgProfile();

  const form = useForm<OrgProfile>({
    resolver: zodResolver(orgProfileSchema),
    defaultValues: { display_name: '', tone: '', icp: '', vocab_rules: '' },
  });

  // Hydrate the form when the query resolves.
  useEffect(() => {
    if (data) form.reset(data);
  }, [data, form]);

  const onSubmit = (values: OrgProfile) => {
    update.mutate(values, {
      onSuccess: () => toast.success('Settings saved'),
      onError: (err) => toast.error(err instanceof Error ? err.message : 'Save failed'),
    });
  };

  if (isError) {
    return (
      <>
        <PageHeader title="Settings" />
        <Card>
          <CardContent className="pt-6 text-destructive">
            Failed to load org profile. Refresh to retry.
          </CardContent>
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Settings"
        action={
          <Button
            type="submit"
            form="settings-form"
            disabled={!form.formState.isDirty || update.isPending}
          >
            {update.isPending ? 'Saving…' : 'Save'}
          </Button>
        }
      />

      {isLoading ? (
        <SettingsSkeleton />
      ) : (
        <Form {...form}>
          <form id="settings-form" onSubmit={form.handleSubmit(onSubmit)} className="space-y-6 max-w-2xl">
            <Card>
              <CardHeader>
                <CardTitle>Org Identity</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="display_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Display Name</FormLabel>
                      <FormControl>
                        <Input placeholder="Acme Corp" {...field} />
                      </FormControl>
                      <FormDescription>How the org appears in the dashboard header.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Voice</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="tone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tone</FormLabel>
                      <FormControl>
                        <Input placeholder="professional, concise" {...field} />
                      </FormControl>
                      <FormDescription>Writing style for agents acting on behalf of this org.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="icp"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>ICP</FormLabel>
                      <FormControl>
                        <Input placeholder="B2B SaaS, 10-200 employees" {...field} />
                      </FormControl>
                      <FormDescription>Ideal customer profile — informs prospecting and outreach skills.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="vocab_rules"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Vocabulary Rules</FormLabel>
                      <FormControl>
                        <Textarea
                          rows={5}
                          placeholder="Always say 'prospect' not 'lead'…"
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>One rule per line. Applied to all generated text.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>
          </form>
        </Form>
      )}
    </>
  );
}

function SettingsSkeleton() {
  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader><Skeleton className="h-5 w-32" /></CardHeader>
        <CardContent><Skeleton className="h-9 w-full" /></CardContent>
      </Card>
      <Card>
        <CardHeader><Skeleton className="h-5 w-24" /></CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm run build
```

Expected: clean. Bundle size will grow ~15-25kB due to react-hook-form + zod chunks not previously imported. If TypeScript complains about a shadcn `Form` re-export, check that `src/components/ui/form.tsx` exists and exports `Form`, `FormField`, `FormItem`, etc. — those were installed in Phase 0.

- [ ] **Step 3: Commit**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
git add remote-gateway/admin-ui/src/routes/SettingsPage.tsx
git commit -m "feat(admin-ui): build Settings page with org profile form"
```

---

## Task 5: Manual smoke test

This task has no commit — it's a verification pass.

- [ ] **Step 1: Start the dev environment**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
cp -n remote-gateway/admin-ui/.env.example remote-gateway/admin-ui/.env.local 2>/dev/null || true
./dev.sh
```

The script blocks in foreground; use a separate terminal for the rest of this task.

- [ ] **Step 2: Verify the page renders**

Open `http://localhost:5173/admin/settings` in a browser.

Expected:
- Page loads with "Settings" in the page header
- Two cards visible: "Org Identity" and "Voice"
- Four fields populated from the current org profile (or empty if uninitialized)
- "Save" button in the page header is **disabled** when no changes have been made

If any of these fail, debug before continuing.

- [ ] **Step 3: Verify save works**

1. Edit the "Display Name" field — observe the Save button becomes **enabled**.
2. Click Save.
3. Expected: a toast appears in the top-right reading "Settings saved", and the Save button returns to disabled (form is no longer dirty after the cache invalidates and re-hydrates).
4. Refresh the page (`Cmd-R`). Expected: the new value persists.

- [ ] **Step 4: Verify validation**

1. Paste 200 characters into "Display Name" (over the 120-char limit).
2. Try to save. Expected: an inline error message reading "Keep it under 120 characters" appears beneath the field; no toast; no API call.

- [ ] **Step 5: Verify error handling**

1. Stop the Python gateway (Ctrl-C in the dev.sh terminal). Vite dev server keeps running.
2. Edit a field, click Save. Expected: an error toast appears (the proxy returns 502 from a dead backend; `api.put` throws `ApiError`).
3. Restart `./dev.sh`.

- [ ] **Step 6: Stop dev.sh**

Ctrl-C in the dev.sh terminal — both Python and Vite should exit cleanly.

---

## Task 6: Final verification

- [ ] **Step 1: Run all tests**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template/remote-gateway/admin-ui
npm test
npx tsc -b
npm run build
```

All three commands should succeed. Test count should be 7 (4 from Phase 0 + 3 new). Bundle sizes should be similar to Phase 0 plus react-hook-form + zod (~20-30kB).

- [ ] **Step 2: Run Python tests**

```bash
cd /Users/jaronsander/main/inform/inform-gateway/.worktrees/gateway-template
pytest remote-gateway/tests/test_admin_routes.py -v
```

Expected: 3 pass (no Python changes in this phase, just sanity check).

- [ ] **Step 3: Sanity-check commits**

```bash
git log --oneline | head -8
```

Expected: 4 new commits since the Phase 0 final commit:
1. feat(admin-ui): add org profile zod schema
2. test(admin-ui): failing tests for useOrgProfile hook
3. feat(admin-ui): add useOrgProfile + useUpdateOrgProfile hooks
4. feat(admin-ui): build Settings page with org profile form

---

## Out of Scope for This Phase

- Operators page, Tools page, Skills/Tool Hints, Tool Calls, Tasks, Dashboard — separate plans (Phases 2-7).
- Backend changes to `/admin/api/org-profile` — the API stays exactly as-is.
- Multiple-org support in the UI — single org assumed (backend picks the primary).
- Auto-save on blur — explicit Save button only (per spec).
- Adding new profile fields beyond the four in the legacy form — keep parity, expand later.

---

## Acceptance Criteria

- [ ] `useOrgProfile` and `useUpdateOrgProfile` hooks exist and have passing tests.
- [ ] `/admin/settings` renders the form with two Cards (Org Identity, Voice).
- [ ] Form hydrates from the backend on load.
- [ ] Save button disabled when form is clean, enabled when dirty, shows "Saving…" during mutation.
- [ ] Successful save shows a green toast; failed save shows a red toast.
- [ ] Field-level validation surfaces inline via shadcn `FormMessage`.
- [ ] Loading state uses `Skeleton`s, not "Loading…" text.
- [ ] No new files outside the file list in this plan.
- [ ] `npm test`, `npx tsc -b`, `npm run build`, and `pytest remote-gateway/tests/test_admin_routes.py` all pass.
