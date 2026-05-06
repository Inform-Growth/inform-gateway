import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useTasks } from './useTasks';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useTasks', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches and unwraps the tasks array from the envelope', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        org_id: 'default',
        tasks: [{
          task_id: 't1', user_id: 'u', org_id: 'default', goal: 'do thing',
          steps: null, status: 'active', outcome: null,
          created_at: 1, completed_at: null,
        }],
        count: 1,
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useTasks({}), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].task_id).toBe('t1');
  });

  it('passes status filter as query param when set', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => ({ org_id: 'default', tasks: [], count: 0 }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useTasks({ status: 'active' }), { wrapper: wrap(qc) });
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('status=active');
  });

  it('omits status param when filter is empty', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, json: async () => ({ org_id: 'default', tasks: [], count: 0 }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useTasks({}), { wrapper: wrap(qc) });
    await waitFor(() => {
      expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    });
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).not.toContain('status=');
  });
});
