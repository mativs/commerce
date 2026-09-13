# Canals Commerce

An order checkout app that selects products, reserves stock at the nearest eligible warehouse, and processes a mock payment. The UI exposes order history, warehouse selection, inventory, and consistency checks.

## 5-minute walkthrough

The [hosted demo](https://web-production-053dd.up.railway.app/) is ready to use without a local setup:

1. Open **Orders → New order** and choose **Successful — payment succeeds** under **Fill with test data**.
2. Click **Place order** and confirm the order reaches **Paid**, with the history **Created → Stock reserved → Awaiting payment → Paid**.
3. Scroll down on the order detail page, review the warehouse decision map and table. Confirm the selected warehouse is the nearest eligible candidate, and inspect each candidate's distance, rank, stock outcome, and rejection reason.
4. Return to **New order**, choose **Payment timeout**, and place it. The order should remain **Awaiting payment** with its reservation retained.
5. Open **Monitoring → Run checks**, set **Paying · seconds** to `1`, wait two seconds, and run the checks. Inspect the pending-payment finding and follow its order link.
6. Open **Stock** to compare on-hand, reserved, and available quantities. Use **Reset demo data** before repeating the walkthrough.

## Checkout reference

The document [docs/orders.md](docs/orders.md) briefly explains some UI examples and provides the detailed API contract, order lifecycle, inventory rules, payment handling, monitoring, and concurrency behavior. The [hosted Swagger UI](https://canals-commerce-production.up.railway.app/docs) is available for trying the API directly.

## Quick start

Requires Docker with Compose v2, a running Docker daemon, and Make. Ports **5173** and **8000** must be free.

```sh
cp .env.example .env
make up
make migrate
```

Open [the app](http://localhost:5173) or [local Swagger UI](http://localhost:8000/docs).

Run the full verification suite:

```sh
make check
```

`make up` builds and starts the services. `make migrate` creates the schema and seeds five warehouses, ten USD products, and stock. The first build requires internet access.

## Non-functional requirements

1. **No duplicate order processing.** Repeated requests must resolve to one order.
2. **No duplicate payments.** A checkout must not create multiple charge attempts.
3. **Consistent inventory.** For each warehouse/product pair, `0 <= reserved <= on_hand` and `available = on_hand - reserved`.

## How the design addresses them

1. **Order idempotency:** `Idempotency-Key` identifies the checkout request. A unique database constraint makes concurrent requests with the same key share one order; a different request with that key returns `409 Conflict`.
2. **Payment idempotency:** the server generates and persists a separate `payment:<UUID>` identity. A payment provider can use it to deduplicate charge attempts; clients cannot choose or reuse another order's payment identity.
3. **Inventory consistency:** the API locks and rechecks all required stock rows before reserving them. Reservation and `BOOKED` commit together; release and `CANCELLED` commit together. Unknown payment outcomes retain reservations.

## Out of scope

1. **Authentication and authorization.** No users, roles, access control, or tenant isolation.
2. **Payment security and production payments.** Payments are fully simulated: card numbers are fictitious test data, no card network or payment provider is contacted, and no money is charged. Production use requires tokenization, PCI controls, provider webhooks, and secret management.
3. **Automatic retries and recovery.** Replaying a request returns its saved state; it does not resume checkout. Recovery workers, provider lookup, reconciliation, and webhook handling are excluded.
4. **Scheduled monitoring and alerts.** Checks run manually and save findings. There is no scheduler, notification delivery, or automatic repair.
5. **Production scale and availability.** Checkout is synchronous. Queues, horizontal-work coordination, rate limiting, and high-availability operations are outside the exercise.
6. **Catalog administration.** Products and warehouses are read-only through the API; CRUD and catalog workflows are excluded.

The mock geocoder ignores the entered address and returns sample coordinates in Mar del Plata. It does not return the address's real location. The header's **Reset demo data** restores the migration seed; `POST /demo/reset` is an assessment convenience, not a production administration API.

## Design decisions

### Request identity belongs in the database

Every checkout requires a client-supplied `Idempotency-Key`. The database enforces uniqueness and stores a request fingerprint: matching retries return the existing order; conflicting input returns `409`. Concurrent requests cannot independently process the same key.

Payment identity is separate: the server generates and saves `payment:<UUID>`. Clients cannot choose or collide with another order's payment key. The mock gateway returns a stable reference for that identity. A real gateway must honor it too; the database alone cannot guarantee that an external provider never charges twice.

### Inventory must remain consistent

For every warehouse/product pair, `0 <= reserved <= on_hand`, and `available = on_hand - reserved`. PostgreSQL enforces the balance bounds; availability is calculated from those balances rather than stored separately. Checkout rereads stock under exclusive locks before reserving it. Reservation and release commit with the corresponding order state, so retries and failures cannot partially update inventory.

Reserved quantities must match the units held by `BOOKED`, `PAYING`, and `PAID` orders. Monitoring checks that agreement and reports discrepancies. Displayed stock is a snapshot; the reservation decision uses current locked database balances. Physical stock represents the recorded warehouse quantity; this demo does not synchronize with a warehouse system or verify physical counts.

### Short transactions, explicit progress

Checkout currently runs synchronously, through independently committed stages:

```text
CREATED → BOOKED → PAYING → PAID
```

Each stage makes progress visible and gives monitoring a place to detect stalled work. Database triggers record status changes, timestamps, and cancellation reasons. Status history uses `clock_timestamp()` so events reflect their actual recording time through a commit transaction.

Order rows are locked for state changes. Stock rows are exclusively locked in product-ID order for reservation and release. Shared product and warehouse locks protect eligibility, price capture, and booking. Stock reservation and `BOOKED` commit together; release and cancellation commit together. State checks prevent repeated finalization or release.

**Network calls never hold inventory locks.** Geocoding and payment run outside database transactions. A later failure leaves earlier commits intact. This allows an order to survive an interrupted checkout, but requires recovery across stages.

**A timeout is not a decline.** A definitive rejection cancels the order and releases stock. An unknown payment outcome leaves it `PAYING`, with stock reserved. This includes an invalid gateway response or a claimed success without a nonblank provider reference of at most 128 characters. Reconciliation must confirm the provider's outcome using the saved payment identity before changing reservations; provider lookup and recovery are outside this exercise's scope.

### Store the facts that matter

| Decision | Reason and trade-off |
| --- | --- |
| Customers stored separately, identified by email, referenced by orders | Reuses customer identity across purchases. Shipping details remain an order snapshot. |
| USD assumed throughout; no currency field | Keeps pricing within the exercise's scope. Multi-currency would require an explicit model change. |
| Python `Decimal` and PostgreSQL `NUMERIC`, two decimal places | Keeps money calculations exact. The API computes totals; the browser shows an estimate. |
| Item prices captured at insertion | Catalog price changes cannot alter an existing order's total. Product names still come from the current catalog; snapshotting them is a possible improvement. |
| One stock row per warehouse/product pair | Separates physical stock from reservations. Available stock is `on_hand - reserved`. |
| Haversine distance, warehouse ID as the tie-breaker | Provides a deterministic ranking for the evaluated coordinates without a routing service. This is great-circle distance, not driving distance. |
| Saved warehouse decision evidence | Preserves candidates, distances, and reservation outcomes when warehouse data later changes. |
| Database audit triggers for warehouses, products, and stock | Records changes in the same transaction, including direct SQL changes. Business behavior in migrations must be tested against PostgreSQL. |

For a detailed explanation of order creation, see the [checkout reference](docs/orders.md).
