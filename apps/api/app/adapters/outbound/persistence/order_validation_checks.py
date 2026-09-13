"""Each check observes a single PostgreSQL statement snapshot; evidence excludes PII."""

ORDER_TOTAL = """
SELECT o.id AS order_id, jsonb_build_object(
    'expected', coalesce(sum(i.quantity::numeric * i.unit_price), 0)::text,
    'actual', o.total_amount::text) AS evidence
FROM orders o LEFT JOIN order_items i ON i.order_id=o.id
GROUP BY o.id HAVING o.total_amount <> coalesce(sum(i.quantity::numeric * i.unit_price), 0)
"""


def stale(status: str, threshold: str) -> str:
    return f"""
    SELECT o.id AS order_id, jsonb_build_object('status', o.status,
        'status_since', h.created_at,
        'threshold_seconds', CAST(:{threshold} AS integer)) AS evidence
    FROM orders o JOIN LATERAL (
        SELECT status, created_at FROM order_status_history WHERE order_id=o.id
        ORDER BY created_at DESC, id DESC LIMIT 1
    ) h ON h.status=o.status
    WHERE o.status='{status}'
      AND h.created_at < CAST(:as_of AS timestamptz)
        - CAST(:{threshold} AS integer) * interval '1 second'
    """


INVENTORY = """
WITH expected AS (
    SELECT o.warehouse_id, i.product_id, sum(i.quantity::bigint) AS quantity
    FROM orders o JOIN order_items i ON i.order_id=o.id
    WHERE o.status IN ('BOOKED','PAYING','PAID') AND o.warehouse_id IS NOT NULL
    GROUP BY o.warehouse_id, i.product_id
)
SELECT coalesce(e.warehouse_id,s.warehouse_id) AS warehouse_id,
       coalesce(e.product_id,s.product_id) AS product_id,
       jsonb_build_object('expected', coalesce(e.quantity,0),
                          'actual', coalesce(s.reserved,0),
                          'stock_row_missing', s.id IS NULL) AS evidence
FROM expected e FULL JOIN stock s USING (warehouse_id,product_id)
WHERE coalesce(e.quantity,0) <> coalesce(s.reserved,0)
"""

STRUCTURE = """
SELECT o.id AS order_id, jsonb_build_object(
    'empty_items', NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.id),
    'missing_warehouse', o.status IN ('BOOKED','PAYING','PAID') AND o.warehouse_id IS NULL,
    'missing_coordinates', o.status IN ('BOOKED','PAYING','PAID')
        AND (o.latitude IS NULL OR o.longitude IS NULL),
    'invalid_items', EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.id
        AND (i.quantity<=0 OR i.unit_price<0 OR i.unit_price='Infinity'::numeric))
) AS evidence FROM orders o
WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.id)
   OR (o.status IN ('BOOKED','PAYING','PAID')
       AND (o.warehouse_id IS NULL OR o.latitude IS NULL OR o.longitude IS NULL))
   OR EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.id
       AND (i.quantity<=0 OR i.unit_price<0 OR i.unit_price='Infinity'::numeric))
"""

HISTORY = """
WITH transitions AS (
    SELECT *, lag(status) OVER (PARTITION BY order_id ORDER BY created_at,id) AS previous
    FROM order_status_history
), invalid AS (
    SELECT DISTINCT order_id FROM transitions
    WHERE (previous IS NULL AND status <> 'CREATED') OR
      (previous IS NOT NULL AND NOT (
        (previous='CREATED' AND status IN ('BOOKED','CANCELLED')) OR
        (previous='BOOKED' AND status IN ('PAYING','PAID','CANCELLED')) OR
        (previous='PAYING' AND status IN ('PAID','CANCELLED'))))
      OR (status='CANCELLED' AND nullif(btrim(reason),'') IS NULL)
)
SELECT o.id AS order_id, jsonb_build_object('current_status',o.status,
    'latest_history_status',h.status, 'invalid_history',v.order_id IS NOT NULL,
    'failure_reason',o.failure_reason, 'history_reason',h.reason) AS evidence
FROM orders o LEFT JOIN LATERAL (
    SELECT status,reason FROM order_status_history WHERE order_id=o.id
    ORDER BY created_at DESC,id DESC LIMIT 1
) h ON true LEFT JOIN invalid v ON v.order_id=o.id
WHERE h.status IS DISTINCT FROM o.status OR v.order_id IS NOT NULL
   OR (o.status='CANCELLED' AND
       (nullif(btrim(o.failure_reason),'') IS NULL OR h.reason IS DISTINCT FROM o.failure_reason))
   OR (o.status<>'CANCELLED' AND o.failure_reason IS NOT NULL)
"""

# BOOKED -> PAID remains valid for historical orders created before PAYING existed.
CHECKS: dict[str, tuple[str, str]] = {
    "ORDER_TOTAL_MISMATCH": (ORDER_TOTAL, "ERROR"),
    "ORDER_STUCK_CREATED": (stale("CREATED", "created_age_seconds"), "WARNING"),
    "PAYMENT_NOT_STARTED": (stale("BOOKED", "booked_age_seconds"), "WARNING"),
    "PAYMENT_PENDING_TOO_LONG": (stale("PAYING", "payment_age_seconds"), "WARNING"),
    "PAID_WITHOUT_REFERENCE": (
        "SELECT id AS order_id, jsonb_build_object('status',status,"
        "'payment_reference_missing',true) AS evidence FROM orders "
        "WHERE status='PAID' AND nullif(btrim(payment_identifier),'') IS NULL",
        "ERROR",
    ),
    "INVENTORY_RESERVATION_MISMATCH": (INVENTORY, "ERROR"),
    "INVALID_ORDER_STRUCTURE": (STRUCTURE, "ERROR"),
    "INCONSISTENT_STATUS_HISTORY": (HISTORY, "ERROR"),
}
