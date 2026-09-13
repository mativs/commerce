import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, monitoringApi, type ValidationParameters, type ValidationRun, type ValidationFinding } from '../api/client';
import { Pagination } from '../components/Pagination';

const checks = [
  { code: 'ORDER_TOTAL_MISMATCH', label: 'Incorrect order total', group: 'Order integrity', description: 'Compare the order total with saved item prices and quantities.' },
  { code: 'PAID_WITHOUT_REFERENCE', label: 'Paid without payment reference', group: 'Order integrity', description: 'Find paid orders without a recorded payment identifier.' },
  { code: 'INVALID_ORDER_STRUCTURE', label: 'Invalid order structure', group: 'Order integrity', description: 'Check items, assigned warehouse, and delivery coordinates.' },
  { code: 'INCONSISTENT_STATUS_HISTORY', label: 'Inconsistent status history', group: 'Order integrity', description: 'Check status transitions and cancellation reasons.' },
  { code: 'ORDER_STUCK_CREATED', label: 'Checkout not progressing', group: 'Checkout progress', description: 'Find orders that have stayed Created too long.' },
  { code: 'PAYMENT_NOT_STARTED', label: 'Payment not started', group: 'Checkout progress', description: 'Find orders that have stayed Stock reserved too long.' },
  { code: 'PAYMENT_PENDING_TOO_LONG', label: 'Payment pending too long', group: 'Checkout progress', description: 'Find orders that have stayed Paying too long.' },
  { code: 'INVENTORY_RESERVATION_MISMATCH', label: 'Reserved stock mismatch', group: 'Inventory', description: 'Compare reserved stock with the quantities held by orders.' },
];
const checkInfo = (code: string) => checks.find((c) => c.code === code);
const label = (code: string) => checkInfo(code)?.label || 'Historical check';
const description = (code: string) => checkInfo(code)?.description || 'Review the recorded result for this historical check.';
const date = (value: string) => new Date(value).toLocaleString();
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to load monitoring data.';
const statusLabels: Record<string, string> = { RUNNING: 'Running', COMPLETED: 'Completed', PARTIAL: 'Partial', FAILED: 'Failed', INTERRUPTED: 'Interrupted', PENDING: 'Waiting', SKIPPED: 'Not evaluated' };
const pendingKey = 'canals-monitoring-request';
type Attempt = { key: string; parameters: ValidationParameters };
function savedAttempt(): Attempt | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(pendingKey) || 'null');
    return value && typeof value.key === 'string' && Array.isArray(value.parameters?.checks) && value.parameters?.thresholds ? value : null;
  } catch { return null; }
}
function Status({ status }: { status: string }) {
  return <span className={`order-badge monitor-status-${status.toLowerCase()}`}>{statusLabels[status] || status}</span>;
}
function duration(run: ValidationRun) {
  return run.finished_at ? `${Math.max(0, (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000).toFixed(1)}s` : 'In progress';
}

export function MonitoringPage({ route }: { route: string }) {
  const id = /^#\/monitoring\/(\d+)$/.exec(route)?.[1];
  const [dialog, setDialog] = useState(false);
  const [initial, setInitial] = useState<ValidationParameters | undefined>();
  const [attempt, setAttempt] = useState<Attempt | null>(savedAttempt);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submitting = useRef(false);
  async function execute(request: Attempt) {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError(''); setAttempt(request); setDialog(false);
    try {
      sessionStorage.setItem(pendingKey, JSON.stringify(request));
      const result = await monitoringApi.run(request.parameters, request.key);
      sessionStorage.removeItem(pendingKey); setAttempt(null);
      window.location.hash = `/monitoring/${result.id}`;
    } catch (e) {
      if (e instanceof ApiError && [409, 422].includes(e.status)) {
        sessionStorage.removeItem(pendingKey); setAttempt(null);
      }
      setError(message(e));
    } finally { submitting.current = false; setBusy(false); }
  }
  function open(parameters?: ValidationParameters) { setInitial(parameters); setDialog(true); }
  return <main className="orders-main monitoring-main">
    {id && <a className="back-link" href="#/monitoring">← Run history</a>}
    <div className="page-heading"><div><p className="eyebrow">ORDER MONITORING</p><h1>{id ? `Run #${id}` : 'Check your order flow'}</h1><p className="intro">Find stalled orders and inconsistencies in totals, history, and stock.</p></div>
      {!id && <button className="primary" disabled={busy || !!attempt} onClick={() => open()}>Run checks</button>}
    </div>
    {busy && <p className="notice" role="status">Checking orders… This can take up to 35 seconds.</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {attempt && !busy && <div className="notice"><p>This request has no confirmed result yet. Check its status using the same request to avoid duplicate runs.</p><button onClick={() => execute(attempt)}>Check run status</button></div>}
    {id ? <RunDetail id={Number(id)} onRun={open} disabled={busy || !!attempt} /> : <RunHistory />}
    {dialog && <RunDialog initial={initial} onClose={() => setDialog(false)} onRun={(parameters) => execute({ key: crypto.randomUUID(), parameters })} />}
  </main>;
}

function RunDialog({ initial, onClose, onRun }: { initial?: ValidationParameters; onClose: () => void; onRun: (parameters: ValidationParameters) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState(initial?.checks.filter((code) => checks.some((c) => c.code === code)) || checks.map((c) => c.code));
  const [thresholds, setThresholds] = useState(initial?.thresholds || { created_age_seconds: 300, booked_age_seconds: 300, payment_age_seconds: 300 });
  useEffect(() => { const element = ref.current; const previous = document.activeElement as HTMLElement | null; element?.showModal(); return () => { element?.close(); previous?.focus(); }; }, []);
  function submit(e: FormEvent) { e.preventDefault(); if (selected.length) onRun({ checks: selected, thresholds }); }
  return <dialog ref={ref} className="monitor-dialog" aria-labelledby="run-title" onCancel={onClose}>
    <form onSubmit={submit}>
      <div className="list-heading"><h2 id="run-title">Run order checks</h2><button type="button" onClick={onClose} aria-label="Close run dialog">Close</button></div>
      <p className="detail">Checks report issues without changing orders or stock.</p>
      <div className="actions"><button type="button" onClick={() => setSelected(checks.map((c) => c.code))}>Select all</button><button type="button" onClick={() => setSelected([])}>Clear selection</button><span className="muted">{selected.length} of 8 selected</span></div>
      {['Order integrity', 'Checkout progress', 'Inventory'].map((group) => <fieldset className="monitor-check-group" key={group}><legend>{group}</legend>{checks.filter((c) => c.group === group).map((c) => <label className="monitor-checkbox" key={c.code}><input type="checkbox" checked={selected.includes(c.code)} onChange={(e) => setSelected(e.target.checked ? [...selected, c.code] : selected.filter((code) => code !== c.code))} /><span>{c.label}<small className="block">{c.description}</small></span></label>)}</fieldset>)}
      <details><summary>Timing thresholds</summary><p className="detail">Flag orders that stay in a stage longer than this duration.</p>{([
        ['created_age_seconds', 'Created'], ['booked_age_seconds', 'Stock reserved'], ['payment_age_seconds', 'Paying'],
      ] as const).map(([key, title]) => <label key={key}>{title} · seconds<input type="number" min={1} max={604800} step={1} required value={Number.isNaN(thresholds[key]) ? '' : thresholds[key]} onChange={(e) => setThresholds({ ...thresholds, [key]: e.target.valueAsNumber })} /></label>)}</details>
      <div className="monitor-dialog-footer"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={!selected.length} type="submit">Run selected checks</button></div>
    </form>
  </dialog>;
}

function RunHistory() {
  const [runs, setRuns] = useState<ValidationRun[]>([]);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    monitoringApi.list(offset, controller.signal).then((data) => { if (!controller.signal.aborted) setRuns(data); }).catch((e) => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset, refresh]);
  return <section className="orders-panel" aria-busy={loading}>
    <div className="list-heading"><h2>Run history</h2><button disabled={loading} onClick={() => setRefresh(refresh + 1)}>Refresh history</button></div>
    <p className="detail">Completed means the checks finished. Findings show whether issues were detected.</p>
    {error ? <p className="error" role="alert">{error}</p> : loading ? <p role="status">Loading runs…</p> : runs.length ? <div className="table-scroll"><table className="orders-table"><thead><tr><th>Started</th><th>Execution</th><th>Findings</th><th>Duration</th><th><span className="sr-only">Results</span></th></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td>{date(run.started_at)}<small className="block">Run #{run.id}</small></td><td><Status status={run.status} /></td><td>{run.finding_count ? `${run.error_count} errors · ${run.warning_count} warnings` : run.status === 'COMPLETED' ? 'No issues found' : 'No findings recorded yet'}</td><td>{duration(run)}</td><td><a href={`#/monitoring/${run.id}`} aria-label={`View results for run ${run.id}`}>View results →</a></td></tr>)}</tbody></table></div> : <div className="empty-state"><h2>{offset ? 'No more runs' : 'No checks run yet'}</h2><p>Run checks to create a saved report of your order flow.</p></div>}
    <Pagination offset={offset} count={runs.length} busy={loading || !!error} onChange={setOffset} />
  </section>;
}

function RunDetail({ id, onRun, disabled }: { id: number; onRun: (parameters: ValidationParameters) => void; disabled: boolean }) {
  const [run, setRun] = useState<ValidationRun | null>(null);
  const [findings, setFindings] = useState<ValidationFinding[]>([]);
  const [check, setCheck] = useState(''); const [severity, setSeverity] = useState(''); const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0); const [error, setError] = useState(''); const [findingError, setFindingError] = useState(''); const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>; setError('');
    async function load() {
      try {
        const saved = await monitoringApi.get(id, controller.signal);
        if (controller.signal.aborted) return;
        setRun(saved);
        if (saved.status === 'RUNNING') timer = setTimeout(load, 2000);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    }
    void load(); return () => { controller.abort(); clearTimeout(timer); };
  }, [id, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setFindingError('');
    monitoringApi.findings(id, offset, check, severity, controller.signal).then((data) => { if (!controller.signal.aborted) setFindings(data); }).catch((e) => { if (!controller.signal.aborted) setFindingError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [id, offset, check, severity, refresh, run?.status]);
  function filter(code: string) { setCheck(code); setOffset(0); }
  return <>
    <div className="actions monitor-toolbar"><button onClick={() => setRefresh(refresh + 1)}>Refresh results</button>{run && <button className="primary" disabled={disabled || run.status === 'RUNNING'} onClick={() => onRun(run.parameters)}>Run again</button>}</div>
    {error && <p className="error" role="alert">{error}</p>}
    {!run && !error && <p role="status">Loading run…</p>}
    {run && <>
      <section className="orders-panel"><div className="monitor-summary"><div><p className="label">Execution</p><Status status={run.status} /></div><div><p className="label">Findings</p><strong>{run.finding_count}</strong><small className="block">{run.error_count} errors · {run.warning_count} warnings</small></div><div><p className="label">Started</p><span>{date(run.started_at)}</span></div><div><p className="label">Duration</p><span>{duration(run)}</span></div></div><p className="detail">Results describe what was observed during this run. Orders may have changed since then.</p>
      {run.status !== 'COMPLETED' && run.status !== 'RUNNING' && <p className="notice">Some checks could not be evaluated. These results are incomplete; review the check details below.</p>}
      <h2>Checks</h2><div className="monitor-checks">{run.checks?.map((c) => <button key={c.id} className="monitor-check" aria-pressed={check === c.check_code} onClick={() => filter(check === c.check_code ? '' : c.check_code)}><strong>{label(c.check_code)}</strong><small className="block">{description(c.check_code)}</small><span>{c.status === 'COMPLETED' ? c.finding_count ? `${c.finding_count} findings` : 'No issues found' : ['FAILED', 'SKIPPED'].includes(c.status) ? 'Could not evaluate' : statusLabels[c.status] || c.status}</span>{c.error && <small>{c.error.includes('budget') ? 'The run reached its time limit.' : c.error.includes('interrupted') ? 'Execution was interrupted.' : 'The check could not finish. Run it again to try once more.'}</small>}</button>)}</div></section>
      <section className="orders-panel" aria-busy={loading}><h2>Findings</h2><div className="inventory-filters"><label className="test-order-picker">Check<select value={check} onChange={(e) => filter(e.target.value)}><option value="">All checks</option>{run.checks?.map((c) => <option value={c.check_code} key={c.id}>{label(c.check_code)}</option>)}</select></label><label className="test-order-picker">Severity<select value={severity} onChange={(e) => { setSeverity(e.target.value); setOffset(0); }}><option value="">All severities</option><option value="ERROR">Errors</option><option value="WARNING">Warnings</option></select></label></div>
      {findingError ? <p className="error" role="alert">{findingError}</p> : loading ? <p role="status">Loading findings…</p> : findings.length ? <div className="table-scroll"><table className="orders-table"><thead><tr><th>Issue</th><th>Affected record</th><th>Expected</th><th>Observed</th></tr></thead><tbody>{findings.map((finding) => { const [expected, actual] = evidence(finding); return <tr key={finding.id}><td><strong>{label(finding.check_code)}</strong><small className={`block ${finding.severity === 'ERROR' ? 'error' : ''}`}>{finding.severity === 'ERROR' ? 'Error' : 'Warning'}</small><small className="block">{date(finding.observed_at)}</small></td><td>{finding.order_id ? <a href={`#/orders/${finding.order_id}`}>Order #{finding.order_id} →</a> : <><a href={`#/warehouses/${finding.warehouse_id}`}>Warehouse #{finding.warehouse_id} →</a><small className="block">Product #{finding.product_id}</small></>}</td><td>{expected}</td><td>{actual}</td></tr>; })}</tbody></table></div> : <p className="detail">{run.status === 'COMPLETED' ? 'No findings match these filters.' : 'No findings recorded for these filters. Some checks may still be unevaluated.'}</p>}
      <Pagination offset={offset} count={findings.length} busy={loading || !!findingError} onChange={setOffset} /></section>
    </>}
  </>;
}

function evidence(finding: ValidationFinding): [string, string] {
  const e = finding.evidence;
  if ('expected' in e) return [String(e.expected), e.stock_row_missing ? 'Stock record missing' : String(e.actual)];
  if ('threshold_seconds' in e) {
    const age = Math.max(0, Math.floor((Date.parse(finding.observed_at) - Date.parse(String(e.status_since))) / 1000));
    return [`Under ${e.threshold_seconds} seconds`, `${Math.floor(age / 60)}m ${age % 60}s in this stage`];
  }
  if (finding.check_code === 'PAID_WITHOUT_REFERENCE') return ['Payment reference recorded', 'Payment reference missing'];
  if (finding.check_code === 'INVALID_ORDER_STRUCTURE') return ['Complete order details', [['empty_items', 'No items'], ['missing_warehouse', 'Warehouse missing'], ['missing_coordinates', 'Delivery coordinates missing'], ['invalid_items', 'Invalid item values']].filter(([key]) => e[key]).map(([, value]) => value).join('; ')];
  if (finding.check_code === 'INCONSISTENT_STATUS_HISTORY') return ['Valid history matching the order', `Current: ${e.current_status}. Latest history: ${e.latest_history_status || 'missing'}.${e.invalid_history ? ' Invalid transition or cancellation reason.' : ''}${e.failure_reason !== e.history_reason ? ' Cancellation reasons differ.' : ''}`];
  return ['Review recorded state', 'Historical finding; consult the order history.'];
}
