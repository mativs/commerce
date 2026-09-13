-- Finds orders that have remained in the supplied status longer than allowed.
-- The runner binds :status, :as_of, and :threshold_seconds for each status-specific check.
-- The latest history row is used so the age reflects the current status transition.
SELECT o.id AS order_id,
       jsonb_build_object('status', o.status, 'status_since', h.created_at, 'threshold_seconds', CAST(:threshold_seconds AS integer)) AS evidence
FROM orders o
JOIN LATERAL
    ( SELECT status,
             created_at
     FROM order_status_history
     WHERE order_id=o.id
     ORDER BY created_at DESC, id DESC
     LIMIT 1) h ON h.status=o.status
WHERE o.status=:status
    AND h.created_at < CAST(:as_of AS timestamptz) - CAST(:threshold_seconds AS integer) * interval '1 second'
