import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, orderApi, productApi, warehouseApi, type Order, type OrderInput, type Product, type ShippingAddressInput, type Warehouse } from '../api/client';

const money = (value: string | number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value));
const date = (value: string) => new Date(value).toLocaleString();
const activityDate = (value: string) => new Date(value).toLocaleString(undefined, {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3,
});
const message = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Please try again.';
const reasons: Record<string, string> = {
  GEOCODING_FAILED: 'We could not locate the shipping address. Check the address and place a new order.',
  OUT_OF_STOCK: 'No single warehouse has enough stock to fulfill these items. Try a smaller quantity or different items in a new order.',
  PAYMENT_FAILED: 'Payment was declined. Your stock reservation has been released.',
};
const labels: Record<string, string> = { CREATED: 'Created', BOOKED: 'Awaiting payment', PAID: 'Paid', CANCELLED: 'Cancelled' };
const storageKey = 'canals-checkout-attempt';
type Attempt = { key: string; payload: OrderInput };
function savedAttempt(): Attempt | null {
  try { const value = JSON.parse(sessionStorage.getItem(storageKey) || 'null'); return value?.key && value?.payload?.items && value?.payload?.shipping_address ? value : null; }
  catch { return null; }
}
function Badge({ status }: { status: string }) { return <span className={`order-badge badge-${status.toLowerCase()}`}>{labels[status] || status}</span>; }

export function OrdersPage({ route }: { route: string }) {
  const match = /^#\/orders\/(\d+)$/.exec(route);
  if (route === '#/orders/new') return <OrderForm />;
  if (match) return <OrderDetail id={Number(match[1])} />;
  return <OrderList />;
}

function OrderList() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    orderApi.list(controller.signal, offset).then(setOrders).catch((e) => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset, refresh]);
  return <main className="orders-main">
    <div className="page-heading"><div><p className="eyebrow">ORDER MANAGEMENT</p><h1>Your orders</h1><p className="intro">From your next supply run to the warehouse door.</p></div>
      <a className="button primary" href="#/orders/new">+ New order</a></div>
    {savedAttempt() && <p className="notice">A checkout needs your attention. <a href="#/orders/new">Check its result</a> before placing another order.</p>}
    <section className="orders-panel" aria-busy={loading}>
      <div className="list-heading"><h2>Order history</h2><button onClick={() => setRefresh(refresh + 1)} disabled={loading}>Refresh</button></div>
      {error ? <p role="alert" className="error">{error}</p> : loading ? <p role="status">Loading orders…</p> : orders.length === 0 ?
        <div className="empty-state"><span className="empty-symbol" aria-hidden="true">▤</span><h2>{offset ? 'No more orders' : 'Your first order starts here'}</h2><p>Choose products, add delivery details, and we’ll find a warehouse.</p><a className="button primary" href="#/orders/new">Create an order</a></div> :
        <div className="table-scroll"><table className="orders-table"><thead><tr><th>Order</th><th>Ship to</th><th>Status</th><th>Total · USD</th><th><span className="sr-only">Details</span></th></tr></thead><tbody>{orders.map((order) => <tr key={order.id}>
          <td><a className="order-link" href={`#/orders/${order.id}`}>#{order.id}</a><small className="block">{date(order.created_at)}</small></td>
          <td>{order.shipping_address.recipient_name || '—'}<small className="block">{order.shipping_address.city}</small></td>
          <td><Badge status={order.status} /></td><td className="money">{money(order.total_amount)}</td><td><a href={`#/orders/${order.id}`} aria-label={`View order ${order.id}`}>View →</a></td>
        </tr>)}</tbody></table></div>}
      <div className="pagination"><button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button><span>Page {offset / 20 + 1}</span><button disabled={loading || !!error || orders.length < 20} onClick={() => setOffset(offset + 20)}>Next</button></div>
    </section>
  </main>;
}

const blankAddress: ShippingAddressInput = { recipient_name: '', phone: '', address_line1: '', address_line2: '', city: 'Mar del Plata', state: 'Buenos Aires', postal_code: '', country_code: 'AR', delivery_instructions: '' };
const fields: { name: keyof ShippingAddressInput; label: string; required?: boolean; max: number; auto?: string }[] = [
  { name: 'recipient_name', label: 'Recipient name', required: true, max: 255, auto: 'shipping name' },
  { name: 'phone', label: 'Phone (optional)', max: 50, auto: 'shipping tel' },
  { name: 'address_line1', label: 'Street address', required: true, max: 255, auto: 'shipping address-line1' },
  { name: 'address_line2', label: 'Apartment, suite, etc. (optional)', max: 255, auto: 'shipping address-line2' },
  { name: 'city', label: 'City', required: true, max: 100, auto: 'shipping address-level2' },
  { name: 'state', label: 'State / province', required: true, max: 100, auto: 'shipping address-level1' },
  { name: 'postal_code', label: 'Postal code', required: true, max: 20, auto: 'shipping postal-code' },
  { name: 'country_code', label: 'Country code', required: true, max: 2, auto: 'shipping country' },
];

function OrderForm() {
  const [attempt, setAttempt] = useState<Attempt | null>(savedAttempt);
  const [products, setProducts] = useState<Product[]>([]);
  const [items, setItems] = useState<{ product_id: number; quantity: string }[]>(() => (attempt?.payload.items || []).map((i) => ({ ...i, quantity: String(i.quantity) })));
  const [address, setAddress] = useState<ShippingAddressInput>(attempt?.payload.shipping_address || blankAddress);
  const [notes, setNotes] = useState(attempt?.payload.notes || '');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [catalogError, setCatalogError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const submitting = useRef(false);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setCatalogError('');
    productApi.list(controller.signal).then((rows) => setProducts(rows.filter((p) => p.is_active && p.currency === 'USD' && !p.deleted_at)))
      .catch((e) => { if (!controller.signal.aborted) setCatalogError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  const byId = new Map(products.map((p) => [p.id, p]));
  const results = products.filter((p) => `${p.name} ${p.sku}`.toLowerCase().includes(search.toLowerCase())).slice(0, 8);
  const validItems = items.length > 0 && items.every((i) => /^\d+$/.test(i.quantity) && Number(i.quantity) > 0 && Number(i.quantity) <= 2147483647 && byId.has(i.product_id));
  const total = items.reduce((sum, i) => sum + Number(byId.get(i.product_id)?.price || 0) * (Number(i.quantity) || 0), 0);
  const locked = busy || !!attempt;
  async function submit(event: FormEvent) {
    event.preventDefault(); if (submitting.current) return;
    if (!attempt && !validItems) { setError('Add at least one product with a valid whole-number quantity.'); return; }
    submitting.current = true; setBusy(true); setError('');
    try {
      const next = attempt || { key: crypto.randomUUID(), payload: { shipping_address: address, notes: notes.trim() || null, items: items.map((i) => ({ product_id: i.product_id, quantity: Number(i.quantity) })) } };
      // Persist before sending: even a refresh after an uncertain response must reuse the key.
      sessionStorage.setItem(storageKey, JSON.stringify(next)); setAttempt(next);
      const order = await orderApi.create(next.payload, next.key);
      sessionStorage.removeItem(storageKey); setAttempt(null);
      window.location.hash = `#/orders/${order.id}`;
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) { sessionStorage.removeItem(storageKey); setAttempt(null); }
      setError(message(e));
    } finally { submitting.current = false; setBusy(false); }
  }
  return <main className="orders-main">
    <a className="back-link" href="#/orders">← All orders</a>
    <div className="page-heading"><div><p className="eyebrow">A NEW DELIVERY</p><h1>Create an order</h1><p className="intro">Build your order, then tell us where it’s going.</p></div><span className="muted">All prices in USD</span></div>
    <form className="checkout-layout" onSubmit={submit}>
      <div>
        <section className="orders-panel"><h2><span className="step-number">1</span> Choose your items</h2>
          {catalogError && <p role="alert" className="error">{catalogError} <button type="button" onClick={() => setReload(reload + 1)}>Reload products</button></p>}
          <fieldset disabled={locked || loading}>
            <label>Find a product<input type="search" placeholder="Search by product name or SKU…" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
            {loading ? <p role="status">Loading products…</p> : <div className="product-picker">{results.map((p) => <div className="picker-row" key={p.id}><div><strong>{p.name}</strong><small className="block">{p.sku} · {money(p.price)}</small></div><button type="button" aria-label={`Add ${p.name}`} disabled={items.some((i) => i.product_id === p.id)} onClick={() => setItems([...items, { product_id: p.id, quantity: '1' }])}>{items.some((i) => i.product_id === p.id) ? 'Added' : '+ Add'}</button></div>)}{!results.length && <p className="detail">{products.length ? 'No matches. Try a different name or SKU.' : 'No active USD products are available.'}</p>}</div>}
            <div className="selected-heading"><h3>Order items <span className="count">{items.length}</span></h3></div>
            {!items.length && <p className="detail">Add products above to start your order.</p>}
            {items.map((item) => <div className="cart-row" key={item.product_id}><div><strong>{byId.get(item.product_id)?.name || `Product #${item.product_id}`}</strong><small className="block">{byId.has(item.product_id) ? `${money(byId.get(item.product_id)!.price)} each` : 'Product currently unavailable'}</small></div><label className="quantity-label">Quantity<input aria-label={`Quantity for ${byId.get(item.product_id)?.name || item.product_id}`} type="number" required min={1} max={2147483647} step={1} value={item.quantity} onChange={(e) => setItems(items.map((i) => i.product_id === item.product_id ? { ...i, quantity: e.target.value } : i))} /></label><button type="button" className="text-button danger" aria-label={`Remove ${byId.get(item.product_id)?.name || item.product_id}`} onClick={() => setItems(items.filter((i) => i.product_id !== item.product_id))}>Remove</button></div>)}
          </fieldset>
        </section>
        <section className="orders-panel"><h2><span className="step-number">2</span> Shipping information</h2><fieldset disabled={locked}>
          <div className="address-grid">{fields.map((f) => <label key={f.name}>{f.label}<input required={f.required} maxLength={f.max} autoComplete={f.auto} type={f.name === 'phone' ? 'tel' : 'text'} pattern={f.name === 'country_code' ? '[A-Za-z]{2}' : f.required ? '.*\\S.*' : undefined} value={address[f.name] || ''} onChange={(e) => setAddress({ ...address, [f.name]: f.name === 'country_code' ? e.target.value.toUpperCase() : e.target.value })} />{f.name === 'country_code' && <small>Two-letter code, e.g. AR or US.</small>}</label>)}</div>
          <label>Delivery instructions (optional)<textarea rows={2} maxLength={1000} value={address.delivery_instructions || ''} placeholder="Gate code, entrance, or delivery preferences" onChange={(e) => setAddress({ ...address, delivery_instructions: e.target.value })} /></label>
          <label>Order notes (optional)<textarea rows={2} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
        </fieldset></section>
      </div>
      <aside className="checkout-summary"><section className="orders-panel"><p className="eyebrow">READY WHEN YOU ARE</p><h2>Order summary</h2><div className="summary-line"><span>Products</span><strong>{items.length}</strong></div><div className="summary-line summary-total"><span>Estimated total</span><strong>{money(total)}</strong></div><p className="detail">USD · Final prices and availability are confirmed when you place the order.</p>
        {attempt && !busy && <p className="notice">Your last submission needs a result check. Retry below to check the same order safely.</p>}
        {error && <p role="alert" className="error">{error}</p>}
        <button type="submit" className="primary place-order" disabled={busy || (!attempt && (loading || !!catalogError || !validItems))}>{busy ? 'Placing your order…' : attempt ? 'Check order result' : 'Place order'}</button>
        <p className="detail" role="status">{busy ? 'Finding a warehouse and processing payment. This may take a few seconds.' : 'We’ll choose the nearest warehouse that can fulfill your entire order.'}</p>
      </section></aside>
    </form>
  </main>;
}

function OrderDetail({ id }: { id: number }) {
  const [order, setOrder] = useState<Order | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    orderApi.get(id, controller.signal).then(setOrder).catch((e) => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    productApi.list(controller.signal).then(setProducts).catch(() => { /* IDs remain visible if catalog is unavailable. */ });
    warehouseApi.list(controller.signal).then(setWarehouses).catch(() => { /* Warehouse ID remains visible. */ });
    return () => controller.abort();
  }, [id, refresh]);
  const address = order?.shipping_address;
  return <main className="orders-main"><a className="back-link" href="#/orders">← All orders</a>
    <div className="page-heading"><div><p className="eyebrow">ORDER DETAILS</p><h1>Order #{id}</h1>{order && <p className="intro">Placed {date(order.created_at)}</p>}</div><div className="actions"><button disabled={loading} onClick={() => setRefresh(refresh + 1)}>Refresh status</button><a className="button primary" href="#/orders/new">New order</a></div></div>
    {error && <p role="alert" className="error">{error}</p>}{loading && !order && <p role="status">Loading order…</p>}
    {order && <><div className={`order-outcome outcome-${order.status.toLowerCase()}`} role="status"><Badge status={order.status} /><p>{order.status === 'PAID' ? 'Your order is confirmed and paid. Your items are reserved for delivery.' : order.status === 'CANCELLED' ? reasons[order.failure_reason || ''] || 'This order has been cancelled.' : 'Your order is saved. Payment or processing is not yet confirmed. Refresh to check its status; do not place the same order again.'}</p></div>
      <div className="checkout-layout"><section className="orders-panel"><h2>Items ordered</h2><div className="table-scroll"><table className="orders-table"><thead><tr><th>Product</th><th>Quantity</th><th>Unit price</th><th>Amount</th></tr></thead><tbody>{order.items.map((item) => <tr key={item.product_id}><td>{products.find((p) => p.id === item.product_id)?.name || `Product #${item.product_id}`}<small className="block">{products.find((p) => p.id === item.product_id)?.sku}</small></td><td>{item.quantity}</td><td className="money">{money(item.unit_price)}</td><td className="money">{money(Number(item.unit_price) * item.quantity)}</td></tr>)}</tbody></table></div><div className="summary-line summary-total"><span>Total · USD</span><strong>{money(order.total_amount)}</strong></div>{order.notes && <><h3>Order notes</h3><p className="preserve-lines">{order.notes}</p></>}</section>
      <section className="orders-panel"><h2>Delivery details</h2>{address && <address><strong>{address.recipient_name}</strong><br />{address.address_line1}{address.address_line2 && <><br />{address.address_line2}</>}<br />{address.city}, {address.state} {address.postal_code}<br />{address.country_code}{address.phone && <><br />{address.phone}</>}</address>}{address?.delivery_instructions && <><h3>Delivery instructions</h3><p className="preserve-lines">{address.delivery_instructions}</p></>}<hr /><h3>Assigned warehouse</h3><p>{order.warehouse_id ? warehouses.find((w) => w.id === order.warehouse_id)?.name || `Warehouse #${order.warehouse_id}` : 'Not assigned'}</p>{order.latitude !== null && order.longitude !== null && <small>Delivery coordinates: {order.latitude.toFixed(5)}, {order.longitude.toFixed(5)}</small>}</section></div>
      <section className="orders-panel"><h2>Order activity</h2><ol className="order-timeline">{order.history.map((event, index) => <li key={index}><div><strong>{labels[event.status] || event.status}</strong><small className="block">{activityDate(event.created_at)}</small>{event.reason && <p>{reasons[event.reason] || event.reason}</p>}</div></li>)}</ol></section>
    </>}
  </main>;
}
