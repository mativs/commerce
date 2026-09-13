# How order creation works

`POST /orders` accepts a customer, shipping address, items, and demo payment details. It saves the order, finds a warehouse that can fulfill every item, reserves stock, and attempts payment.

**No duplicate orders. No duplicate payments. Consistent inventory balances.** Physical stock, reservations, and availability must remain consistent under concurrent checkouts, retries, and failures. An unknown payment outcome must not release inventory. These requirements determine the transaction boundaries and retry behavior.

Checkout runs synchronously within the HTTP request. Each database stage commits independently; external calls run between transactions. There is no queue, webhook handler, or recovery worker. The lifecycle makes interrupted work visible, but recovery is still unimplemented.

```text
CREATED → BOOKED → PAYING → PAID
    │         │        │
    └─────────┴────────┴────→ CANCELLED
```

| Status | What is known | Stock reserved? |
| --- | --- | --- |
| `CREATED` | Order, items, captured prices, and total are saved. Fulfillment is incomplete. | No |
| `BOOKED` | One warehouse has reserved every item. | Yes |
| `PAYING` | Local payment initiation was recorded. The provider's outcome may be unknown. | Yes |
| `PAID` | Payment success and its reference were saved. | Yes, until a future shipment |
| `CANCELLED` | Checkout ended with a definitive failure reason. | No |

`BOOKED → CANCELLED` is supported by the repository. In the normal checkout flow, a payment rejection occurs after `PAYING` has committed.

## Try one request

Follow the [README setup](../README.md#run-locally) first. It starts the app and applies migrations, including five warehouses, ten USD products, and demo stock.

This example requires `curl` and available stock for product `1`, which exists in a fresh database:

```sh
curl -i -X POST http://localhost:8000/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: order-guide-1' \
  --data-binary @- <<'JSON'
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
JSON
```

Expect `201`, `status: "PAID"`, a total of `"119.98"` with the original seeded price, a payment reference, and all four success stages in `history`. The mock payment waits about two seconds. It makes no real charge.

Repeat the command unchanged: it returns the same order ID without reserving or paying again. Change the quantity while keeping the key: expect `409`. Use a new key for a new order. For an existing database with depleted stock, use the UI's **Fill with test data** presets, which inspect current availability.

## The inventory rules every stage must preserve

For each warehouse/product pair:

```text
0 <= reserved <= on_hand
available = on_hand - reserved
reserved = sum of item quantities held by BOOKED, PAYING, and PAID orders
```

`on_hand` is the recorded physical quantity. Reserving stock increases `reserved`; releasing it decreases `reserved`. Neither operation changes `on_hand`. Availability is calculated from the two balances, so there is no third stored counter to drift out of sync.

PostgreSQL constraints reject negative balances and reservations above physical stock. Transactions and row locks keep reservation changes consistent with order state. Monitoring independently compares reserved balances with the orders that hold them; the per-row constraints alone cannot enforce that cross-table agreement.

**A displayed stock count is a snapshot, not permission to sell.** Another checkout may reserve units immediately after a read. Every reservation rereads the current balances under exclusive locks and validates the complete order before changing stock. Retries, declines, and rollbacks must preserve these same rules.

These guarantees concern the recorded inventory. The demo does not synchronize with a warehouse system, verify physical counts, or process receipts and shipments. Those integrations would need to preserve the same invariants.

## 1. Validate and normalize the request

[The HTTP adapter](../apps/api/app/adapters/inbound/http/orders.py) validates input before handing a command to the application service.

- `Idempotency-Key` is mandatory: 1–128 visible ASCII characters, without spaces.
- Customer, shipping address, at least one item, card number, and payment description are required. Unknown fields are rejected, including client-supplied prices, totals, coordinates, status, or warehouse selection.
- Product IDs and quantities must be integers from `1` to `2147483647`. The request accepts at most 1,000 item entries.
- Each quantity is validated **before** duplicate product entries are combined. Two entries for the same product become one item with their summed quantity; the combined quantity must also fit the limit.
- Strings are trimmed where specified by the input models. Customer email is lowercased; country code is uppercased. Items are sorted by product ID.

Invalid input returns `422` before an order is created. Product existence and eligibility are checked inside the next transaction.

**Decision:** the server owns price, fulfillment, and status. Accepting them from the browser would let a request bypass the rules that make checkout correct. FastAPI and Pydantic keep this validation and the [interactive API contract](http://localhost:8000/docs) together.

## 2. Claim the request and save the order

The service generates a server-owned payment key, `payment:<UUID>`. The repository opens a transaction and attempts to insert the order with:

- The client order key and a SHA-256 fingerprint of the normalized command.
- The separate payment key.
- The shipping snapshot, notes, and demo payment details.
- Initial status `CREATED`.

A unique database constraint arbitrates concurrent requests using the same order key. Only the request that inserts the order continues checkout.

| Existing key | Result |
| --- | --- |
| Same normalized command | Read the saved order under a shared lock and return its current state. |
| Different normalized command | Return `409 Conflict`. |

The fingerprint includes customer, shipping, items, notes, and payment input. Retrying with the same body is the simplest way to preserve identity. A newly generated payment key on a replay is discarded; the saved order keeps its original payment identity.

**Decision:** deduplication belongs in PostgreSQL. An application-side “does this key exist?” check would race with another request. The unique constraint makes ownership of the request atomic.

For a new order, the same transaction then:

1. Takes shared product locks in product-ID order and checks that every product exists, is active, and is not deleted.
2. Inserts the order items. A database trigger copies each product's current price into `unit_price`.
3. Calculates `total_amount` from saved unit prices and quantities using Python `Decimal`.
4. Commits the order, items, total, and initial status history together.

Unavailable products or an unsupported total return `422` and roll back this entire transaction. No partial order or consumed idempotency key remains.

**Decision:** prices are facts about the purchase. They are captured once and protected against later changes. PostgreSQL `NUMERIC` stores two decimal places; USD is assumed throughout, with no currency field. Product names still come from the current catalog, so renaming a product changes its displayed name on older orders. Snapshotting names would be a separate improvement.

The assessment stores test card numbers in the database and temporarily in browser session storage for pending retries. API responses omit them. Real payment integration requires provider tokenization.

## 3. Attach the customer

A separate transaction locks the order and links it to a customer identified by normalized email. If no customer exists, it inserts one. If the email already exists, it reuses that customer's ID; **it does not overwrite the existing name or phone**.

**Decision:** customer identity is shared across purchases. Delivery details belong to the individual order and remain a shipping snapshot. There is no separate saved-address CRUD model.

This step commits after order creation. A crash between the two transactions can leave a `CREATED` order without a customer link. That is one of the boundaries a future recovery process must handle.

## 4. Locate the shipping address

The service calls the geocoder outside any database transaction, with a ten-second timeout. On success, a short transaction locks the order and saves its latitude and longitude. The order remains `CREATED`.

The current mock ignores the address and returns a sample Mar del Plata location. Repeated new orders for the same address can receive different sample coordinates. Replays keep the coordinates already saved on the order.

A geocoding timeout or unavailable response cancels the order with `GEOCODING_FAILED`. No inventory has been reserved and no payment is attempted.

**Decision:** a slow external service must not hold database locks. The geocoder is an async interface with a mock adapter, so a real provider can be added without moving HTTP concerns into checkout rules.

## 5. Rank warehouses and save the evidence

The repository finds non-deleted warehouses with enough available stock for **every** requested item:

```text
available = on_hand - reserved
```

Stock has one row per warehouse/product pair. A missing row cannot satisfy an item. Stock distributed across several warehouses cannot satisfy a single order: split fulfillment is outside the scope.

The service ranks eligible candidates by Haversine distance from the saved shipping coordinates, then by warehouse ID to break ties. Haversine gives great-circle distance in kilometers. It does not estimate driving distance, delivery time, or shipping cost.

**Decision:** this gives a deterministic ranking for the evaluated coordinates without a routing API. One warehouse per order keeps reservation and fulfillment rules small and explicit.

Before trying to reserve, another transaction saves `warehouse_decision`, a versioned JSONB snapshot containing the evaluation timestamp, strategy, shipping coordinates, and ranked candidates. Each candidate records its ID, name, coordinates, unrounded distance, rank, reservation outcome, and rejection reason.

**A candidate is not a reservation.** Another checkout can consume its stock after evaluation. The next step must recheck availability under locks.

The evidence has precise limits:

- Only warehouses eligible at evaluation time appear as candidates. The snapshot does not explain every excluded warehouse.
- Candidates begin as `NOT_ATTEMPTED`. Reservation attempts change them to `REJECTED` or `SELECTED`; candidates after the winner stay `NOT_ATTEMPTED`.
- An empty candidate list means none qualified. A null snapshot means no decision was recorded, such as a historical order, geocoding failure, or interruption before selection.
- Replays and later warehouse changes do not recompute the evidence. Payment failure does not erase it.

The order detail table and Leaflet map display this evidence. The map also shows current warehouse locations, labeled separately from saved candidate coordinates. Current data cannot reconstruct historical eligibility. OpenStreetMap tiles need internet access; markers and the table remain available if tiles fail.

## 6. Reserve all items at one warehouse

Each candidate gets its **own transaction**. The repository:

1. Exclusively locks the order and requires `CREATED`.
2. Takes a shared lock on the warehouse and verifies it still exists and is not deleted.
3. Takes shared product locks in product-ID order and rechecks product eligibility.
4. Exclusively locks the matching stock rows in product-ID order and rereads their balances.
5. Verifies that every item has enough available stock before changing any balance.
6. Increases each row's `reserved` quantity, assigns the warehouse, records `SELECTED`, and changes the order to `BOOKED`.
7. Commits all those changes together.

Physical `on_hand` stock does not change. Reservation reduces availability by increasing `reserved`.

**Decision:** checking all items before updating any of them prevents partial booking. Committing the reservation and `BOOKED` together prevents an order from claiming stock it does not hold. Consistent stock-lock ordering avoids competing checkouts acquiring the same rows in opposite orders. Shared catalog locks let checkouts coexist while protecting the data they depend on.

If a candidate fails, its rejection evidence commits without changing stock:

| Reason | What changed or was missing |
| --- | --- |
| `WAREHOUSE_UNAVAILABLE` | Warehouse no longer eligible. |
| `PRODUCT_UNAVAILABLE` | At least one product is missing, inactive, or deleted. |
| `INSUFFICIENT_STOCK` | A stock row is missing or available quantity is too low. |

That transaction ends before the next candidate is tried, releasing its locks. The service uses the original ranked candidate list; it does not discover newly eligible warehouses during retries. If no candidate succeeds, it cancels with `OUT_OF_STOCK`.

## 7. Record payment initiation, then call the provider

A short transaction locks the order, requires `BOOKED`, and commits `PAYING`. Only then does the service call the payment gateway, outside the transaction, with:

- The saved order total.
- The request's payment details.
- The server-generated payment identity saved at creation.
- A ten-second timeout.

**`PAYING` proves local intent, not provider receipt.** The process can crash after committing that state but before sending the request. It can also lose the response after the provider has charged successfully. The same local state can represent either situation.

The mock waits two seconds, succeeds, and derives a stable payment reference from the payment key. No money moves. A real gateway must honor the idempotency key; database uniqueness cannot by itself prevent duplicate charges inside an external system.

**Decision:** order identity and payment identity serve different purposes. The client identifies a checkout request. The server identifies the corresponding charge. Reusing an order key returns early, before geocoding, reservation, or payment can run again.

## 8. Finalize what is known

| Gateway outcome | Database action | Inventory |
| --- | --- | --- |
| Success | Lock the order; if still `PAYING`, save the provider reference and set `PAID`. | Keep reserved. |
| Definitive decline | Lock the order and stock, release the reservation, record `PAYMENT_FAILED`, and set `CANCELLED` in one transaction. | Release exactly once. |
| Timeout or provider unavailable | Return the saved `PAYING` order. | Keep reserved. |

**A timeout is not a decline.** Releasing stock after an unknown outcome could sell inventory already paid for by this customer. The cost of preserving it is reduced availability until reconciliation.

Cancellation checks the current state before releasing anything. It locks stock in product-ID order and verifies that the reservation can be released in full. An inconsistent reservation raises an error and rolls back cancellation; it does not silently subtract a partial amount. Already paid or cancelled orders are not cancelled again by this method. Payment finalization only changes orders still in `PAYING`.

**Paid does not mean shipped.** The app has no shipment stage, so `BOOKED`, `PAYING`, and `PAID` all retain reservations. Physical stock remains unchanged throughout checkout.

## History, responses, and interrupted work

Database triggers append status history in the same transaction as each status change. Entries include status, timestamp, and cancellation reason when applicable. `clock_timestamp()` records wall-clock time; history sorts by timestamp and ID. History cannot be updated or deleted, and orders cannot be deleted. Separate database audit triggers record warehouse, product, and stock changes, including reservation and release.

**Decision:** evidence must commit with the change it describes. Application logs help trace requests; durable history explains the order even after logs expire. State checks govern the application's transitions; the history trigger records changes, while monitoring can detect invalid sequences introduced outside that flow.

`GET /orders/{id}` uses a shared order lock while loading its related data.

The order-list read avoids holding locks across per-order hydration: it selects the page, items, history, and customers in batches inside a PostgreSQL `REPEATABLE READ` transaction, so every returned order is assembled from one deliberate snapshot.

| `POST /orders` response | Meaning |
| --- | --- |
| `201` | Saved order is `PAID` or `CANCELLED`. Inspect `status` and `failure_reason`. A replay of a terminal order also returns `201`. |
| `202` | Saved order is `CREATED`, `BOOKED`, or `PAYING`. This does not promise background processing. |
| `409` | Existing key was used with a different normalized command. |
| `422` | Request validation, product eligibility, or supported-total validation failed; this request created no order. |
| Unexpected error / lost response | Earlier stages may already have committed. Retry with the same key and body to learn the saved state. |

Successful order responses include `Location: /orders/{id}`, items, chronological history, warehouse evidence, and the payment reference when recorded. `GET /orders?limit=50&offset=0` lists newest orders first. Lists return arrays, with `limit` from 1–100 and nonnegative `offset`. Editing, manual status changes, and deletion endpoints are not exposed.

### What survives a crash

| Interruption point | Durable state | What a replay does |
| --- | --- | --- |
| Before creation commits | No order from that attempt. | Can create and process the order. |
| After creation, before booking | `CREATED`; customer, coordinates, or decision evidence may be incomplete. | Returns it without resuming. |
| After reservation, before payment initiation | `BOOKED`, with stock reserved. | Returns it without starting payment. |
| After `PAYING`, before finalization | `PAYING`, with stock reserved; provider outcome uncertain. | Returns it without another charge. |
| After finalization, before HTTP response | `PAID` or `CANCELLED`. | Returns the saved result. |

A database error rolls back the current transaction, not earlier commits. A provider can confirm payment while the local order still says `PAYING` if finalization fails.

**Recovery is the missing piece.** A future worker must inspect the saved stage, reconcile any possible charge using the original payment identity, and make guarded state changes. Simply posting the order again does not perform that work. Never replace an uncertain attempt with a new key just to make it proceed.

## Verify failures and concurrency

The [README walkthrough](../README.md#verify-the-behavior) covers the interface. For API testing, use the request above with a fresh order key per scenario and one of these keywords in `notes`:

| Notes keyword | Expected result | Reservation |
| --- | --- | --- |
| No recognized keyword | `201`, `PAID` | Retained |
| `geocoding-timeout` | `201`, `CANCELLED`, `GEOCODING_FAILED` | Never taken |
| `payment-declined` | `201`, `CANCELLED`, `PAYMENT_FAILED` | Released |
| `payment-timeout` | `202`, `PAYING` | Retained |
| `payment-failed` | `202`, `PAYING`; provider unavailable | Retained |

Payment scenarios require a successful reservation first. To verify out-of-stock behavior, choose **No stock** in the UI; it requests more units than any warehouse can supply and should return `CANCELLED` with `OUT_OF_STOCK`.

Keywords are case-insensitive, must be complete keywords, and the first match in the notes wins. Simulated timeouts raise immediately rather than waiting ten seconds. Per-invocation adapter wrappers implement these scenarios; checkout rules and SQL contain no simulation branches. Simulations are always enabled for this assessment.

Demo stock is finite. Migration `0010` seeds overlapping assortments with 5–50 units per stocked pair: two products appear in all five warehouses, and the remaining products appear in three. Migrations preserve existing balances. Paid and pending orders consume availability, so rerunning migrations does not reset the demo.

After setup, from the repository root:

```sh
make test
```

The existing PostgreSQL tests verify behavior that is difficult to prove by clicking twice:

| Behavior | Test in [test_orders.py](../apps/api/tests/test_orders.py) |
| --- | --- |
| Same-key concurrent requests process once | `test_concurrent_requests_same_key_only_process_once` |
| Competing checkouts cannot oversell; payment holds no stock locks | `test_payment_does_not_hold_stock_locks_and_no_overselling` |
| Stale candidates fall back; release happens once | `test_stale_candidates_fall_back_and_release_once` |
| Missing inventory cannot partially reserve an order | `test_missing_stock_cannot_partially_book` |
| Failed cancellation rolls back stock and history together | `test_failed_finalization_rolls_back_stock_and_history` |
| Warehouse evidence survives later changes | `test_decision_records_fallback_and_survives_warehouse_changes` |

Tests create and remove temporary schemas against the migrated database. `make check` also runs lint, formatting, TypeScript checks, and the web build. See [automated checks](../README.md#automated-checks) for the full setup and coverage boundaries.

## Monitor what checkout leaves behind

Monitoring detects stalled work and inconsistent data. It saves reports; it never charges, cancels, releases stock, or repairs orders.

Open **Monitoring → Run checks**, or run:

```sh
curl -i -X POST http://localhost:8000/order-validation-runs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: validation-guide-1' \
  -d '{}'
```

An empty object runs all eight checks. To select checks and thresholds, use:

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

Thresholds default to 300 seconds and accept 1–604800. Checks scan all orders; inventory comparison uses complete warehouse/product totals.

| Check | Finding |
| --- | --- |
| `ORDER_TOTAL_MISMATCH` | Saved total differs from saved unit prices × quantities. |
| `ORDER_STUCK_CREATED` | Latest `CREATED` stage exceeds its threshold. |
| `PAYMENT_NOT_STARTED` | Latest `BOOKED` stage exceeds its threshold without recorded payment initiation. |
| `PAYMENT_PENDING_TOO_LONG` | Latest `PAYING` stage exceeds its threshold. |
| `PAID_WITHOUT_REFERENCE` | Paid order lacks a payment reference. |
| `INVENTORY_RESERVATION_MISMATCH` | Reserved stock differs from quantities held by `BOOKED`, `PAYING`, and `PAID` orders, including missing stock rows. |
| `INVALID_ORDER_STRUCTURE` | Items are empty/invalid, or a stock-holding order lacks a warehouse or coordinates. |
| `INCONSISTENT_STATUS_HISTORY` | Missing history, invalid transition, current/latest status mismatch, or inconsistent cancellation reason. |

Historical `BOOKED → PAID` transitions remain valid. Older `BOOKED` orders may already have attempted payment; introducing `PAYING` did not reclassify them.

**Completed means execution finished, not that orders are healthy.** Inspect `finding_count`, error/warning totals, and each check's result. Findings preserve identifiers and diagnostic values, excluding customer/address snapshots and card numbers. They do not verify provider transactions, duplicate charges, charged amounts, or currency.

A new run returns `201` and `Location`; the same key and parameters return `200` with the existing run. A key with different parameters or a competing execution holding the database lock returns `409`. Invalid parameters return `422`.

| Endpoint | Result |
| --- | --- |
| `GET /order-validation-runs?limit=50&offset=0` | Run history and finding counts. |
| `GET /order-validation-runs/{id}` | Parameters, timestamps, rules version, and check results. |
| `GET /order-validation-runs/{id}/findings` | Paginated evidence; optional `check`, `severity` (`ERROR`/`WARNING`), and `order_id` filters. |

Each check reads one database statement snapshot and commits its findings independently. Checks in one run may observe different moments during concurrent checkout. Age checks use a common cutoff time captured at run start. Check statements have a five-second timeout; a 30-second execution budget stops further checks from starting and marks them skipped. Failed or skipped checks make the run `PARTIAL`, or `FAILED` if none completed. This budget is not a strict HTTP response deadline.

An abrupt crash can leave a `RUNNING` record. The next new invocation marks abandoned runs `INTERRUPTED` after acquiring the execution lock. There is no scheduler.

In the UI, **Run again** restores the previous selection and thresholds for review. **Check run status** reuses a pending request identity after a lost response, retained across reloads within the browser tab. Results link to affected orders and warehouses; running result pages refresh automatically, and historical results offer manual refresh.

## Follow the implementation

| Concern | Source |
| --- | --- |
| Request validation and HTTP responses | [HTTP order adapter](../apps/api/app/adapters/inbound/http/orders.py) |
| Checkout stages and external calls | [Order service](../apps/api/app/application/services/orders.py) |
| Transactions, locks, and persisted evidence | [SQL order repository](../apps/api/app/adapters/outbound/persistence/orders.py) |
| Failure presets | [Simulation adapters](../apps/api/app/infrastructure/order_simulation.py) |
| Database invariants and history | [Migrations](../apps/api/migrations/versions/) |
| Monitoring checks and execution | [Check queries](../apps/api/app/adapters/outbound/persistence/order_validation_checks.py), [validation repository](../apps/api/app/adapters/outbound/persistence/order_validations.py) |

The API writes structured JSON logs. Match the response's `X-Request-ID` to request events, then follow checkout events by order ID with `make api-logs`. Logs help locate the failure; the order, history, reservation balances, and saved decision evidence establish what committed.
