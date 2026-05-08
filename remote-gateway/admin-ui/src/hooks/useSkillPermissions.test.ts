import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useSkillPermissions, useSetSkillPermission } from './useSkillPermissions';

function wrapper(qc: QueryClient) {
  return function W({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('useSkillPermissions', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches skill permissions for a user', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({
        user_id: 'alice',
        permissions: [
          { skill_name: 'briefing', enabled: true },
          { skill_name: 'recap',    enabled: false },
        ],
      }),
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useSkillPermissions('alice'), { wrapper: wrapper(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
  });

  it('does not fetch when user_id is null (disabled query)', () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => useSkillPermissions(null), { wrapper: wrapper(qc) });
    expect(result.current.fetchStatus).toBe('idle');
    expect((fetch as any).mock?.calls?.length ?? 0).toBe(0);
  });
});

describe('useSetSkillPermission', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('PUTs the new value and optimistically updates cache', async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, user_id: 'alice', skill_name: 'briefing', enabled: false }),
    });

    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    qc.setQueryData(['skill-permissions', 'alice'], [
      { skill_name: 'briefing', enabled: true },
      { skill_name: 'recap',    enabled: false },
    ]);

    const { result } = renderHook(() => useSetSkillPermission('alice'), { wrapper: wrapper(qc) });

    await act(async () => {
      await result.current.mutateAsync({ skill_name: 'briefing', enabled: false });
    });

    const cached = qc.getQueryData<{ skill_name: string; enabled: boolean }[]>(
      ['skill-permissions', 'alice'],
    );
    expect(cached?.find((p) => p.skill_name === 'briefing')?.enabled).toBe(false);

    const [url, init] = (fetch as any).mock.calls[0];
    expect(init.method).toBe('PUT');
    expect(url).toContain('/admin/api/skill-permissions/alice/briefing');
    expect(JSON.parse(init.body)).toEqual({ enabled: false });
  });
});
