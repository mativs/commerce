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

export type WarehouseInput = { name: string };
export type Warehouse = WarehouseInput & { latitude: number; longitude: number; id: number; created_at: string; updated_at: string; deleted_at: string | null };
export type AuditLog<T = Warehouse> = { id: number; action: string; created_at: string; old_values: T | null; new_values: T | null };

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(path: string, options: RequestInit = {}, timeout = 10000): Promise<T> {
  const baseUrl = import.meta.env.VITE_API_URL?.trim().replace(/\/+$/, '');
  if (!baseUrl) throw new Error('VITE_API_URL is not configured.');
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...options,
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...options.headers },
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(timeout)])
        : AbortSignal.timeout(timeout),
    });
  } catch {
    throw new Error('Cannot reach the API. Refresh the list before retrying a change.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new ApiError(typeof detail === 'string' ? detail : response.status === 422
      ? (Array.isArray(detail) ? detail.map((issue: { loc?: string[]; msg?: string }) => `${issue.loc?.slice(1).join('.') || 'Input'}: ${issue.msg || 'Invalid value'}`).join('; ') : 'Check the form fields and try again.')
      : `Request failed (HTTP ${response.status}). Please try again.`, response.status);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export const warehouseApi = {
  logs: (id: number, offset = 0) => request<AuditLog[]>(`/warehouses/${id}/logs?limit=20&offset=${offset}`),
  list: (signal: AbortSignal, offset = 0, limit = 20) => request<Warehouse[]>(`/warehouses?limit=${limit}&offset=${offset}`, { signal }),
  get: (id: number, signal?: AbortSignal) => request<Warehouse>(`/warehouses/${id}`, { signal }),
  create: (data: WarehouseInput) => request<Warehouse>('/warehouses', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: WarehouseInput) => request<Warehouse>(`/warehouses/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  remove: (id: number) => request<void>(`/warehouses/${id}`, { method: 'DELETE' }),
};

export type ShippingAddressInput = {
  recipient_name: string;
  phone: string | null;
  address_line1: string;
  address_line2: string | null;
  city: string;
  state: string;
  postal_code: string;
  country_code: string;
  delivery_instructions: string | null;
};
export type ShippingAddress = ShippingAddressInput & {
  id: number;
  latitude: number | null;
  longitude: number | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
export const shippingAddressApi = {
  list: (signal: AbortSignal, offset = 0, limit = 20) => request<ShippingAddress[]>(`/shipping-addresses?limit=${limit}&offset=${offset}`, { signal }),
  get: (id: number, signal?: AbortSignal) => request<ShippingAddress>(`/shipping-addresses/${id}`, { signal }),
  create: (data: ShippingAddressInput) => request<ShippingAddress>('/shipping-addresses', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: ShippingAddressInput) => request<ShippingAddress>(`/shipping-addresses/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  remove: (id: number) => request<void>(`/shipping-addresses/${id}`, { method: 'DELETE' }),
  logs: (id: number, offset = 0) => request<AuditLog<ShippingAddress>[]>(`/shipping-addresses/${id}/logs?limit=20&offset=${offset}`),
};

export type ProductInput = {
  name: string;
  sku: string;
  description: string | null;
  price: string;
  currency: string;
  is_active: boolean;
};
export type Product = ProductInput & {
  ean: string | null;
  id: number; created_at: string; updated_at: string; deleted_at: string | null;
};
export const productApi = {
  search: (q: string, offset: number, signal: AbortSignal) => request<Product[]>(`/products?limit=8&offset=${offset}&is_active=true&currency=USD&q=${encodeURIComponent(q)}`, { signal }),
  list: (signal: AbortSignal, offset = 0, limit = 20) => request<Product[]>(`/products?limit=${limit}&offset=${offset}`, { signal }),
  get: (id: number, signal?: AbortSignal) => request<Product>(`/products/${id}`, { signal }),
  create: (data: ProductInput) => request<Product>('/products', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: number, data: ProductInput) => request<Product>(`/products/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  remove: (id: number) => request<void>(`/products/${id}`, { method: 'DELETE' }),
  logs: (id: number, offset = 0) => request<AuditLog<Product>[]>(`/products/${id}/logs?limit=20&offset=${offset}`),
};


export type OrderInput = {
  shipping_address: ShippingAddressInput;
  items: { product_id: number; quantity: number }[];
  notes: string | null;
};
export type Order = Omit<OrderInput, 'items'> & {
  id: number;
  status: 'CREATED' | 'BOOKED' | 'PAID' | 'CANCELLED';
  warehouse_id: number | null;
  latitude: number | null;
  longitude: number | null;
  total_amount: string;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
  items: { product_id: number; quantity: number; unit_price: string }[];
  history: { status: string; reason: string | null; created_at: string }[];
};
export const orderApi = {
  list: (signal: AbortSignal, offset = 0) => request<Order[]>(`/orders?limit=20&offset=${offset}`, { signal }),
  get: (id: number, signal?: AbortSignal) => request<Order>(`/orders/${id}`, { signal }),
  create: (data: OrderInput, key: string) => request<Order>('/orders', {
    method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(data),
  }, 30000),
};
