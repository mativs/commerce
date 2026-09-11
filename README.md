# Backend Assessment

## Overview

A small API + web monorepo with an admin area for warehouses and shipping addresses, automatic mock geocoding, and change history.

## Stack

- Backend: Python 3.13, FastAPI, SQLAlchemy 2.x async, asyncpg, PostgreSQL, Alembic, Pydantic Settings, pytest and Ruff.
- Frontend: React, TypeScript (strict), Vite and plain CSS.
- Infrastructure: Docker Compose and Make. Python dependencies use `pyproject.toml` and `uv.lock`; web dependencies use `package-lock.json`.

## Architecture

```text
HTTP adapter
    ↓
application
    ↓
domain
    ↑
application ports
    ↑
outbound adapters
```

Dependencies point inward: adapters → application → domain. Shipping address use cases follow this structure, with application-owned geocoding and repository ports and framework-free domain values. `app/main.py` is the composition root; configuration and database lifecycle live in infrastructure. Domain and application packages contain no framework imports. Add only abstractions required by concrete use cases; no generic repositories, unit-of-work framework or speculative entities.

Future SQLAlchemy models belong in `adapters/outbound/persistence/models.py`, using `Mapped[...]` and `mapped_column`. Import any additional model modules there so Alembic sees their metadata. Introduce separate domain objects only when behavior or isolation warrants them; domain code must never import SQLAlchemy.

## Web architecture

React is a deliberately thin interface over the API. `src/api/client.ts` uses browser `fetch` and the public `VITE_API_URL` variable. The admin navigation switches between `WarehousesPage` and `ShippingAddressesPage`, each with a list, create/edit form, deletion confirmation, and change history. Hash URLs support direct links and browser back/forward without server routing configuration. Requests show loading and error states and can be retried with Refresh. Workflow UI lives under `pages`, with components extracted when needed. There is no routing, state library or SDK framework.

## Async database behavior

Async improves I/O efficiency. An `AsyncEngine` owns the connection pool; `async_sessionmaker` creates an `AsyncSession` per dependency invocation, with `expire_on_commit=False`. The HTTP `DatabaseSession` dependency closes sessions on success and failure; uncommitted work is rolled back on close. Engine disposal runs on application shutdown.

Transactions remain explicit at the persistence/orchestration edge:

```python
async with session.begin():
    # Perform the atomic database operations here.
    ...
```

Start the transaction before any queries that might autobegin one. No request-end commit is installed. Keep SQLAlchemy session handling out of domain/application code; add application-owned ports only when a real use case requires them.

PostgreSQL controls isolation, transactions and row-level locks, including `SELECT ... FOR UPDATE`. Async Python does not change lock semantics. Each concurrent task needs its own session. The engine retains PostgreSQL's default isolation (normally READ COMMITTED). Future database tests must run against PostgreSQL, not SQLite.

`GET /health` is process liveness and returns `{"status":"ok"}`; it does not query the database. Compose checks PostgreSQL health separately before starting the API.

## Running locally

Requires Docker with Compose v2 and Make.

```sh
cp .env.example .env
make up
```

- Web: http://localhost:5173
- API: http://localhost:8000/health
- OpenAPI docs: http://localhost:8000/docs

The sample credentials are disposable local defaults. `DATABASE_URL` is required and must use `postgresql+asyncpg://`. CORS origins are comma-separated explicit origins without trailing slashes. Only `VITE_` values are exposed to browser code. Compose passes backend variables only to the API; never put secrets in `VITE_` variables.

Docker uses `db:5432` for database access; the browser uses `localhost:8000` for the API. PostgreSQL stays on the internal Docker network; use `make db-shell` to access it. Web/API ports bind to loopback. Database data persists across `make down`.

API, migrations, tests and web source are bind-mounted for development. Vite reloads web changes; run `docker compose restart api` after API edits. Rebuild after dependency changes. Compose uses development image targets. The default API Docker target excludes development dependencies and runs as a non-root user. The default web target exports `/dist` static assets (not a running server); build it with `--build-arg VITE_API_URL=https://your-api.example` and serve the assets with your eventual hosting platform. Vite is only the local development server; public API URLs are baked into production web builds.

Optional host tooling (Python 3.13, uv and Node 22.12+):

```sh
uv sync --project apps/api
cd apps/web && npm ci
```

For a host-run API/Alembic, provide a reachable PostgreSQL instance (or publish the Compose database port via a local override). Run from `apps/api` and export the root example variables with `DATABASE_URL` adjusted to that instance. Start with `uv run uvicorn app.main:create_app --factory --reload`. Host-run Vite needs `VITE_API_URL` exported or in `apps/web/.env.local`.

## Make commands

| Command | Action |
| --- | --- |
| `make up` | Build and start PostgreSQL, API and web; wait for startup |
| `make down` | Stop/remove containers, preserve database volume |
| `make build` | Build API and web development images |
| `make logs` | Follow all service logs |
| `make api-logs` / `make web-logs` | Follow one service's logs |
| `make test` | Run backend pytest |
| `make check` | Ruff lint/format, pytest, TypeScript check and web production build |
| `make migrate` | Apply migrations |
| `make migration name="create_orders"` | Generate a migration in the host migrations directory |
| `make api-shell` / `make web-shell` | Open a shell in a running container |
| `make db-shell` | Open psql in PostgreSQL |

Run `make up` first. Checks use disposable containers and stop at the first failed command.

## Migrations

```sh
make migrate
make migration name="description"
```

Equivalent commands inside `make api-shell` (or a configured host API environment):

```sh
alembic revision --autogenerate -m "description"
alembic upgrade head
```

Alembic reads application settings and `Base.metadata`, using an async connection with `run_sync`. `upgrade head` creates the warehouse and audit tables, coordinate constraints, and the audit trigger. Always review generated migrations before applying them; migrations run explicitly, not at API startup.

## Testing

```sh
make test
make check
```

The health test covers HTTP 200, its JSON payload, and CORS without a live database. Warehouse and shipping address tests require PostgreSQL and applied migrations (`make migrate` before `make test`); they use isolated schemas and verify CRUD, validation, coordinate column types and constraints, soft deletion, and audit snapshots. Without `DATABASE_URL`, database integration tests are skipped; geocoder and service unit tests still run. To check browser failure handling, stop the API, click **Refresh**, then start the API and refresh again.

Implementation references: [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html), [Alembic async migrations](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic), [Vite environment variables](https://vite.dev/guide/env-and-mode).

## Warehouses

Run `make migrate` before using the warehouse page at http://localhost:5173.

| Method | Path | Action |
| --- | --- | --- |
| POST | `/warehouses` | Create (201) |
| GET | `/warehouses` | List active warehouses |
| GET | `/warehouses/{id}` | Read an active warehouse |
| PUT | `/warehouses/{id}` | Rename; preserve assigned coordinates |
| DELETE | `/warehouses/{id}` | Soft delete (204) |
| GET | `/warehouses/{id}/logs` | Read change history, including after deletion |

Create/update bodies contain only `name`. Coordinates are assigned automatically on creation and are read-only in API responses; sending latitude/longitude returns 422. Renaming preserves the saved location. Names are trimmed and must have 1–255 characters. The utility `random_warehouse_coordinates()` in `app/adapters/outbound/geocoding/warehouse_locations.py` randomly selects from 20 hardcoded Mar del Plata sample points, with no overlap with the 100 shipping address points. Selection is with replacement, so warehouses can share a point. Existing warehouse locations are preserved. Latitude must be between −90 and 90; longitude between −180 and 180. Coordinates use SQLAlchemy `Float` and PostgreSQL `DOUBLE PRECISION NOT NULL`, with database CHECK constraints. Invalid input returns 422; missing or deleted warehouses return 404 on normal CRUD routes.

All application tables must include timezone-aware `created_at`, `updated_at`, and nullable `deleted_at` columns using `TimestampMixin`. Deletion of business records is soft; list/read routes exclude deleted records. Future business tables must receive an audit trigger in their migration too. Alembic's internal version table is migration bookkeeping.

The warehouse database trigger maintains update timestamps and writes create/update/delete snapshots to `audit_logs` atomically, including direct SQL writes. Logs retain before/after JSON, table name, record ID, and time. Audit rows carry the same timestamp columns but are not recursively audited; there are no endpoints to modify/delete logs. No actor identity is captured because authentication is not implemented. Audit tracking begins when migration 0002 is applied; earlier changes cannot be reconstructed.

## Shipping addresses and admin

Open http://localhost:5173/#/admin/shipping-addresses or use the admin navigation.

| Method | Path | Action |
| --- | --- | --- |
| POST | `/shipping-addresses` | Geocode and create (201) |
| GET | `/shipping-addresses` | List active shipping addresses |
| GET | `/shipping-addresses/{id}` | Read an active shipping address |
| PUT | `/shipping-addresses/{id}` | Replace shipping details; re-geocode if the location changes |
| DELETE | `/shipping-addresses/{id}` | Soft delete (204) |
| GET | `/shipping-addresses/{id}/logs` | Read history, including after deletion |

Example create/update body:

```json
{
  "recipient_name": "Ana Pérez",
  "phone": "+54 223 555 0100",
  "address_line1": "San Martín 2500",
  "address_line2": "Apartment B",
  "city": "Mar del Plata",
  "state": "Buenos Aires",
  "postal_code": "B7600",
  "country_code": "AR",
  "delivery_instructions": "Ring the bell"
}
```

Phone, address line 2, and delivery instructions are optional/nullable. Required strings are trimmed and cannot be blank. Country codes accept two letters and normalize to uppercase. Coordinates are returned in responses but cannot be supplied by clients. They use `Float` in SQLAlchemy, `DOUBLE PRECISION NOT NULL` in PostgreSQL, and geographic range constraints. Both business tables share the database audit function `audit_record_change()`; migration 0003 renames the existing function without changing warehouse trigger behavior.

The geocoding boundary is:

```text
HTTP shipping address adapter
    → ShippingAddressService
        → Geocoder port → MockGeocoder → random_mar_del_plata_coordinates()
        → ShippingAddressRepository port → SQLAlchemy adapter → PostgreSQL
```

`app/domain/shipping_address.py` contains framework-free immutable address/coordinate values. The application service and ports have no FastAPI or SQLAlchemy imports. `app/main.py` wires the concrete repository and geocoder. A real provider implements async `Geocoder.geocode(AddressDetails) -> Coordinates`; replace `MockGeocoder` in the composition root and keep provider-specific HTTP and error handling in its outbound adapter. Providers signal lookup failures with `GeocodingUnavailable` (HTTP 503, no saved changes). Geocoding happens before the write transaction so external I/O does not hold a database transaction open.

Creating an address always awaits geocoding. Updates geocode again only when street, apartment/unit, city, state, postal code, or country changes. Recipient, phone, and delivery instruction edits keep existing coordinates. The resulting address and coordinates are audited together in the same transaction. Soft deletion and timestamps follow the warehouse conventions.

The mock randomly selects one of **100 distinct, hardcoded WGS84 sample points** from `app/adapters/outbound/geocoding/sample_locations.py`. Its selection utility stays inside the outbound geocoding adapter, separate from business rules. The inland sample grid spans latitude −38.008 to −37.990 and longitude −57.5875 to −57.565 in Mar del Plata, Buenos Aires. Geographic references: [Argentina Chamber of Deputies city location](https://www.hcdn.gob.ar/comisiones/permanentes/cdhygarantias/proyecto.html?exp=2906-D-2013) and [Mar del Plata coordinates](https://www.geodatos.net/coordenadas/argentina/mar-del-plata). These are synthetic test locations, not surveyed addresses or actual matches to submitted addresses. Repeated lookups may return the same point; there is no live geocoding request or artificial sleep.

Run `make migrate` before `make check`. Tests cover address CRUD, request validation, all location-change triggers, a replaceable async geocoder, provider failures without partial writes, coordinate constraints, audit rollback/direct SQL writes, and warehouse regression coverage.
