import { useEffect, useState } from 'react';
import { getHealth } from '../api/client';

type Status = { kind: 'loading' } | { kind: 'healthy' } | { kind: 'error'; message: string };

export function HomePage() {
  const [status, setStatus] = useState<Status>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus({ kind: 'loading' });
    getHealth(controller.signal).then(
      () => { if (!controller.signal.aborted) setStatus({ kind: 'healthy' }); },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setStatus({ kind: 'error', message: error instanceof Error ? error.message : 'API check failed.' });
        }
      },
    );
    return () => controller.abort();
  }, [attempt]);

  return (
    <main>
      <p className="eyebrow">API + WEB FOUNDATION</p>
      <h1>Backend Assessment</h1>
      <p className="intro">A small workspace for the next assignment.</p>
      <section aria-label="API connection">
        <p className="label">API status</p>
        <div role="status" aria-live="polite" className={`status ${status.kind}`}>
          <span className="dot" aria-hidden="true" />
          {status.kind === 'loading' ? 'Checking connection…' : status.kind === 'healthy' ? 'Healthy' : 'Unavailable'}
        </div>
        <p className="detail">
          {status.kind === 'healthy' ? 'Connected to the backend API.' : status.kind === 'error' ? status.message : 'Waiting for the backend API.'}
        </p>
        <button disabled={status.kind === 'loading'} onClick={() => setAttempt((value) => value + 1)}>
          {status.kind === 'error' ? 'Try again' : 'Check again'}
        </button>
      </section>
    </main>
  );
}
