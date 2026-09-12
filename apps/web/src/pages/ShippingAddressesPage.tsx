import { Pagination } from '../components/Pagination';
import { useEffect, useState, type FormEvent } from 'react';
import { shippingAddressApi, type ShippingAddress, type ShippingAddressInput, type AuditLog } from '../api/client';

const emptyForm = {
  recipient_name: '', phone: '', address_line1: '', address_line2: '',
  city: 'Mar del Plata', state: 'Buenos Aires', postal_code: '', country_code: 'AR', delivery_instructions: '',
};
type AddressForm = typeof emptyForm;
const fields: { name: keyof AddressForm; label: string; required?: boolean; maxLength: number; autoComplete?: string; type?: string }[] = [
  { name: 'recipient_name', label: 'Recipient name', required: true, maxLength: 255, autoComplete: 'shipping name' },
  { name: 'phone', label: 'Phone (optional)', maxLength: 50, autoComplete: 'shipping tel', type: 'tel' },
  { name: 'address_line1', label: 'Street address', required: true, maxLength: 255, autoComplete: 'shipping address-line1' },
  { name: 'address_line2', label: 'Apartment, unit, etc. (optional)', maxLength: 255, autoComplete: 'shipping address-line2' },
  { name: 'city', label: 'City', required: true, maxLength: 100, autoComplete: 'shipping address-level2' },
  { name: 'state', label: 'Province / state', required: true, maxLength: 100, autoComplete: 'shipping address-level1' },
  { name: 'postal_code', label: 'Postal code', required: true, maxLength: 20, autoComplete: 'shipping postal-code' },
  { name: 'country_code', label: 'Country code (e.g. AR)', required: true, maxLength: 2, autoComplete: 'shipping country' },
];

export function ShippingAddressesPage() {
  const [addresses, setAddresses] = useState<ShippingAddress[]>([]);
  const [form, setForm] = useState<AddressForm>(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [offset, setOffset] = useState(0);
  const [historyMore, setHistoryMore] = useState(false);
  const [history, setHistory] = useState<{ id: number; name: string; logs: AuditLog<ShippingAddress>[] } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    shippingAddressApi.list(controller.signal, offset).then(
      (items) => { if (!controller.signal.aborted) { setAddresses(items); if (!items.length && offset > 0) setOffset(Math.max(0, offset - 20)); } },
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
      const data: ShippingAddressInput = {
        ...form,
        phone: form.phone.trim() || null,
        address_line2: form.address_line2.trim() || null,
        delivery_instructions: form.delivery_instructions.trim() || null,
      };
      await (editingId === null
        ? shippingAddressApi.create(data)
        : shippingAddressApi.update(editingId, data));
      setAttempt((value) => value + 1);
      setNotice(editingId === null ? 'Shipping address created.' : 'Shipping address updated.');
      setHistory(null);
      reset();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(address: ShippingAddress) {
    if (!window.confirm(`Delete shipping address for “${address.recipient_name}” at ${address.address_line1}?`)) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await shippingAddressApi.remove(address.id);
      setAttempt((value) => value + 1);
      if (editingId === address.id) reset();
      setHistory(null);
      setNotice('Shipping address deleted.');
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  function edit(address: ShippingAddress) {
    setEditingId(address.id);
    setForm({
      recipient_name: address.recipient_name, phone: address.phone ?? '',
      address_line1: address.address_line1, address_line2: address.address_line2 ?? '',
      city: address.city, state: address.state, postal_code: address.postal_code,
      country_code: address.country_code, delivery_instructions: address.delivery_instructions ?? '',
    });
    setNotice('');
    document.getElementById('recipient_name')?.focus();
  }

  return (
    <main>
      <p className="eyebrow">ADMIN / SHIPPING ADDRESSES</p>
      <h1>Shipping addresses</h1>
      <p className="intro">Manage delivery details and saved locations.</p>
      {error && <p role="alert" className="error">{error}</p>}
      <p role="status" className="healthy">{notice}</p>
      <section aria-labelledby="address-form-title">
        <h2 id="address-form-title">{editingId === null ? 'Add shipping address' : 'Edit shipping address'}</h2>
        <form onSubmit={save}>
          <fieldset disabled={busy || loading}>
            <div className="coordinates">
              {fields.map((field) => <label key={field.name} htmlFor={field.name}>{field.label}
                <input id={field.name} name={field.name} type={field.type ?? 'text'} required={field.required}
                  maxLength={field.maxLength} autoComplete={field.autoComplete}
                  pattern={field.name === 'country_code' ? '[A-Za-z]{2}' : undefined}
                  value={form[field.name]} onChange={(event) => setForm({ ...form, [field.name]: event.target.value })} />
              </label>)}
            </div>
            <label htmlFor="delivery_instructions">Delivery instructions (optional)
              <textarea id="delivery_instructions" maxLength={1000} rows={3} value={form.delivery_instructions}
                onChange={(event) => setForm({ ...form, delivery_instructions: event.target.value })} />
            </label>
            <p className="detail">Coordinates are assigned automatically. Demo locations are in Mar del Plata.</p>
            <div className="actions">
              <button className="primary" type="submit" disabled={fields.some((field) => field.required && !form[field.name].trim())}>
                {busy ? 'Please wait…' : editingId === null ? 'Add shipping address' : 'Save changes'}
              </button>
              {editingId !== null && <button type="button" onClick={reset}>Cancel</button>}
            </div>
          </fieldset>
        </form>
      </section>
      <section aria-labelledby="address-list-title" aria-busy={loading}>
        <div className="list-heading">
          <h2 id="address-list-title">All shipping addresses</h2>
          <button disabled={busy || loading} onClick={() => setAttempt((value) => value + 1)}>Refresh</button>
        </div>
        {loading ? <p>Loading shipping addresses…</p> : addresses.length === 0 ? <p className="detail">{error ? 'Could not load addresses. Try refreshing.' : 'No shipping addresses yet. Add your first address above.'}</p> : (
          <ul className="warehouse-list">
            {addresses.map((address) => <li key={address.id}>
              <div>
                <strong>{address.recipient_name}</strong>
                <AddressSummary address={address} />
                <p className="detail">Latitude: {address.latitude} · Longitude: {address.longitude}</p>
              </div>
              <div className="actions">
                <button disabled={busy || loading} aria-label={`Edit address for ${address.recipient_name}`} onClick={() => edit(address)}>Edit</button>
                <button disabled={busy || loading} aria-label={`History for ${address.recipient_name}`} onClick={async () => {
                  setBusy(true);
                  setError('');
                  try { const logs = await shippingAddressApi.logs(address.id); setHistory({ id: address.id, name: address.recipient_name, logs }); setHistoryMore(logs.length === 20); }
                  catch (err) { setError(message(err)); }
                  finally { setBusy(false); }
                }}>History</button>
                <button className="danger" disabled={busy || loading} aria-label={`Delete address for ${address.recipient_name}`} onClick={() => void remove(address)}>Delete</button>
              </div>
            </li>)}
          </ul>
        )}
        <Pagination offset={offset} count={addresses.length} busy={busy || loading || !!error} onChange={setOffset} />
      </section>
      {history && <section aria-label="Shipping address history">
        <div className="list-heading"><h2>History: {history.name}</h2><button onClick={() => setHistory(null)}>Close</button></div>
        <ol>{history.logs.map((log) => <li key={log.id}>
          <p><strong>{log.action}</strong> · {new Date(log.created_at).toLocaleString()}</p>
          {log.old_values && <div><h3>Before</h3><strong>{log.old_values.recipient_name}</strong><AddressSummary address={log.old_values} /><p className="detail">{log.old_values.latitude}, {log.old_values.longitude}</p></div>}
          {log.new_values && <div><h3>After</h3><strong>{log.new_values.recipient_name}</strong><AddressSummary address={log.new_values} /><p className="detail">{log.new_values.latitude}, {log.new_values.longitude}</p></div>}
        </li>)}</ol>
        {historyMore && <button disabled={busy} onClick={async () => {
          setBusy(true); setError('');
          try {
            const logs = await shippingAddressApi.logs(history.id, history.logs.length);
            setHistory({ ...history, logs: [...history.logs, ...logs] });
            setHistoryMore(logs.length === 20);
          } catch (err) { setError(message(err)); } finally { setBusy(false); }
        }}>Load more activity</button>}
      </section>}
    </main>
  );
}

function AddressSummary({ address }: { address: ShippingAddress }) {
  return <>
    <p className="detail">{address.address_line1}{address.address_line2 && `, ${address.address_line2}`}<br />
      {address.city}, {address.state} {address.postal_code} · {address.country_code}</p>
    {address.phone && <p className="detail">Phone: {address.phone}</p>}
    {address.delivery_instructions && <p className="detail">Instructions: {address.delivery_instructions}</p>}
  </>;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}
