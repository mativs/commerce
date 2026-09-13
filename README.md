# Canals Commerce

An order checkout app that selects products, reserves stock at the nearest eligible warehouse, and processes a mock payment. The UI exposes order history, warehouse selection, inventory, and consistency checks.

## Non-functional requirements

1. **No duplicate order processing.** Repeated requests must resolve to one order.
2. **No duplicate payments.** A checkout must not create multiple charge attempts.
3. **Consistent inventory.** For each warehouse/product pair, `0 <= reserved <= on_hand` and `available = on_hand - reserved`.

## How the design addresses them

1. **Order idempotency:** `Idempotency-Key` identifies the checkout request. A unique database constraint makes concurrent requests with the same key share one order; a different request with that key returns `409 Conflict`.
2. **Payment idempotency:** the server generates and persists a separate `payment:<UUID>` identity. A payment provider can use it to deduplicate charge attempts; clients cannot choose or reuse another order's payment identity.
3. **Inventory consistency:** the API locks and rechecks all required stock rows before reserving them. Reservation and `BOOKED` commit together; release and `CANCELLED` commit together. Unknown payment outcomes retain reservations.

See the [checkout reference](docs/orders.md) for the detailed API contract, transaction flow, failure handling, monitoring checks, and concurrency behavior.

## Out of scope

1. **Authentication and authorization.** No users, roles, access control, or tenant isolation.
2. **Payment security and production payments.** Payments are mocked. Production use requires tokenization, PCI controls, provider webhooks, and secret management.
3. **Automatic retries and recovery.** Replaying a request returns its saved state; it does not resume checkout. Recovery workers, provider lookup, reconciliation, and webhook handling are excluded.
4. **Scheduled monitoring and alerts.** Checks run manually and save findings. There is no scheduler, notification delivery, or automatic repair.
5. **Production scale and availability.** Checkout is synchronous. Queues, horizontal-work coordination, rate limiting, and high-availability operations are outside the exercise.
6. **Catalog administration.** Products and warehouses are read-only through the API; CRUD and catalog workflows are excluded.

**Hosted demo:** [Open the deployed web app](https://web-production-053dd.up.railway.app/)

The web app and API are deployed as separate services. The hosted API is [canals-commerce-production.up.railway.app](https://canals-commerce-production.up.railway.app/). Open its [hosted Swagger UI](https://canals-commerce-production.up.railway.app/docs) or download the [hosted OpenAPI schema](https://canals-commerce-production.up.railway.app/openapi.json) without running the project locally. The local equivalents are listed below.

## Run locally

Requires **Docker with Compose v2**, a running Docker daemon, and **Make**. Ports **5173** and **8000** must be free. Docker provides Python, Node, PostgreSQL, and project dependencies; no local language setup or API keys are required. The first build needs internet access.

From a fresh checkout, in the repository root:

```sh
cp .env.example .env
make up
make migrate
```

`make up` builds and starts the services. `make migrate` creates the schema and seeds **5 warehouses, 10 USD products, and stock**. Run both before opening the app.

| Open | Purpose |
| --- | --- |
| [App](http://localhost:5173) | Place orders, inspect stock, run monitoring checks |
| [Interactive API docs](http://localhost:8000/docs) | Inspect requests and call endpoints |
| [Health endpoint](http://localhost:8000/health) | Confirm the API responds; does not verify migrations |

FastAPI generates the API documentation from the endpoint definitions. Access the [local Swagger UI](http://localhost:8000/docs) or [local OpenAPI schema](http://localhost:8000/openapi.json) after the API starts; the web app is not required. The frontend and API use separate base URLs.

The header's **Reset demo data** action accepts `RESET`, deletes mutable demo state, and restores the migration seed. Use it only with the disposable assessment database.

`POST /demo/reset` is an assessment convenience, not a production administration API. Run it when no checkout or monitoring request is in flight. Reset and reseeding share one transaction: a failure rolls it back and returns a generic `500`, with diagnostics in request logs.

Geocoding returns a sample Mar del Plata location, not the real coordinates of the entered address.

## Verify the behavior

### 1. Place an order

1. Open **Orders → New order**.
2. Under **Fill with test data**, select **Successful — payment succeeds**. This fills every required field and selects items that fit in one warehouse's available stock.
3. Click **Place order**. The mock payment takes about two seconds.
4. Expect **Paid**, a payment reference, and this activity history: **Created → Stock reserved → Awaiting payment → Paid**.
5. Inspect the warehouse decision table and map. The selected warehouse is the nearest eligible candidate whose stock could be reserved.
6. Open **Stock** to inspect inventory. Paid orders keep their units reserved because shipment is outside this app's scope.

### 2. Exercise failures

Create a **new order for each row**, choose the corresponding test-data option, and click **Place order**.

| Test scenario | Expected result | Inventory effect |
| --- | --- | --- |
| Geocoding timeout | **Cancelled**, `GEOCODING_FAILED` | No reservation |
| Payment declined | **Cancelled**, `PAYMENT_FAILED` | Reservation released |
| Payment timeout | **Awaiting payment** (`PAYING`) | Reservation retained |
| Payment failed | **Awaiting payment** (`PAYING`); provider outcome unknown | Reservation retained |
| No stock | **Cancelled**, `OUT_OF_STOCK` | No reservation |

Failure presets insert a keyword into **Order notes**. The no-stock preset uses real inventory: it requests more units than any single warehouse can supply. These controls are always enabled for the assessment.

### 3. Find a stuck payment

After creating a **Payment timeout** order:

1. Open **Monitoring → Run checks**. Leave all eight checks selected.
2. Expand **Timing thresholds**, set **Paying · seconds** to `1`, and wait at least two seconds.
3. Click **Run selected checks**.
4. Expect a **Completed** run with a **Payment pending too long** finding linked to that order. Other pending orders may also appear.
5. Follow the order link. It should still be **Awaiting payment**. Monitoring records findings; it does not repair orders or retry payments.

### 4. Verify retries through the API

In [Swagger UI](http://localhost:8000/docs), open `POST /orders`, click **Try it out**, use the [complete example request](docs/orders.md), and set `Idempotency-Key` to `readme-order-1`.

1. Submit twice with the same key and body: expect the **same order ID**, with no second reservation or payment attempt.
2. Change the quantity while keeping the key: expect **409 Conflict**.
3. Use a fresh key with quantity `0`: expect **422**, with no order created.

Use a new key for each new order. A `201` response means the order was saved; inspect `status` because cancelled checkouts also return `201`. Pending orders return `202`. Replaying a pending order observes its saved state; it does not resume checkout.

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

Each stage makes progress visible and gives monitoring a place to detect stalled work. Database triggers record status changes, timestamps, and cancellation reasons. Status history uses `clock_timestamp()` so events reflect their actual recording time.

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

### Use a small stack with clear boundaries

- **FastAPI + Pydantic:** request validation and interactive API documentation come from the endpoint definitions, reducing duplicated contract work.
- **SQLAlchemy + Alembic + PostgreSQL:** explicit transactions, row locking, constraints, and versioned migrations support the checkout guarantees. SQLite would not exercise the same locking and trigger behavior.
- **Application services with adapter interfaces:** checkout rules depend on repository, payment, and geocoder contracts. SQL, HTTP, and failure simulation stay in adapters; real providers have a defined integration point.
- **React + TypeScript + Vite:** three screens need little infrastructure. Component state, a fetch client, and hash navigation avoid a global state store or routing framework.
- **Leaflet + OpenStreetMap:** a map without a paid API key. Tiles need internet access; markers and the decision table remain available if tiles fail.
