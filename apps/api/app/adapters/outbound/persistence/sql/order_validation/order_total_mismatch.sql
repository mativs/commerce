-- Finds orders whose stored total differs from the sum of their item snapshots.
-- One finding is returned per order, with both totals preserved as evidence.
SELECT o.id AS order_id,
       jsonb_build_object( 'expected', coalesce(sum(i.quantity::numeric * i.unit_price), 0)::text, 'actual', o.total_amount::text) AS evidence
FROM orders o
LEFT JOIN order_items i ON i.order_id=o.id
GROUP BY o.id
HAVING o.total_amount <> coalesce(sum(i.quantity::numeric * i.unit_price), 0)
