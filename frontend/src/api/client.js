export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';
export const BASE = import.meta.env.VITE_API_BASE || '/api';

let token = null;
let onUnauthorized = () => {};
export const setToken = (t) => { token = t; };
export const setOnUnauthorized = (f) => { onUnauthorized = f; };

export async function api(method, path, body) {
  if (USE_MOCK) {
    const m = await import('./mock.js');
    return m.mockHandle(method, path, body);
  }
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  if (method !== 'GET') headers['Idempotency-Key'] = crypto.randomUUID();
  const res = await fetch(BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401) onUnauthorized();
  const isJson = (res.headers.get('content-type') || '').includes('json');
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const e = (data && data.error) || { code: 'UNKNOWN', message: 'Request failed' };
    throw Object.assign(new Error(e.message), { code: e.code });
  }
  return data;
}

export async function downloadIcs(id) {
  const text = await api('GET', `/student/interviews/${id}/ics`);
  const url = URL.createObjectURL(new Blob([text], { type: 'text/calendar' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `interview-${id}.ics`;
  a.click();
  URL.revokeObjectURL(url);
}