-- Reconstructs each order's status transitions and compares them with the allowed state machine.
-- The same history scan identifies the latest row, avoiding a separate per-order lookup.
-- It also checks that the current order and cancellation reason agree with that history.
WITH ranked_history AS (
    SELECT
        h.order_id,
        h.status,
        h.reason,
        h.created_at,
        h.id,
        lag(h.status) OVER (
            PARTITION BY h.order_id
            ORDER BY h.created_at, h.id
        ) AS previous,
        row_number() OVER (
            PARTITION BY h.order_id
            ORDER BY h.created_at DESC, h.id DESC
        ) AS latest_rank
    FROM order_status_history h
),
invalid AS (
    SELECT DISTINCT order_id
    FROM ranked_history
    WHERE (previous IS NULL AND status <> 'CREATED')
       OR (
            previous IS NOT NULL
            AND NOT (
                (previous = 'CREATED' AND status IN ('BOOKED', 'CANCELLED'))
                OR (previous = 'BOOKED' AND status IN ('PAYING', 'PAID', 'CANCELLED'))
                OR (previous = 'PAYING' AND status IN ('PAID', 'CANCELLED'))
            )
       )
       OR (status = 'CANCELLED' AND nullif(btrim(reason), '') IS NULL)
),
latest AS (
    SELECT order_id, status, reason
    FROM ranked_history
    WHERE latest_rank = 1
)
SELECT
    o.id AS order_id,
    jsonb_build_object(
        'current_status', o.status,
        'latest_history_status', h.status,
        'invalid_history', v.order_id IS NOT NULL,
        'failure_reason', o.failure_reason,
        'history_reason', h.reason
    ) AS evidence
FROM orders o
LEFT JOIN latest h ON h.order_id = o.id
LEFT JOIN invalid v ON v.order_id = o.id
WHERE h.status IS DISTINCT FROM o.status
   OR v.order_id IS NOT NULL
   OR (
        o.status = 'CANCELLED'
        AND (
            nullif(btrim(o.failure_reason), '') IS NULL
            OR h.reason IS DISTINCT FROM o.failure_reason
        )
   )
   OR (o.status <> 'CANCELLED' AND o.failure_reason IS NOT NULL)
