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
