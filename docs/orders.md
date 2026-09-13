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
- `202`: the saved order is still `CREATED`, `BOOKED`, or `PAYING`. A replay observes its current
  state without starting another checkout. A payment with an unknown outcome stays
  `PAYING` and retains its reservation.
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
or unknown payment outcome after reservation can leave `PAYING`. Reusing the POST
key or reading the order observes that state; it does not resume processing. Future
recovery must reconcile payment using the same key before releasing reservations.
Unexpected database errors roll back the current transaction, not earlier committed
steps. Never blindly cancel a potentially charged order.

Migration `0010` adds demo stock automatically with `make migrate`. With the original
five warehouses and 10 active USD products, warehouses receive overlapping
assortments with 5–50 units each and no reservations. Two products are shared by every
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
| `payment-timeout` | Remains `PAYING` (HTTP 202); reserved stock retained. |
| `payment-failed` | Provider unavailable; remains `PAYING` (HTTP 202), stock retained. |

Without a recognized keyword, mock payments succeed. Timeout markers raise the
same exception handled by the service immediately, without waiting ten seconds.
An unavailable provider has an unknown payment outcome, so it cannot safely cancel
the order. Out-of-stock and reservation failures use actual inventory conditions.

`app/infrastructure/order_simulation.py` composes per-invocation adapter wrappers,
wired in the HTTP dependency factory. The order service and SQL repository contain
no simulation logic. Notes remain saved on the order; retries with the same
idempotency key observe the saved result without rerunning the scenario.


### Payment initiation and manual validation

New checkouts follow `CREATED → BOOKED → PAYING → PAID`. `PAYING` is committed
immediately before the gateway call; its history timestamp records local initiation,
not confirmation that the provider received the request. Declines cancel with
`PAYMENT_FAILED`; timeouts and unavailable responses remain `PAYING`. `BOOKED`,
`PAYING`, and `PAID` retain stock. Existing `BOOKED` orders are not reclassified.

Trigger a synchronous, read-only order validation run:

```sh
curl -X POST http://localhost:8000/order-validation-runs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: validation-example-1' \
  -d '{}'
```

An empty object runs all checks. To select checks and thresholds:

```json
{
  "checks": ["ORDER_TOTAL_MISMATCH", "PAYMENT_NOT_STARTED", "PAYMENT_PENDING_TOO_LONG"],
  "thresholds": {
    "created_age_seconds": 300,
    "booked_age_seconds": 300,
    "payment_age_seconds": 300
  }
}
```

All thresholds default to 300 seconds and accept 1–604800 seconds. Checks scan all
orders; inventory checks always compare complete warehouse/product totals.

| Check | Finding |
| --- | --- |
| `ORDER_TOTAL_MISMATCH` | Saved total differs from sum of saved unit prices × quantities. |
| `ORDER_STUCK_CREATED` | Latest `CREATED` history entry exceeds its age threshold. |
| `PAYMENT_NOT_STARTED` | Latest `BOOKED` entry exceeds its threshold; no recorded payment initiation. Historical orders may already have attempted payment. |
| `PAYMENT_PENDING_TOO_LONG` | Latest `PAYING` entry exceeds its threshold. |
| `PAID_WITHOUT_REFERENCE` | Paid order has no payment reference. |
| `INVENTORY_RESERVATION_MISMATCH` | Stock reserved differs from `BOOKED` + `PAYING` + `PAID` quantities, including missing stock rows. |
| `INVALID_ORDER_STRUCTURE` | Empty/invalid items, or missing warehouse/coordinates in a stock-holding state. |
| `INCONSISTENT_STATUS_HISTORY` | Invalid transition, missing history, latest/current status mismatch, or inconsistent cancellation reason. Legacy `BOOKED → PAID` remains accepted. |

`POST` returns `201` and `Location` for a new run; replaying the same key and
parameters returns `200` with the existing run. Different parameters with that key,
or another execution holding the database lock, return `409`. Unknown checks return
`422`. A completed execution can contain findings: inspect `finding_count` and each
check, not just the run status.

- `GET /order-validation-runs?limit=50&offset=0`: run history and finding counts.
- `GET /order-validation-runs/{id}`: parameters, timestamps, rules version and checks.
- `GET /order-validation-runs/{id}/findings`: paginated evidence; optional `check`,
  `severity` (`ERROR`/`WARNING`), and `order_id` filters.

Each check commits its findings independently and reads one database statement
snapshot. Different checks may observe different moments during concurrent checkout.
Check statements have a five-second timeout; after the 30-second execution budget,
remaining checks are skipped and the run is partial (or failed if none completed).
An abrupt process failure can leave a running record; the next new invocation marks
abandoned runs interrupted after acquiring the execution lock. There is no scheduler.

This job never charges, cancels, or repairs orders. It does not verify actual provider
transactions, duplicate charges, charged amounts, or currency, and does not create
payment-attempt or reservation tables. Findings contain identifiers and diagnostic
values, not card numbers or customer/address snapshots.

### Monitoring interface

Open **Monitoring** in the main navigation to view saved runs or choose **Run checks**.
The dialog selects all eight checks by default and lets you change stage thresholds
in seconds. Results separate execution status from error/warning totals, summarize
each check, and filter findings by check or severity. Order and warehouse links open
the affected records; observations describe the state at the time of the run.

**Run again** opens the previous selection and thresholds for review. If the POST
response is lost, **Check run status** reuses the saved request identity rather than
creating a duplicate run. That pending identity is retained for the browser tab across
reloads. Running result pages refresh automatically; historical pages offer manual
refresh. No repair or payment actions are exposed.


### Warehouse decision evidence

Migration `0020` adds the nullable `orders.warehouse_decision` JSONB snapshot.
Order create, detail, and list responses expose it for a future order information view.
It records version, evaluation time, strategy, shipping coordinates, selected warehouse
ID, and candidates in selection order. Each candidate includes its warehouse ID and
name, coordinate snapshot, unrounded Haversine distance in kilometers, rank,
reservation outcome, and rejection reason. Distances are great-circle distances,
not driving distances. Equal distances use the lower warehouse ID.

Candidates are the non-deleted warehouses with enough available stock for every
order item at evaluation time; warehouses excluded by this stock query are not included.
The snapshot is saved before reservation. Outcomes start as `NOT_ATTEMPTED`;
each attempt saves `REJECTED` (with `WAREHOUSE_UNAVAILABLE`, `PRODUCT_UNAVAILABLE`,
or `INSUFFICIENT_STOCK`) or `SELECTED` in the same transaction as the reservation.
Candidates after the winner remain `NOT_ATTEMPTED`.

An empty candidate list means evaluation found no eligible warehouse. A null snapshot
means no evidence was recorded (historical order, geocoding failure, or checkout not
yet at selection); historical decisions are not reconstructed. A snapshot with no
selection and unattempted candidates can indicate processing interrupted before
reservation. Payment failure does not erase the selection. Replays and later changes
to warehouse names, coordinates, or stock do not recompute the saved evidence.

The order detail map uses Leaflet and OpenStreetMap tiles without an API key.
It shows saved shipping and candidate coordinates, plus all current warehouses
loaded through the paginated warehouse API. Current warehouses without candidate
evidence are labeled separately; their current locations do not reconstruct historical
eligibility. Selected warehouses and shipping locations have distinct markers, and
popups identify the coordinate source. Map tile failures leave markers and the decision
table available. OpenStreetMap attribution remains visible; browser requests use normal
HTTP caching, with no offline download or bulk prefetch. Public tiles are best-effort
and subject to https://operations.osmfoundation.org/policies/tiles/.
