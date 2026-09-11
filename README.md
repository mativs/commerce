# Backend Assessment

## Overview

A small API + web monorepo: a technical foundation with no product functionality.

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

Dependencies point inward: adapters → application → domain. The diagram shows intended placement; there are no use cases or ports yet. `app/main.py` is the composition root; configuration and database lifecycle live in infrastructure. Domain and application packages contain no framework imports. Add only abstractions required by concrete use cases; no generic repositories, unit-of-work framework or speculative entities.

Future SQLAlchemy models belong in `adapters/outbound/persistence/models.py`, using `Mapped[...]` and `mapped_column`. Import any additional model modules there so Alembic sees their metadata. Introduce separate domain objects only when behavior or isolation warrants them; domain code must never import SQLAlchemy.

## Web architecture

React is a deliberately thin interface over the API. `src/api/client.ts` uses browser `fetch` and the public `VITE_API_URL` variable. `HomePage` displays loading, healthy and error states with a manual retry and a five-second timeout. Future workflow UI can live under `pages`, with components extracted when needed. There is no routing, state library or SDK framework.

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

Alembic reads application settings and `Base.metadata`, using an async connection with `run_sync`. There are no application tables or revisions yet. `upgrade head` initializes Alembic tracking. Always review generated migrations before applying them; migrations run explicitly, not at API startup.

## Testing

```sh
make test
make check
```

The health test covers HTTP 200, its JSON payload, allowed CORS and rejection of an untrusted origin; it needs no live database. To check browser failure handling, stop the API with `docker compose stop api`, click **Check again**, confirm **Unavailable**, then run `docker compose start api` and click **Try again**.

Implementation references: [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html), [Alembic async migrations](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic), [Vite environment variables](https://vite.dev/guide/env-and-mode).
