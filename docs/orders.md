# Order creation walkthrough

Use the [hosted web app](https://web-production-053dd.up.railway.app/) or start the app locally with the [README setup](../README.md#quick-start). The interface provides test-data presets so the main checkout and failure paths can be exercised without manually preparing every field.

## 1. Place a successful order

1. Open **Orders → New order**.
2. Under **Fill with test data**, select **Successful — payment succeeds**. This fills every required field and selects items that fit in one warehouse's available stock.
3. Click **Place order**. The mock payment takes about two seconds.
4. Expect **Paid**, a payment reference, and this activity history: **Created → Stock reserved → Awaiting payment → Paid**.
5. Inspect the warehouse decision table and map. The selected warehouse is the nearest eligible candidate whose stock could be reserved.
6. Open **Stock** to inspect inventory. Paid orders keep their units reserved because shipment is outside this app's scope.

## 2. Exercise checkout failures

Create a **new order for each row**, choose the corresponding option under **Fill with test data**, and click **Place order**.

| Test scenario | Expected result | Inventory effect |
| --- | --- | --- |
| Geocoding timeout | **Cancelled**, `GEOCODING_FAILED` | No reservation |
| Payment declined | **Cancelled**, `PAYMENT_FAILED` | Reservation released |
| Payment timeout | **Awaiting payment** (`PAYING`) | Reservation retained |
| Payment failed | **Awaiting payment** (`PAYING`); provider outcome unknown | Reservation retained |
| No stock | **Cancelled**, `OUT_OF_STOCK` | No reservation |

Failure presets insert a keyword into **Order notes**. The no-stock preset uses real inventory: it requests more units than any single warehouse can supply. These controls are always enabled for the assessment.

## 3. Find a stuck payment

After creating a **Payment timeout** order:

1. Open **Monitoring → Run checks**. Leave all eight checks selected.
2. Expand **Timing thresholds**, set **Paying · seconds** to `1`, and wait at least two seconds.
3. Click **Run selected checks**.
4. Expect a **Completed** run with a **Payment pending too long** finding linked to that order. Other pending orders may also appear.
5. Follow the order link. It should still be **Awaiting payment**. Monitoring records findings; it does not repair orders or retry payments.

Use **Reset demo data** from the header before repeating the walkthrough. Reset is intended only for the disposable demo database and should not run while checkout or monitoring requests are in flight.

# How order creation works

`POST /orders` accepts customer, shipping, items, and demo payment data. It saves the order, selects a warehouse that can fulfill every item, reserves stock, and attempts payment.

**No duplicate orders. No duplicate payments. Consistent inventory balances.** These invariants hold across concurrent checkouts, retries, and failures. Unknown payment outcomes retain inventory.

Checkout runs synchronously within the HTTP request. Database stages commit independently; external calls run between transactions. Monitoring exposes interrupted work. Queues, webhooks, and automatic recovery are out of scope; a pending response does not start background work.

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

Follow the [README setup](../README.md#run-locally) first. It starts the app and applies migrations with five warehouses, ten USD products, and demo stock.

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

Expect `201`, `status: "PAID"`, total `"119.98"`, a payment reference, and all four success stages in `history`. The mock payment waits about two seconds and makes no real charge.

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

> **A displayed stock count is a snapshot, not permission to sell.** Another checkout may reserve units immediately after a read. Every reservation rereads the current balances under exclusive locks and validates the complete order before changing stock. Retries, declines, and rollbacks must preserve these rules.

These guarantees concern the recorded inventory. The demo does not synchronize with a warehouse system, verify physical counts, or process receipts and shipments. Those integrations would need to preserve the same invariants.

## 1. Validate and normalize the request

[The HTTP adapter](../apps/api/app/adapters/inbound/http/orders.py) validates input before handing a command to the application service.

- `Idempotency-Key` is required: 1–128 visible ASCII characters, with no spaces.
- Customer, shipping address, at least one item, card number, and payment description are required. Unknown fields—including prices, totals, coordinates, status, and warehouse—are rejected.
- Product IDs and quantities are integers from `1` to `2147483647`; requests accept at most 1,000 item entries.
- Quantities are validated before duplicate product entries are merged. The merged quantity must also fit the limit.
- Models trim specified strings, lowercase email, uppercase country code, and sort items by product ID.

Invalid input returns `422` before an order is created. Product existence and eligibility are checked inside the next transaction.

> **Design decision.** The server owns price, fulfillment, and status. Accepting them from the browser would bypass checkout rules. FastAPI and Pydantic keep validation and the [interactive API contract](http://localhost:8000/docs) together. For hosted use, open the [hosted Swagger UI](https://canals-commerce-production.up.railway.app/docs) or [hosted OpenAPI schema](https://canals-commerce-production.up.railway.app/openapi.json).

## 2. Claim the request and save the order

The service generates a server-owned payment key, `payment:<UUID>`. The repository inserts the order in one transaction with:

- The client order key and a SHA-256 fingerprint of the normalized command.
- The separate payment key.
- The shipping snapshot, notes, and demo payment details.
- Initial status `CREATED`.

A unique database constraint arbitrates concurrent requests using the same order key. Only the request that inserts the order continues checkout.

| Existing key | Result |
| --- | --- |
| Same normalized command | Read the saved order under a shared lock and return its current state. |
| Different normalized command | Return `409 Conflict`. |

The fingerprint includes customer, shipping, items, notes, and payment input. A replay discards its newly generated payment key and keeps the saved order's key.

> **Design decision.** PostgreSQL owns deduplication. The unique constraint makes request ownership atomic; an application-side existence check would race.

For a new order, that transaction then:

1. Creates or reuses the customer identified by normalized email and links it to the order. If the email already exists, it reuses that customer's ID; **it does not overwrite the existing name or phone**.
2. Takes shared product locks in product-ID order and checks that every product exists, is active, and is not deleted.
3. Inserts the order items. A database trigger copies each product's current price into `unit_price`.
4. Calculates `total_amount` from saved unit prices and quantities using Python `Decimal`.
5. Commits the customer link, order, items, total, and initial status history together.

Unavailable products or an unsupported total return `422` and roll back this entire transaction. No partial order or consumed idempotency key remains.

> **Design decision.** Prices are purchase facts. They are captured once with Python `Decimal` and PostgreSQL `NUMERIC` at two-decimal precision. USD is assumed. Product names remain live catalog data, so renaming a product changes older displays.

The assessment stores test card numbers in the database and temporarily in browser session storage for pending retries. API responses omit them. Real payment integration requires provider tokenization.

## 3. Create or attach the customer

The order-creation transaction creates or reuses the customer by normalized email. It never overwrites an existing customer's name or phone. Customer identity is shared across purchases, while delivery details remain order snapshots. The app has no saved-address CRUD model.

## 4. Locate the shipping address

The service calls the geocoder outside a database transaction with a ten-second timeout. On success, a short transaction locks the order and saves its coordinates. The order remains `CREATED`.

The mock geocoder ignores the entered address and returns sample coordinates in Mar del Plata. New orders for the same address can receive different sample coordinates; replays retain the coordinates saved on the order.

A geocoding timeout or unavailable response cancels the order with `GEOCODING_FAILED`. No inventory has been reserved and no payment is attempted.

> **Design decision.** External calls do not hold database locks. The async geocoder interface isolates the mock and future providers from checkout rules.

There is no `GEOCODING` status: the lookup neither charges nor reserves stock. `CREATED` plus saved coordinates provide sufficient durable progress.

## 5. Rank warehouses and save the evidence

The repository finds non-deleted warehouses with enough available stock for **every** requested item:

```text
available = on_hand - reserved
```

Stock has one row per warehouse/product pair. A missing row cannot satisfy an item. Stock distributed across several warehouses cannot satisfy a single order: split fulfillment is outside the scope.

The service ranks candidates by Haversine distance from the saved coordinates, then warehouse ID. Haversine gives great-circle distance, not driving distance, delivery time, or shipping cost.

> **Design decision.** This provides deterministic ranking without a routing API. One warehouse per order keeps fulfillment rules explicit.

Before trying to reserve, another transaction saves `warehouse_decision`, a versioned JSONB snapshot containing the evaluation timestamp, strategy, shipping coordinates, and ranked candidates. Each candidate records its ID, name, coordinates, unrounded distance, rank, reservation outcome, and rejection reason.

> **A candidate is not a reservation.** Another checkout can consume its stock after evaluation. The next step must recheck availability under locks.

Evidence limits:

- Only warehouses eligible at evaluation time appear as candidates. The snapshot does not explain every excluded warehouse.
- Candidates begin as `NOT_ATTEMPTED`. Reservation attempts change them to `REJECTED` or `SELECTED`; candidates after the winner stay `NOT_ATTEMPTED`.
- An empty candidate list means none qualified. A null snapshot means no decision was recorded, such as a historical order, geocoding failure, or interruption before selection.
- Replays and later warehouse changes do not recompute the evidence. Payment failure does not erase it.

The order detail table and Leaflet map display this evidence. Current warehouse data cannot reconstruct historical eligibility. OpenStreetMap tiles need internet access; markers and the table remain available if tiles fail.

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

> **Design decision.** Validate all items before updating stock, and commit the reservation with `BOOKED`. Product-ID lock ordering prevents deadlocks; catalog locks protect eligibility and price capture.

If a candidate fails, its rejection evidence commits without changing stock:

| Reason | What changed or was missing |
| --- | --- |
| `WAREHOUSE_UNAVAILABLE` | Warehouse no longer eligible. |
| `PRODUCT_UNAVAILABLE` | At least one product is missing, inactive, or deleted. |
| `INSUFFICIENT_STOCK` | A stock row is missing or available quantity is too low. |

The transaction ends before the next candidate, releasing its locks. The service uses the original ranked list and does not discover new candidates. If none succeeds, it cancels with `OUT_OF_STOCK`.

## 7. Record payment initiation, then call the provider

A short transaction locks the order, requires `BOOKED`, and commits `PAYING`. The service then calls the gateway outside the transaction with:

- The saved order total.
- The request's payment details.
- The server-generated payment identity saved at creation.
- A ten-second timeout.

> **`PAYING` proves local intent, not provider receipt.** The process can crash before sending the request or lose a successful provider response.

The mock waits two seconds and returns success with a stable payment reference derived from the payment key. No money moves. A real gateway must honor the idempotency key; database uniqueness cannot by itself prevent duplicate charges inside an external system.

> **Design decision.** The client identifies the checkout request; the server identifies its charge. Reusing an order key returns before geocoding, reservation, or payment.

## 8. Finalize what is known

| Gateway outcome | Database action | Inventory |
| --- | --- | --- |
| Success | Lock the order; if still `PAYING`, save the provider reference and set `PAID`. | Keep reserved. |
| Definitive decline | Lock the order and stock, release the reservation, record `PAYMENT_FAILED`, and set `CANCELLED` in one transaction. | Release exactly once. |
| Timeout or provider unavailable | Return the saved `PAYING` order. | Keep reserved. |
| Invalid response, including success without a valid reference | Return the saved `PAYING` order and log `PAYMENT_RESPONSE_INVALID`. | Keep reserved. |

> **A timeout is not a decline.** Releasing stock after an unknown outcome could resell paid inventory. The trade-off is reduced availability until reconciliation.

A successful gateway response must include a nonblank string reference of at most 128 characters. Otherwise the result is incomplete evidence, not a decline: return `202` with `PAYING`. A replay with the same key returns that state without charging again.

Cancellation checks state, locks stock in product-ID order, and verifies a full release. An inconsistent reservation raises an error and rolls back; it never partially subtracts. Already `PAID` or `CANCELLED` orders are unchanged. Finalization only changes `PAYING` orders.

> **Paid does not mean shipped.** The app has no shipment stage. `BOOKED`, `PAYING`, and `PAID` retain reservations; physical stock is unchanged.

## History, responses, and interrupted work

Database triggers append status history in the same transaction as each status change. Entries include status, timestamp, and applicable cancellation reason. `clock_timestamp()` records wall-clock time; history sorts by timestamp and ID. History cannot be updated or deleted; orders cannot be deleted. Separate audit triggers record warehouse, product, and stock changes, including reservation and release.

> **Design decision.** Evidence commits with the change it describes. Logs trace requests; durable history remains after logs expire. State checks govern application transitions, while monitoring detects invalid sequences introduced outside that flow.

`GET /orders/{id}` uses a shared order lock while loading its related data.

The order list avoids per-order locks: it loads the page, items, history, and customers in batches inside a PostgreSQL `REPEATABLE READ` transaction. Every result is assembled from one snapshot.

| `POST /orders` response | Meaning |
| --- | --- |
| `201` | Saved order is `PAID` or `CANCELLED`. Inspect `status` and `failure_reason`. A replay of a terminal order also returns `201`. |
| `202` | Saved order is `CREATED`, `BOOKED`, or `PAYING`. This does not promise background processing. |
| `409` | Existing key was used with a different normalized command. |
| `422` | Request validation, product eligibility, or supported-total validation failed; this request created no order. |
| Unexpected error / lost response | Earlier stages may already have committed. Retry with the same key and body to learn the saved state. |

Successful responses include `Location: /orders/{id}`, items, chronological history, warehouse evidence, and any payment reference. `GET /orders?limit=50&offset=0` lists newest orders first; `limit` is 1–100 and `offset` is nonnegative. Editing, manual status changes, and deletion endpoints are not exposed.

### What survives a crash

| Interruption point | Durable state | What a replay does |
| --- | --- | --- |
| Before creation commits | No order from that attempt. | Can create and process the order. |
| After creation, before booking | `CREATED`; coordinates or decision evidence may be incomplete. | Returns it without resuming. |
| After reservation, before payment initiation | `BOOKED`, with stock reserved. | Returns it without starting payment. |
| After `PAYING`, before finalization | `PAYING`, with stock reserved; provider outcome uncertain. | Returns it without another charge. |
| After finalization, before HTTP response | `PAID` or `CANCELLED`. | Returns the saved result. |

A database error rolls back the current transaction, not earlier commits. Finalization can fail after the provider confirms payment, leaving the local order `PAYING`.

> **Recovery is out of scope.** The implementation preserves committed progress and monitoring detects stalled orders. It does not query the provider, reconcile charges, or resume interrupted work. A future provider lookup would use the saved `payment:<UUID>`. Reposting the order returns its saved state; it does not recover it. Do not replace an uncertain attempt with a new key.

## Verify failures and concurrency

The [README walkthrough](../README.md#verify-the-behavior) covers the interface. For API testing, use the request above with a fresh order key per scenario and one of these keywords in `notes`:

| Notes keyword | Expected result | Reservation |
| --- | --- | --- |
| No recognized keyword | `201`, `PAID` | Retained |
| `geocoding-timeout` | `201`, `CANCELLED`, `GEOCODING_FAILED` | Never taken |
| `payment-declined` | `201`, `CANCELLED`, `PAYMENT_FAILED` | Released |
| `payment-timeout` | `202`, `PAYING` | Retained |
| `payment-failed` | `202`, `PAYING`; provider unavailable | Retained |

Payment scenarios require a successful reservation first. For out-of-stock behavior, choose **No stock** in the UI; it requests more units than any warehouse can supply and returns `CANCELLED` with `OUT_OF_STOCK`.

Keywords are case-insensitive, must be complete, and the first match wins. Simulated timeouts raise immediately. Per-invocation adapter wrappers implement these scenarios; checkout rules and SQL contain no simulation branches. Simulations are always enabled.

Demo stock is finite. Migration `0010` seeds 5–50 units per stocked pair; two products appear in all five warehouses and the rest in three. Migrations preserve balances, so paid and pending orders reduce availability until the demo is reset.

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

Tests create and remove temporary schemas against the migrated database. The repository also includes lint, formatting, TypeScript, and web-build checks for code changes.

## Monitor what checkout leaves behind

Monitoring detects stalled work and inconsistent data. It saves findings but never charges, cancels, releases stock, or repairs orders. Runs are manual; there is no scheduler or notification delivery.

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

Thresholds default to 300 seconds and accept 1–604800 seconds. Checks scan all orders; inventory comparison uses complete warehouse/product totals.

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

> **Completed means execution finished, not that orders are healthy.** Inspect `finding_count`, severity totals, and each result. Findings preserve identifiers and diagnostics but exclude customer/address snapshots and card numbers. They do not verify provider transactions, duplicate charges, amounts, or currency.

A new run returns `201` and `Location`; the same key and parameters return `200` with the existing run. A key with different parameters or a competing execution holding the database lock returns `409`. Invalid parameters return `422`.

| Endpoint | Result |
| --- | --- |
| `GET /order-validation-runs?limit=50&offset=0` | Run history and finding counts. |
| `GET /order-validation-runs/{id}` | Parameters, timestamps, rules version, and check results. |
| `GET /order-validation-runs/{id}/findings` | Paginated evidence; optional `check`, `severity` (`ERROR`/`WARNING`), and `order_id` filters. |

Each check reads one statement snapshot and commits findings independently, so checks in one run may observe different moments during concurrent checkout. Age checks share a cutoff captured at run start. Statements have a five-second timeout; a 30-second execution budget skips remaining checks. Failed or skipped checks produce `PARTIAL`, or `FAILED` if none complete. The budget is not an HTTP deadline.

An abrupt crash can leave a `RUNNING` record. The next new invocation marks abandoned runs `INTERRUPTED` after acquiring the execution lock. There is no scheduler.

In the UI, **Run again** restores the previous selection and thresholds. **Check run status** reuses a pending request identity after a lost response within the browser tab. Results link to affected orders and warehouses; active pages refresh automatically and historical results refresh manually.

## Follow the implementation

| Concern | Source |
| --- | --- |
| Request validation and HTTP responses | [HTTP order adapter](../apps/api/app/adapters/inbound/http/orders.py) |
| Checkout stages and external calls | [Order service](../apps/api/app/application/services/orders.py) |
| Transactions, locks, and persisted evidence | [SQL order repository](../apps/api/app/adapters/outbound/persistence/orders.py) |
| Failure presets | [Simulation adapters](../apps/api/app/infrastructure/order_simulation.py) |
| Database invariants and history | [Migrations](../apps/api/migrations/versions/) |
| Monitoring checks and execution | [Check queries](../apps/api/app/adapters/outbound/persistence/order_validation_checks.py), [validation repository](../apps/api/app/adapters/outbound/persistence/order_validations.py) |

The API writes structured JSON logs. Match `X-Request-ID` to request events, then follow checkout events by order ID with `make api-logs`. Logs locate failures; the order, history, reservation balances, and decision evidence establish what committed.
