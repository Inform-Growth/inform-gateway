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
