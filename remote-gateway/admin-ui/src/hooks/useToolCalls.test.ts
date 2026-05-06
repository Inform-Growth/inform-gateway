import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useToolCalls } from './useToolCalls';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useToolCalls', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('passes limit + offset query params', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => [],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useToolCalls({ limit: 25, offset: 50 }), { wrapper: wrap(qc) });
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('limit=25');
    expect(url).toContain('offset=50');
  });

  it('omits empty filter params and includes provided ones', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => [],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(
      () => useToolCalls({
        limit: 100, offset: 0, tool: 'attio__search', user: '', success: 'false',
      }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('tool=attio__search');
    expect(url).toContain('success=false');
    expect(url).not.toContain('user=');
  });

  it('returns the array as data', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => [{
        id: 1, tool_name: 'x', called_at: '2026-05-06T14:00:00Z', duration_ms: 100,
        success: true, error_type: null, error_message: null, user_id: 'u',
        request_id: 'r', response_size: 1, input_size: 2, input_body: null,
        response_preview: null, task_id: null,
      }],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useToolCalls({ limit: 100, offset: 0 }), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});
