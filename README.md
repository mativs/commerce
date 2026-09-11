# Backend Assessment

FastAPI + PostgreSQL API with a React admin app for warehouses, shipping addresses, and products.

## Setup

Requires Docker with Compose v2 and Make. Run from the project root:

```sh
cp .env.example .env
make up
make migrate
```

The migrations also add 5 warehouses, 5 sample shipping addresses, and 100 products priced in USD.

## Usage

- Open the [admin app](http://localhost:5173) to create, edit, delete, and view change history for warehouses, shipping addresses, and products.
- Use the [API docs](http://localhost:8000/docs) to explore and try the endpoints.

Warehouse and shipping address coordinates are assigned automatically using mock locations in Mar del Plata. Deleted records retain their audit history.

## Development

| Command | Action |
| --- | --- |
| `make check` | Run lint, tests, TypeScript checks, and the web build |
| `make test` | Run backend tests |
| `make logs` | Follow service logs |
| `make migrate` | Apply database migrations |
| `make down` | Stop services; keep database data |

Web changes reload automatically. After API edits, run `docker compose restart api`. After dependency changes, run `make up` to rebuild.
