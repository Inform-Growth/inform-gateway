import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useToolStats } from './useToolStats';

function wrapper(qc: QueryClient) {
  return function W({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe('useToolStats', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches stats and returns the tools array', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        tools: [
          {
            name: 'attio__search',
            call_count: 42,
            error_count: 0,
            error_rate: '0.0%',
            last_called: '2026-05-06T14:30Z',
            avg_duration_ms: 120,
            max_duration_ms: 300,
            avg_response_size: 5_000,
            max_response_size: 12_000,
            avg_input_size: 200,
            max_input_size: 800,
          },
        ],
        summary: { total_calls: 42 },
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useToolStats(), { wrapper: wrapper(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].name).toBe('attio__search');
  });

  it('returns empty array if telemetry returned an error shape', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ error: 'telemetry disabled', tools: [] }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useToolStats(), { wrapper: wrapper(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
