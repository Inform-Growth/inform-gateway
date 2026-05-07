import { describe, it, expect, beforeEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useSkills, useCreateSkill, useUpdateSkill, useDeleteSkill } from './useSkills';

const wrap = (qc: QueryClient) =>
  function W({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };

describe('useSkills', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('fetches the list', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: '1',
          name: 'a',
          description: 'd',
          prompt_template: 't',
          is_system: 0,
          created_by: null,
          created_at: 1,
          updated_at: 1,
        },
      ],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useSkills(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });
});

describe('useCreateSkill', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('POSTs and invalidates', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        id: '2',
        name: 'b',
        description: 'd',
        prompt_template: 't',
        is_system: 0,
        created_by: null,
        created_at: 1,
        updated_at: 1,
      }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const inv = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useCreateSkill(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'b', description: 'd', prompt_template: 't' });
    });
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ name: 'b', description: 'd', prompt_template: 't' });
    expect(inv).toHaveBeenCalledWith({ queryKey: ['skills'] });
  });
});

describe('useUpdateSkill', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('PUTs description+prompt_template only (name is the path)', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        id: '1',
        name: 'a',
        description: 'd2',
        prompt_template: 't2',
        is_system: 0,
        created_by: null,
        created_at: 1,
        updated_at: 2,
      }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { result } = renderHook(() => useUpdateSkill(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        name: 'a',
        description: 'd2',
        prompt_template: 't2',
      });
    });
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.method).toBe('PUT');
    expect(url).toContain('/admin/api/skills/a');
    expect(JSON.parse(init.body)).toEqual({ description: 'd2', prompt_template: 't2' });
  });
});

describe('useDeleteSkill', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('DELETEs by name and invalidates', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ deleted: 'a' }),
    });
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const inv = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useDeleteSkill(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync('a');
    });
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.method).toBe('DELETE');
    expect(url).toContain('/admin/api/skills/a');
    expect(inv).toHaveBeenCalledWith({ queryKey: ['skills'] });
  });
});
