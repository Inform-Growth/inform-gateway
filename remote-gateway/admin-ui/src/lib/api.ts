import { getToken } from './auth';

export class ApiError extends Error {
  status: number;
  body?: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, params?: Params): string {
  const url = new URL(path, window.location.origin);
  const token = getToken();
  if (token) url.searchParams.set('token', token);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
}

async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  const res = await fetch(buildUrl(path, params), {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let parsed: unknown = null;
  try { parsed = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    if (res.status === 403 && !window.location.pathname.endsWith('/login')) {
      window.location.href = '/admin/login';
    }
    const msg = (parsed as { error?: string })?.error ?? `${method} ${path} → ${res.status}`;
    throw new ApiError(res.status, msg, parsed);
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>('GET', path, undefined, params),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put:  <T>(path: string, body?: unknown) => request<T>('PUT',  path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
};
