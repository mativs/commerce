import { useEffect, useState } from 'react';
import { resetDemoData } from './api/client';
import { WarehousesPage } from './pages/WarehousesPage';
import { MonitoringPage } from './pages/MonitoringPage';
import { OrdersPage } from './pages/OrdersPage';

export default function App() {
  const [route, setRoute] = useState(window.location.hash);
  const [resetting, setResetting] = useState(false);
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
        <button className="reset-demo-button" disabled={resetting} onClick={async () => {
          const confirmation = window.prompt('This deletes all demo orders and restores the initial data. Type RESET to continue.');
          if (confirmation !== 'RESET') return;
          setResetting(true);
          try {
            await resetDemoData();
            window.sessionStorage.clear();
            window.location.hash = '#/orders';
            window.location.reload();
          } catch (error) {
            window.alert(error instanceof Error ? error.message : 'Could not reset demo data.');
          } finally { setResetting(false); }
        }}>{resetting ? 'Resetting…' : 'Reset demo data'}</button>
      </header>
      {route.startsWith('#/monitoring') ? <MonitoringPage key={route} route={route} /> : route.startsWith('#/warehouses') ? <WarehousesPage key={route} route={route} /> : <OrdersPage key={route} route={route} />}
    </>
  );
}
