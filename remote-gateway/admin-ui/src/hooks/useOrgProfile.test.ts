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
