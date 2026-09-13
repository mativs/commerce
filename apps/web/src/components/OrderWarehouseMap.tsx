import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { inventoryApi, type Order, type Warehouse } from '../api/client';

type Point = { latitude: number; longitude: number; label: string; kind: 'shipping' | 'selected' | 'candidate' | 'other' };
const colors = { shipping: '#7346b1', selected: '#237343', candidate: '#246da0', other: '#64717b' };

export function OrderWarehouseMap({ order }: { order: Order }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [warehouseError, setWarehouseError] = useState(false);
  const [tileError, setTileError] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setWarehouses([]); setWarehouseError(false); setLoading(true);
    inventoryApi.warehouses(controller.signal).then((rows) => {
      if (!controller.signal.aborted) setWarehouses(rows);
    }).catch(() => {
      if (!controller.signal.aborted) setWarehouseError(true);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [order.id, order.updated_at]);

  const points = useMemo(() => {
    const decision = order.warehouse_decision;
    const candidates = decision?.candidates || [];
    const candidateIds = new Set(candidates.map((candidate) => candidate.warehouse_id));
    const result: Point[] = warehouses.filter((warehouse) => !candidateIds.has(warehouse.id)).map((warehouse) => ({
      latitude: warehouse.latitude, longitude: warehouse.longitude,
      label: `${warehouse.name} (#${warehouse.id}) — current location; ${warehouse.id === order.warehouse_id ? 'assigned warehouse' : !decision ? 'No saved decision' : new Date(warehouse.created_at) > new Date(decision.evaluated_at) ? 'Added after this order was evaluated' : 'Not enough stock for this order'}`,
      kind: warehouse.id === order.warehouse_id ? 'selected' : 'other',
    }));
    for (const candidate of candidates) result.push({
      ...candidate.coordinates,
      label: `${candidate.warehouse_name} (#${candidate.warehouse_id}) — saved location; rank ${candidate.rank}; ${candidate.distance_km.toLocaleString(undefined, { maximumFractionDigits: 6 })} km; ${candidate.outcome.toLowerCase().replaceAll('_', ' ')}`,
      kind: candidate.warehouse_id === decision?.selected_warehouse_id ? 'selected' : 'candidate',
    });
    const shipping = decision?.shipping_coordinates || (order.latitude !== null && order.longitude !== null ? { latitude: order.latitude, longitude: order.longitude } : null);
    if (shipping) result.push({ ...shipping, label: 'Shipping location — saved delivery coordinates', kind: 'shipping' });
    return result;
  }, [order, warehouses]);

  useEffect(() => {
    if (!container.current || !points.length) return;
    setTileError(false);
    const map = L.map(container.current, { scrollWheelZoom: false });
    mapRef.current = map;
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).on('tileerror', () => setTileError(true)).addTo(map);
    for (const point of points) {
      const popup = document.createElement('span');
      popup.textContent = point.label;
      const icon = L.divIcon({
        className: 'order-map-marker',
        html: `<span style="background:${colors[point.kind]}">${point.kind === 'shipping' ? 'S' : point.kind === 'selected' ? '✓' : 'W'}</span>`,
        iconSize: [28, 28],
        // Opposite anchors keep a shipping/warehouse pair at the same coordinates clickable.
        iconAnchor: point.kind === 'shipping' ? [14, 28] : [14, 0],
      });
      L.marker([point.latitude, point.longitude], { icon, title: point.label, alt: point.label, zIndexOffset: point.kind === 'shipping' ? 1000 : 0 }).bindPopup(popup).addTo(map);
    }
    map.fitBounds(L.latLngBounds(points.map((point) => [point.latitude, point.longitude])), { padding: [35, 35], maxZoom: 13 });
    const resize = new ResizeObserver(() => map.invalidateSize());
    resize.observe(container.current);
    return () => { resize.disconnect(); map.remove(); mapRef.current = null; };
  }, [points]);

  return <div className="order-map-section">
    <div className="summary-line"><h3>Warehouse and shipping map</h3><button type="button" disabled={!points.length} onClick={() => mapRef.current?.fitBounds(L.latLngBounds(points.map((point) => [point.latitude, point.longitude])), { padding: [35, 35], maxZoom: 13 })}>Show all locations</button></div>
    {loading && <p role="status">Loading warehouse locations…</p>}
    {warehouseError && <p role="status">Could not load all current warehouses. Saved order locations are still shown.</p>}
    {!points.some((point) => point.kind === 'shipping') && <p className="detail">Shipping coordinates are not available for this order.</p>}
    {points.length > 0 ? <div ref={container} className="order-warehouse-map" role="region" aria-label="Warehouse and shipping locations map" /> : !loading && <p>No locations available to map.</p>}
    {tileError && <p role="status">The map background could not fully load. Location markers and the decision table remain available.</p>}
    <div className="order-map-legend" aria-label="Map legend">
      {(['shipping', 'selected', 'candidate', 'other'] as const).map((kind) => <span key={kind}><i style={{ background: colors[kind] }} aria-hidden="true" />{{ shipping: 'Shipping (S)', selected: 'Selected (✓)', candidate: 'Decision candidate (W)', other: 'Other current warehouse (W)' }[kind]}</span>)}
    </div>
    <p className="detail">Candidate markers use saved checkout locations. Other warehouses use current locations and may not have existed or been eligible at checkout. Select a marker for details.</p>
  </div>;
}
