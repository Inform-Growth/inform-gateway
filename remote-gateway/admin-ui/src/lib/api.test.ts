import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ApiError, api } from './api';
import { getToken, setToken, captureTokenFromUrl } from './auth';

describe('auth', () => {
  beforeEach(() => sessionStorage.clear());

  it('captures and strips token from URL', () => {
    history.replaceState(null, '', '/admin/dashboard?token=abc&foo=bar');
    captureTokenFromUrl();
    expect(getToken()).toBe('abc');
    expect(window.location.search).toBe('?foo=bar');
  });

  it('persists set token in sessionStorage', () => {
    setToken('xyz');
    expect(sessionStorage.getItem('admin_token')).toBe('xyz');
    expect(getToken()).toBe('xyz');
  });
});

describe('api', () => {
  beforeEach(() => {
    sessionStorage.setItem('admin_token', 'tkn');
    vi.stubGlobal('fetch', vi.fn());
  });

  it('appends token query param', async () => {
    (fetch as any).mockResolvedValue({ ok: true, json: async () => ({ ok: 1 }) });
    await api.get('/admin/api/stats');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/admin\/api\/stats\?token=tkn$/),
      expect.any(Object),
    );
  });

  it('throws ApiError on non-2xx', async () => {
    (fetch as any).mockResolvedValue({
      ok: false, status: 500,
      json: async () => ({ error: 'boom' }),
    });
    await expect(api.get('/admin/api/stats')).rejects.toBeInstanceOf(ApiError);
  });
});
