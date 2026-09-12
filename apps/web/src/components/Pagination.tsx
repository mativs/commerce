export function Pagination({ offset, count, busy, onChange, size = 20 }: {
  offset: number; count: number; busy: boolean; onChange: (offset: number) => void; size?: number;
}) {
  return <div className="pagination" aria-label="Pagination">
    <button type="button" disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - size))}>Previous</button>
    <span>Page {Math.floor(offset / size) + 1}</span>
    <button type="button" disabled={busy || count < size} onClick={() => onChange(offset + size)}>Next</button>
  </div>;
}
