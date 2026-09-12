import { Pagination } from '../components/Pagination';
import { useEffect, useState, type FormEvent } from 'react';
import { productApi, type Product, type AuditLog } from '../api/client';

const emptyForm = { name: '', sku: '', description: '', price: '', currency: 'ARS', is_active: true };

export function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [offset, setOffset] = useState(0);
  const [historyMore, setHistoryMore] = useState(false);
  const [history, setHistory] = useState<{ id: number; name: string; logs: AuditLog<Product>[] } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    productApi.list(controller.signal, offset).then(
      (items) => { if (!controller.signal.aborted) { setProducts(items); if (!items.length && offset > 0) setOffset(Math.max(0, offset - 20)); } },
      (err: unknown) => { if (!controller.signal.aborted) setError(message(err)); },
    ).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, offset]);

  function reset() {
    setEditingId(null);
    setForm(emptyForm);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const data = { ...form, name: form.name.trim(), sku: form.sku.trim(),
        description: form.description.trim() || null };
      await (editingId === null
        ? productApi.create(data)
        : productApi.update(editingId, data));
      setAttempt((value) => value + 1);
      setNotice(editingId === null ? 'Product created.' : 'Product updated.');
      setHistory(null);
      reset();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(product: Product) {
    if (!window.confirm(`Delete product “${product.name}”?`)) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await productApi.remove(product.id);
      setAttempt((value) => value + 1);
      if (editingId === product.id) reset();
      setHistory(null);
      setNotice('Product deleted.');
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <p className="eyebrow">CANALS COMMERCE</p>
      <h1>Products</h1>
      <p className="intro">Manage sellable items, identifiers, and prices.</p>
      {error && <p role="alert" className="error">{error}</p>}
      <p role="status" className="healthy">{notice}</p>
      <section aria-labelledby="product-form-title">
        <h2 id="product-form-title">{editingId === null ? 'Add product' : 'Edit product'}</h2>
        <form onSubmit={save}>
          <fieldset disabled={busy || loading}>
            <label>Name<input required maxLength={255} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <div className="coordinates">
              <label>SKU<input required maxLength={100} value={form.sku} onChange={(event) => setForm({ ...form, sku: event.target.value })} /></label>
              <label>Price<input required type="number" min="0" max="9999999999.99" step="0.01" value={form.price} onChange={(event) => setForm({ ...form, price: event.target.value })} /></label>
              <label>Currency<input required pattern="[A-Za-z]{3}" maxLength={3} value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value })} /></label>
            </div>
            <label>Description (optional)<textarea maxLength={2000} rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
            <label className="checkbox-label"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} />Active</label>
            <p className="detail">An EAN is generated automatically when you create a product.</p>
            <div className="actions">
              <button className="primary" type="submit" disabled={!form.name.trim() || !form.sku.trim()}>{busy ? 'Saving…' : editingId === null ? 'Add product' : 'Save changes'}</button>
              {editingId !== null && <button type="button" onClick={reset}>Cancel</button>}
            </div>
          </fieldset>
        </form>
      </section>
      <section aria-labelledby="product-list-title" aria-busy={loading}>
        <div className="list-heading">
          <h2 id="product-list-title">All products</h2>
          <button disabled={busy || loading} onClick={() => setAttempt((value) => value + 1)}>Refresh</button>
        </div>
        {loading ? <p>Loading products…</p> : products.length === 0 ? <p className="detail">{error ? 'Could not load products. Try refreshing.' : 'No products yet. Add your first product above.'}</p> : (
          <ul className="warehouse-list">
            {products.map((product) => (
              <li key={product.id}>
                <div><strong>{product.name}</strong><ProductSummary product={product} /></div>
                <div className="actions">
                  <button disabled={busy} aria-label={`Edit ${product.name}`} onClick={() => {
                    setEditingId(product.id);
                    setForm({ name: product.name, sku: product.sku, 
                      description: product.description ?? '', price: product.price, currency: product.currency,
                      is_active: product.is_active });
                    setNotice('');
                    document.getElementById('product-form-title')?.scrollIntoView({ behavior: 'smooth' });
                  }}>Edit</button>
                  <button disabled={busy} aria-label={`History for ${product.name}`} onClick={async () => {
                    setBusy(true);
                    setError('');
                    try { const logs = await productApi.logs(product.id); setHistory({ id: product.id, name: product.name, logs }); setHistoryMore(logs.length === 20); }
                    catch (err) { setError(message(err)); }
                    finally { setBusy(false); }
                  }}>History</button>
                  <button className="danger" disabled={busy} aria-label={`Delete ${product.name}`} onClick={() => void remove(product)}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <Pagination offset={offset} count={products.length} busy={busy || loading || !!error} onChange={setOffset} />
      </section>
      {history && <section aria-label="Product history">
        <div className="list-heading"><h2>History: {history.name}</h2><button onClick={() => setHistory(null)}>Close</button></div>
        <ol>{history.logs.map((log) => <li key={log.id}>
          <p><strong>{log.action}</strong> · {new Date(log.created_at).toLocaleString()}</p>
          {log.old_values && <div><h3>Before: {log.old_values.name}</h3><ProductSummary product={log.old_values} /></div>}
          {log.new_values && <div><h3>After: {log.new_values.name}</h3><ProductSummary product={log.new_values} /></div>}
        </li>)}</ol>
        {historyMore && <button disabled={busy} onClick={async () => {
          setBusy(true); setError('');
          try {
            const logs = await productApi.logs(history.id, history.logs.length);
            setHistory({ ...history, logs: [...history.logs, ...logs] });
            setHistoryMore(logs.length === 20);
          } catch (err) { setError(message(err)); } finally { setBusy(false); }
        }}>Load more activity</button>}
      </section>}
    </main>
  );
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

function ProductSummary({ product }: { product: Product }) {
  return <>
    <p className="detail">SKU: {product.sku}{product.ean && ` · EAN: ${product.ean}`}</p>
    <p className="detail">{product.currency} {product.price} · {product.is_active ? 'Active' : 'Inactive'}</p>
    {product.description && <p className="detail">{product.description}</p>}
  </>;
}
