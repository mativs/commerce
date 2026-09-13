import { useEffect, useState } from 'react';
import { WarehousesPage } from './pages/WarehousesPage';
import { MonitoringPage } from './pages/MonitoringPage';
import { OrdersPage } from './pages/OrdersPage';

export default function App() {
  const [route, setRoute] = useState(window.location.hash);
  useEffect(() => {
    const onNavigate = () => { setRoute(window.location.hash); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', onNavigate);
    return () => window.removeEventListener('hashchange', onNavigate);
  }, []);
  return (
    <>
      <header className="commerce-header">
        <a className="brand" href="#/orders">Canals<span className="brand-divider">/</span>Commerce</a>
        <nav aria-label="Main navigation">
          <a href="#/orders" aria-current={!route.startsWith('#/warehouses') && !route.startsWith('#/monitoring') ? 'page' : undefined}>Orders</a>
          <a href="#/warehouses" aria-current={route.startsWith('#/warehouses') ? 'page' : undefined}>Stock</a>
          <a href="#/monitoring" aria-current={route.startsWith('#/monitoring') ? 'page' : undefined}>Monitoring</a>
        </nav>
      </header>
      {route.startsWith('#/monitoring') ? <MonitoringPage key={route} route={route} /> : route.startsWith('#/warehouses') ? <WarehousesPage key={route} route={route} /> : <OrdersPage key={route} route={route} />}
    </>
  );
}
