# Canals Commerce

An order checkout app: choose products, reserve stock at the nearest eligible warehouse, and process a mock payment. The interface exposes order history, warehouse selection, inventory, and checks for stalled or inconsistent orders.

**Three requirements drive the design: no duplicate orders, no duplicate payments, and consistent inventory balances.** Retries reuse the original request identity. Physical stock, reservations, and availability must remain consistent under concurrent checkouts, retries, and failures. An uncertain payment keeps its inventory reservation because a timeout does not prove that a charge failed.

**Hosted demo:** [canals-commerce.example.com](https://canals-commerce.example.com) — placeholder; not deployed yet.

## Run locally

Requires **Docker with Compose v2**, a running Docker daemon, and **Make**. Ports **5173** and **8000** must be free. Docker installs Python, Node, PostgreSQL, and project dependencies. No local language setup or API keys are needed; the first build requires internet access.

From a fresh checkout, in the repository root:

```sh
cp .env.example .env
make up
make migrate
make check
```

`make up` builds and starts the services. `make migrate` creates the schema and seeds **5 warehouses, 10 USD products, and stock across warehouses**. Run both before opening the app or testing database behavior. `make check` runs the checks described below.

| Open | Purpose |
| --- | --- |
| [App](http://localhost:5173) | Place orders, inspect stock, run monitoring checks |
| [Interactive API docs](http://localhost:8000/docs) | Inspect requests and call endpoints |
| [Health endpoint](http://localhost:8000/health) | Confirm the API responds; does not verify migrations |

Use fictional customer details and test card `4242424242424242`. Payments are simulated; no money moves. Geocoding returns a sample Mar del Plata location, not the real coordinates of the entered address.

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

- Submit twice with the same key and body: expect the **same order ID**, with no second reservation or payment attempt.
- Change the quantity while keeping the key: expect **409 Conflict**.
- Use a fresh key with quantity `0`: expect **422**, with no order created.

Use a new key for each new order. A `201` response means the order was saved; inspect `status` because cancelled checkouts also return `201`. Pending orders return `202`. Replaying a pending order observes its saved state; it does not resume checkout.

## Automated checks

After setup, run `make check` for Ruff lint and formatting checks, the backend pytest suite, TypeScript checks, and a Vite build. Every step must pass. For backend tests alone:

```sh
make test
```

Database tests use **real PostgreSQL**, with temporary schemas created and removed per test. They require the migrated database and leave demo orders and stock intact. Running pytest without `DATABASE_URL` skips database tests; use the Make commands to exercise them.

The suite covers concurrent requests sharing an idempotency key, competing inventory reservations, warehouse fallback, payment failures, rollback, price snapshots, status history, monitoring findings, and log redaction. External payment and geocoding services are mocked. There is no committed browser test suite; use the walkthrough above to verify the interface.

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

## Scope and limits

- **Assessment demo:** no authentication or real payment integration. Test card numbers are stored in the database and temporarily in browser session storage for pending checkout retries. Real payments require provider tokenization.
- **One warehouse per order.** No split shipments, taxes, shipping rates, fulfillment, refunds, or replenishment UI. Products and warehouses are read-only through the API.
- **Interrupted work is detected, not automatically recovered.** Monitoring runs are manual, with saved findings and execution history. There is no scheduler or automatic notification delivery, and a completed run can still contain errors. Provider lookup, reconciliation, recovery workers, and webhook handling are intentionally outside this exercise's scope. The saved payment identity supports a future provider lookup; no such lookup runs today. Replaying a request returns its saved state without restarting processing.
- **Finite demo stock.** Successful and pending orders retain reservations. Re-running migrations does not replenish stock; enough repeated checkouts will exhaust it.

## Development

| Command | Purpose |
| --- | --- |
| `make up` | Build and start services; rebuild after dependency changes |
| `make migrate` | Apply pending migrations |
| `make check` | Run backend checks, tests, and web typecheck/build |
| `make test` | Run backend tests only |
| `make logs` | Follow all service logs |
| `make api-logs` | Follow API JSON logs |
| `make down` | Stop services and retain database data |

API and web source changes reload automatically. After changing `.env`, run `make up` to recreate affected services. Defaults are in [.env.example](.env.example).

If startup fails, run `docker compose ps -a` and `make logs`. If API calls report missing tables, run `make migrate`. For request failures, match the response's `X-Request-ID` to structured API logs. Application events omit customer details, addresses, card data, and idempotency keys; conventions live in [logging.py](apps/api/app/infrastructure/logging.py).

Start reading at [the checkout service](apps/api/app/application/services/orders.py), then [the SQL repository](apps/api/app/adapters/outbound/persistence/orders.py) and [checkout tests](apps/api/tests/test_orders.py). The [checkout reference](docs/orders.md) documents request bodies, failure keywords, monitoring checks, and warehouse decision evidence.
