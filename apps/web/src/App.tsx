import { useEffect, useState } from 'react';
import { ProductsPage } from './pages/ProductsPage';
import { WarehousesPage } from './pages/WarehousesPage';
import { OrdersPage } from './pages/OrdersPage';

export default function App() {
  const [route, setRoute] = useState(window.location.hash);
  useEffect(() => {
    const onNavigate = () => { setRoute(window.location.hash); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', onNavigate);
    return () => window.removeEventListener('hashchange', onNavigate);
  }, []);
  const admin = route.startsWith('#/admin');
  return (
    <>
      <header className="commerce-header">
        <a className="brand" href="#/orders">Canals<span className="brand-divider">/</span>Commerce</a>
        <nav aria-label="Main navigation">
          <a href="#/orders" aria-current={!admin ? 'page' : undefined}>Orders</a>
          <a href="#/admin/warehouses" aria-current={admin ? 'page' : undefined}>Admin</a>
        </nav>
      </header>
      {admin && <nav className="admin-tabs" aria-label="Admin sections">
        <a href="#/admin/warehouses" aria-current={route === '#/admin/warehouses' ? 'page' : undefined}>Warehouses</a>
        <a href="#/admin/products" aria-current={route === '#/admin/products' ? 'page' : undefined}>Products</a>
      </nav>}
      {admin ? (route === '#/admin/products' ? <ProductsPage /> : <WarehousesPage />) : <OrdersPage key={route} route={route} />}
    </>
  );
}
