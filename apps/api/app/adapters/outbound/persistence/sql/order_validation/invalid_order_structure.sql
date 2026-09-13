-- Checks structural invariants that should hold as an order advances through fulfillment.
-- Item facts are aggregated once so the evidence and filter use the same values.
-- Evidence identifies missing items, warehouse/coordinates, or invalid item values.
WITH item_flags AS (
    SELECT
        order_id,
        bool_or(
            quantity <= 0
            OR unit_price < 0
            OR unit_price = 'Infinity'::numeric
        ) AS invalid_items
    FROM order_items
    GROUP BY order_id
)
SELECT
    o.id AS order_id,
    jsonb_build_object(
        'empty_items', flags.order_id IS NULL,
        'missing_warehouse',
            o.status IN ('BOOKED', 'PAYING', 'PAID')
            AND o.warehouse_id IS NULL,
        'missing_coordinates',
            o.status IN ('BOOKED', 'PAYING', 'PAID')
            AND (o.latitude IS NULL OR o.longitude IS NULL),
        'invalid_items', coalesce(flags.invalid_items, false)
    ) AS evidence
FROM orders o
LEFT JOIN item_flags flags ON flags.order_id = o.id
WHERE flags.order_id IS NULL
   OR (
        o.status IN ('BOOKED', 'PAYING', 'PAID')
        AND (
            o.warehouse_id IS NULL
            OR o.latitude IS NULL
            OR o.longitude IS NULL
        )
   )
   OR coalesce(flags.invalid_items, false)
