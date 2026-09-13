-- A paid order must retain the provider reference needed for reconciliation.
-- Blank and whitespace-only values are treated as missing references.
SELECT id AS order_id,
       jsonb_build_object('status',status, 'payment_reference_missing',TRUE) AS evidence
FROM orders
WHERE status='PAID'
    AND nullif(btrim(payment_identifier),'') IS NULL
