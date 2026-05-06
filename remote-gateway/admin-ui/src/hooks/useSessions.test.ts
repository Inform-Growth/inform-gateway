import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useSessions } from './useSessions';

const wrap = (qc: QueryClient) => function W({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: qc }, children);
};

describe('useSessions', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('returns sankey + user_breakdown', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        sankey: {
          nodes: [{ id: 'a', name: 'a' }, { id: 'b', name: 'b' }],
          links: [{ source: 'a', target: 'b', value: 5 }],
        },
        user_breakdown: { alice: 10, bob: 3 },
        recent_sequences: {},
      }),
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useSessions(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.sankey.links).toHaveLength(1);
    expect(result.current.data?.user_breakdown).toEqual({ alice: 10, bob: 3 });
  });
});
