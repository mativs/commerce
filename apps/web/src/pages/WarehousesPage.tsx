import { Fragment, useEffect, useState } from 'react';
import { inventoryApi, type Product, type Warehouse, type StockFilter } from '../api/client';
import { Pagination } from '../components/Pagination';

export function WarehousesPage({ route }: { route: string }) {
  const initialWarehouse = /^#\/warehouses\/(\d+)$/.exec(route)?.[1] || 'all';
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [warehouseId, setWarehouseId] = useState(initialWarehouse);
  const [stockFilter, setStockFilter] = useState<StockFilter>('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    Promise.all([inventoryApi.warehouses(controller.signal), inventoryApi.products(controller.signal)])
      .then(([locations, catalog]) => {
        if (controller.signal.aborted) return;
        setWarehouses(locations); setProducts(catalog); setOffset(0);
      })
      .catch((e) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to load inventory.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);
  const visibleWarehouses = warehouses.filter((warehouse) => warehouseId === 'all' || warehouse.id === Number(warehouseId));
  const rows = products.map((product) => {
    const stock = product.stock.filter((row) => visibleWarehouses.some((warehouse) => warehouse.id === row.warehouse_id));
    return { product, onHand: stock.reduce((sum, row) => sum + row.on_hand, 0), booked: stock.reduce((sum, row) => sum + row.reserved, 0), available: stock.reduce((sum, row) => sum + row.available, 0) };
  }).filter(({ product, onHand, available }) =>
    (stockFilter === 'all' || (stockFilter === 'on_hand' ? onHand > 0 : available > 0)) &&
    `${product.name} ${product.sku}`.toLowerCase().includes(search.trim().toLowerCase()));
  const page = rows.slice(offset, offset + 20);
  function toggle(id: number) {
    setExpanded((previous) => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  return <main className="orders-main">
    <div className="page-heading"><div><p className="eyebrow">WAREHOUSE INVENTORY</p><h1>Stock overview</h1><p className="intro">Compare product totals and expand a product for warehouse details.</p></div><button disabled={loading} onClick={() => setRefresh(refresh + 1)}>Refresh stock</button></div>
    <section className="orders-panel" aria-busy={loading}>
      <div className="inventory-filters">
        <label className="test-order-picker">Warehouse<select value={warehouseId} disabled={loading} onChange={(e) => { setWarehouseId(e.target.value); setOffset(0); }}><option value="all">All warehouses</option>{warehouses.map((warehouse) => <option value={warehouse.id} key={warehouse.id}>{warehouse.name}</option>)}</select></label>
        <label className="test-order-picker">Show products<select value={stockFilter} onChange={(e) => { setStockFilter(e.target.value as StockFilter); setOffset(0); }}><option value="all">All products</option><option value="available">Available stock only</option><option value="on_hand">On-hand stock only</option></select></label>
        <label>Find a product<input type="search" value={search} placeholder="Product name or SKU" onChange={(e) => { setSearch(e.target.value); setOffset(0); }} /></label>
      </div>
      <p className="detail">{warehouseId === 'all' ? 'Totals across all warehouses.' : 'Totals for the selected warehouse.'} Booked units are reserved; available = on hand − booked.</p>
      {error ? <p role="alert" className="error">{error}</p> : loading ? <p role="status">Loading inventory…</p> : page.length ?
        <div className="table-scroll"><table className="orders-table"><thead><tr><th>Product</th><th>On hand</th><th>Booked</th><th>Available</th></tr></thead><tbody>{page.map(({ product, onHand, booked, available }) => <Fragment key={product.id}>
          <tr><td><button className="inventory-expand" type="button" aria-expanded={expanded.has(product.id)} aria-controls={`stock-${product.id}`} onClick={() => toggle(product.id)}><span aria-hidden="true">{expanded.has(product.id) ? '▾' : '▸'}</span> {product.name}</button><small className="block">{product.sku}</small></td><td>{onHand}</td><td>{booked}</td><td>{available}</td></tr>
          {expanded.has(product.id) && <tr id={`stock-${product.id}`} className="inventory-breakdown"><td colSpan={4}><table aria-label={`Warehouse stock for ${product.name}`}><thead><tr><th>Warehouse</th><th>On hand</th><th>Booked</th><th>Available</th></tr></thead><tbody>{visibleWarehouses.map((warehouse) => {
            const stock = product.stock.find((row) => row.warehouse_id === warehouse.id);
            return <tr key={warehouse.id}><td>{warehouse.name}</td><td>{stock?.on_hand || 0}</td><td>{stock?.reserved || 0}</td><td>{stock?.available || 0}</td></tr>;
          })}</tbody></table></td></tr>}
        </Fragment>)}</tbody></table></div> : <p>No products match these filters.</p>}
      <Pagination offset={offset} count={page.length} busy={loading || !!error} onChange={setOffset} />
    </section>
  </main>;
}
