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
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('admin_token', 'tkn');
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
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('admin_token', 'tkn');
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
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('admin_token', 'tkn');
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
