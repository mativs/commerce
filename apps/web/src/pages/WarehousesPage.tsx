import { useEffect, useState, type FormEvent } from 'react';
import { warehouseApi, type Warehouse, type AuditLog } from '../api/client';

const emptyForm = { name: '' };

export function WarehousesPage() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [history, setHistory] = useState<{ name: string; logs: AuditLog[] } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    warehouseApi.list(controller.signal).then(
      (items) => { if (!controller.signal.aborted) setWarehouses(items); },
      (err: unknown) => { if (!controller.signal.aborted) setError(message(err)); },
    ).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);

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
      const data = { name: form.name.trim() };
      const saved = editingId === null
        ? await warehouseApi.create(data)
        : await warehouseApi.update(editingId, data);
      setWarehouses((items) => editingId === null
        ? [...items, saved]
        : items.map((item) => item.id === saved.id ? saved : item));
      setNotice(editingId === null ? 'Warehouse created.' : 'Warehouse updated.');
      setHistory(null);
      reset();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(warehouse: Warehouse) {
    if (!window.confirm(`Delete warehouse “${warehouse.name}”?`)) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await warehouseApi.remove(warehouse.id);
      setWarehouses((items) => items.filter((item) => item.id !== warehouse.id));
      if (editingId === warehouse.id) reset();
      setHistory(null);
      setNotice('Warehouse deleted.');
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <p className="eyebrow">CANALS COMMERCE</p>
      <h1>Warehouses</h1>
      <p className="intro">Manage warehouse names and locations.</p>
      {error && <p role="alert" className="error">{error}</p>}
      <p role="status" className="healthy">{notice}</p>
      <section aria-labelledby="warehouse-form-title">
        <h2 id="warehouse-form-title">{editingId === null ? 'Add warehouse' : 'Edit warehouse'}</h2>
        <form onSubmit={save}>
          <fieldset disabled={busy || loading}>
            <label>Name<input required maxLength={255} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <p className="detail">A location in Mar del Plata is assigned automatically when you create a warehouse.</p>
            <div className="actions">
              <button className="primary" type="submit" disabled={!form.name.trim()}>{busy ? 'Saving…' : editingId === null ? 'Add warehouse' : 'Save changes'}</button>
              {editingId !== null && <button type="button" onClick={reset}>Cancel</button>}
            </div>
          </fieldset>
        </form>
      </section>
      <section aria-labelledby="warehouse-list-title" aria-busy={loading}>
        <div className="list-heading">
          <h2 id="warehouse-list-title">All warehouses</h2>
          <button disabled={busy || loading} onClick={() => setAttempt((value) => value + 1)}>Refresh</button>
        </div>
        {loading ? <p>Loading warehouses…</p> : warehouses.length === 0 ? <p className="detail">{error ? 'Could not load warehouses. Try refreshing.' : 'No warehouses yet. Add your first warehouse above.'}</p> : (
          <ul className="warehouse-list">
            {warehouses.map((warehouse) => (
              <li key={warehouse.id}>
                <div><strong>{warehouse.name}</strong><p className="detail">Latitude: {warehouse.latitude} · Longitude: {warehouse.longitude}</p></div>
                <div className="actions">
                  <button disabled={busy} aria-label={`Edit ${warehouse.name}`} onClick={() => {
                    setEditingId(warehouse.id);
                    setForm({ name: warehouse.name });
                    setNotice('');
                    document.getElementById('warehouse-form-title')?.scrollIntoView({ behavior: 'smooth' });
                  }}>Edit</button>
                  <button disabled={busy} aria-label={`History for ${warehouse.name}`} onClick={async () => {
                    setBusy(true);
                    setError('');
                    try { setHistory({ name: warehouse.name, logs: await warehouseApi.logs(warehouse.id) }); }
                    catch (err) { setError(message(err)); }
                    finally { setBusy(false); }
                  }}>History</button>
                  <button className="danger" disabled={busy} aria-label={`Delete ${warehouse.name}`} onClick={() => void remove(warehouse)}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      {history && <section aria-label="Warehouse history">
        <div className="list-heading"><h2>History: {history.name}</h2><button onClick={() => setHistory(null)}>Close</button></div>
        <ol>{history.logs.map((log) => <li key={log.id}>
          <p><strong>{log.action}</strong> · {new Date(log.created_at).toLocaleString()}</p>
          {log.old_values && <p className="detail">Before: {log.old_values.name} ({log.old_values.latitude}, {log.old_values.longitude})</p>}
          {log.new_values && <p className="detail">After: {log.new_values.name} ({log.new_values.latitude}, {log.new_values.longitude})</p>}
        </li>)}</ol>
      </section>}
    </main>
  );
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}
