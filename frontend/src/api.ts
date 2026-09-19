export type RecordValue = Record<string, any>;
let csrf = sessionStorage.getItem('hr_csrf') || '';

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (!(init.body instanceof FormData) && init.body !== undefined) headers.set('Content-Type', 'application/json');
  if (csrf && init.method && !['GET', 'HEAD'].includes(init.method)) headers.set('X-CSRF-Token', csrf);
  const response = await fetch('/api' + path, { ...init, headers, credentials: 'include', cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败 (${response.status})`);
  }
  return response.json();
}

export function setCsrf(value: string) { csrf = value; sessionStorage.setItem('hr_csrf', value); }
export function clearCsrf() { csrf = ''; sessionStorage.removeItem('hr_csrf'); }
export const json = (value: unknown) => JSON.stringify(value);
