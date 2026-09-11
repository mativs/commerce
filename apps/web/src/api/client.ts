export async function getHealth(signal: AbortSignal): Promise<void> {
  const baseUrl = import.meta.env.VITE_API_URL?.trim().replace(/\/+$/, '');
  if (!baseUrl) throw new Error('VITE_API_URL is not configured.');

  let response: Response;
  try {
    response = await fetch(`${baseUrl}/health`, {
      signal: AbortSignal.any([signal, AbortSignal.timeout(5000)]),
      cache: 'no-store',
    });
  } catch {
    throw new Error('Cannot reach the API. Check that it is running and try again.');
  }
  if (!response.ok) throw new Error(`API request failed (HTTP ${response.status}).`);

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new Error('The API returned invalid JSON.');
  }
  if (typeof body !== 'object' || body === null || !('status' in body) || body.status !== 'ok') {
    throw new Error('The API returned an unexpected health response.');
  }
}

export type WarehouseInput = { name: string; latitude: number; longitude: number };
export type Warehouse = WarehouseInput & { id: number; created_at: string; updated_at: string; deleted_at: string | null };
export type AuditLog = { id: number; action: string; created_at: string; old_values: Warehouse | null; new_values: Warehouse | null };

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = import.meta.env.VITE_API_URL?.trim().replace(/\/+$/, '');
  if (!baseUrl) throw new Error('VITE_API_URL is not configured.');
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...options,
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(10000)])
        : AbortSignal.timeout(10000),
    });
  } catch {
    throw new Error('Cannot reach the API. Refresh the list before retrying a change.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(typeof detail === 'string' ? detail : response.status === 422
      ? 'Enter a name, latitude between −90 and 90, and longitude between −180 and 180.'
      : `Request failed (HTTP ${response.status}). Please try again.`);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export const warehouseApi = {
  logs: (id: number) => request<AuditLog[]>(`/warehouses/${id}/logs`),
  list: (signal: AbortSignal) => request<Warehouse[]>('/warehouses', { signal }),
  create: (data: WarehouseInput) => request<Warehouse>('/warehouses', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: WarehouseInput) => request<Warehouse>(`/warehouses/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  remove: (id: number) => request<void>(`/warehouses/${id}`, { method: 'DELETE' }),
};
