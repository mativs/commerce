import { useEffect, useState } from 'react';
import { ShippingAddressesPage } from './pages/ShippingAddressesPage';
import { ProductsPage } from './pages/ProductsPage';
import { WarehousesPage } from './pages/WarehousesPage';

function currentSection() {
  if (window.location.hash === '#/admin/products') return 'products';
  return window.location.hash === '#/admin/shipping-addresses' ? 'shipping-addresses' : 'warehouses';
}

export default function App() {
  const [section, setSection] = useState(currentSection);
  useEffect(() => {
    const onNavigate = () => setSection(currentSection());
    window.addEventListener('hashchange', onNavigate);
    return () => window.removeEventListener('hashchange', onNavigate);
  }, []);

  return (
    <>
      <header className="admin-header">
        <a className="brand" href="#/admin/warehouses">Canals Commerce <span>Admin</span></a>
        <nav aria-label="Admin sections">
          <a href="#/admin/warehouses" aria-current={section === 'warehouses' ? 'page' : undefined}>Warehouses</a>
          <a href="#/admin/shipping-addresses" aria-current={section === 'shipping-addresses' ? 'page' : undefined}>Shipping addresses</a>
          <a href="#/admin/products" aria-current={section === 'products' ? 'page' : undefined}>Products</a>
        </nav>
      </header>
      {section === 'products' ? <ProductsPage /> : section === 'warehouses' ? <WarehousesPage /> : <ShippingAddressesPage />}
    </>
  );
}
