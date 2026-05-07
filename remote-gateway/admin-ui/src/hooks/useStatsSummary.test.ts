import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useStatsSummary } from './useStatsSummary';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useStatsSummary', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('extracts the summary block', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        tools: [{ name: 'a', call_count: 100, avg_duration_ms: 50 }],
        summary: { total_calls: 100, total_tools_seen: 1, high_error_rate: ['x'] },
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useStatsSummary(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      total_calls: 100, total_tools_seen: 1, high_error_rate: ['x'],
    });
  });

  it('returns zeroed defaults when telemetry returned an error shape', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ error: 'telemetry disabled', tools: [] }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useStatsSummary(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      total_calls: 0, total_tools_seen: 0, high_error_rate: [],
    });
  });
});
