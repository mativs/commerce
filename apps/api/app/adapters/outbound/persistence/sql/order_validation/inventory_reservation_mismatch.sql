-- Compares inventory expected by active fulfillment orders with stock.reserved.
-- A FULL JOIN also reports missing stock rows and stock rows with no matching order demand.
-- Warehouse and product IDs identify the mismatched reservation bucket.
WITH expected AS
    ( SELECT o.warehouse_id,
             i.product_id,
             sum(i.quantity::bigint) AS quantity
     FROM orders o
     JOIN order_items i ON i.order_id=o.id
     WHERE o.status IN ('BOOKED',
                        'PAYING',
                        'PAID')
         AND o.warehouse_id IS NOT NULL
     GROUP BY o.warehouse_id,
              i.product_id)
SELECT coalesce(e.warehouse_id,s.warehouse_id) AS warehouse_id,
       coalesce(e.product_id,s.product_id) AS product_id,
       jsonb_build_object('expected', coalesce(e.quantity,0), 'actual', coalesce(s.reserved,0), 'stock_row_missing', s.id IS NULL) AS evidence
FROM expected e
FULL JOIN stock s USING (warehouse_id,
                         product_id)
WHERE coalesce(e.quantity,0) <> coalesce(s.reserved,0)
