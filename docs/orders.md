# Order checkout

`POST /orders` accepts the complete address and items. Send a unique `Idempotency-Key`
header for each new order; reuse it with the same payload after a network failure. This
client-owned key identifies the order request only. Payment uses a separate, server-owned
idempotency key derived from the saved order ID, so clients cannot choose or collide with
payment identities.
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
Both external services use async ports and mock outbound adapters. Geocoding returns a sample Mar del Plata location. Payment waits two seconds
and always succeeds, with a stable provider reference keyed by the idempotency key
so retries return the same reference. No real payment is made.

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


### Simulating failures

Simulations are always enabled for this exercise. Include a plain keyword anywhere
in order notes (for example, `Please test payment-declined`). Matching ignores case
and requires a complete keyword; if several appear, the first one wins.

| Keyword | Result |
| --- | --- |
| `geocoding-timeout` | Cancelled with `GEOCODING_FAILED`; no payment attempted. |
| `payment-declined` | Cancelled with `PAYMENT_FAILED`; reserved stock released. |
| `payment-timeout` | Remains `BOOKED` (HTTP 202); reserved stock retained. |
| `payment-failed` | Provider unavailable; remains `BOOKED` (HTTP 202), stock retained. |

Without a recognized keyword, mock payments succeed. Timeout markers raise the
same exception handled by the service immediately, without waiting ten seconds.
An unavailable provider has an unknown payment outcome, so it cannot safely cancel
the order. Out-of-stock and reservation failures use actual inventory conditions.

`app/infrastructure/order_simulation.py` composes per-invocation adapter wrappers,
wired in the HTTP dependency factory. The order service and SQL repository contain
no simulation logic. Notes remain saved on the order; retries with the same
idempotency key observe the saved result without rerunning the scenario.
