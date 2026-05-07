import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useToolHints, useUpsertToolHint } from './useToolHints';

const wrap = (qc: QueryClient) =>
  function W({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };

describe('useToolHints', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches the list', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => [
        {
          tool_name: 'attio__search',
          interpretation_hint: 'be terse',
          usage_rules: '',
          data_sensitivity: 'internal',
        },
      ],
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
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        tool_name: 'attio__search',
        interpretation_hint: 'be terse',
        usage_rules: 'no PII',
        data_sensitivity: 'sensitive',
      }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const inv = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useUpsertToolHint(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        tool_name: 'attio__search',
        interpretation_hint: 'be terse',
        usage_rules: 'no PII',
        data_sensitivity: 'sensitive',
      });
    });
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
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
