# Order checkout

`POST /orders` accepts the complete address and items. Send a unique `Idempotency-Key`
header for each new order; reuse it with the same payload after a network failure.
Duplicate products are combined after each quantity is validated. Prices and totals
are calculated from active USD products; status, warehouse, prices, and coordinates
are not accepted as input.

```json
{
  "customer": {
    "first_name": "Ana",
    "last_name": "Pérez",
    "phone": "+54 223 555 0100",
    "email": "ana@example.com"
  },
  "shipping_address": {
    "recipient_name": "Ana Pérez",
    "address_line1": "San Martín 2500",
    "city": "Mar del Plata",
    "state": "Buenos Aires",
    "postal_code": "B7600",
    "country_code": "AR"
  },
  "items": [{"product_id": 1, "quantity": 2}],
  "notes": "Ring the bell",
  "credit_card_number": "4242424242424242",
  "payment_description": "Demo checkout"
}
```

- `201`: the order is saved and is `PAID` or `CANCELLED`. Inspect `failure_reason`
  for `GEOCODING_FAILED`, `OUT_OF_STOCK`, or `PAYMENT_FAILED`.
- `202`: the saved order is still `CREATED` or `BOOKED`. A replay observes its current
  state without starting another checkout. A payment with an unknown outcome stays
  `BOOKED` and retains its reservation.
- `409`: this key was already used with different input.
- `422`: invalid input or an unavailable/non-USD product; no order is created.

`Location` identifies `GET /orders/{id}`, which includes items and chronological
status history and, after payment, the provider's payment reference. The card number
is never returned. `GET /orders?limit=50&offset=0` lists newest orders first. Editing,
manual status changes, and deletion endpoints are not part of this operation.

Order creation, captured item prices, and the total commit together. Geocoding runs
outside the transaction and saves coordinates on the order's address snapshot.
Candidates must fulfill all items and are ranked by Haversine distance, then warehouse
ID. Each candidate is rechecked with ordered inventory locks in its own transaction;
booking and reservation commit together before payment starts. Payment success retains
reserved physical inventory until a future shipment. A definitive rejection releases
it and records cancellation in one transaction. Status history is written by the
existing database trigger, with a reason for cancellation.

Shipping details belong to the order snapshot; there is no separate saved-address model or CRUD.
Checkout uses a separate mock instance so its simulated failures do not affect other API operations.

Both external services use async ports and mock outbound adapters. Checkout geocoding fails
with probability 1/5. Payment waits two seconds and uses a stable pseudo-random
outcome with approximately 1/5 declines, keyed by the idempotency key so retries do
not change its outcome. No real payment is made.

There is no recovery worker yet. A crash after creation can leave `CREATED`; a crash
or unknown payment outcome after reservation can leave `BOOKED`. Reusing the POST
key or reading the order observes that state; it does not resume processing. Future
recovery must reconcile payment using the same key before releasing reservations.
Unexpected database errors roll back the current transaction, not earlier committed
steps. Never blindly cancel a potentially charged order.

Migration `0010` adds demo stock automatically with `make migrate`. With the original
five warehouses and 100 active USD products, each warehouse receives 64 different
products with 5–50 units each and no reservations. Ten products are shared by every
warehouse; the rest appear in three warehouses, allowing warehouse selection and
unavailable-order scenarios. Existing stock balances are preserved.
