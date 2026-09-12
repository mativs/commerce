# Backend Assessment

FastAPI + PostgreSQL API with a React order workspace and admin screens.

## Setup

Requires Docker with Compose v2 and Make. Run from the project root:

```sh
cp .env.example .env
make up
make migrate
```

The migrations also add 5 warehouses, 5 sample shipping addresses, and 100 products priced in USD.

## Usage

- Open the [web app](http://localhost:5173) to create orders, edit items before checkout, enter shipping details, and view order results.
- Use the Admin tab to manage warehouses, shipping addresses, and products.
- Use the [API docs](http://localhost:8000/docs) to explore and try the endpoints.

Warehouse and admin shipping-address coordinates use mock locations in Mar del Plata. Order checkout also geocodes its own address snapshot. Deleted admin records retain their audit history.

Use `POST /orders` in the API docs to place an order. See [order checkout](docs/orders.md) for the request, demo stock setup, and retry behavior.

## Development

| Command | Action |
| --- | --- |
| `make check` | Run lint, tests, TypeScript checks, and the web build |
| `make test` | Run backend tests |
| `make logs` | Follow service logs |
| `make migrate` | Apply database migrations |
| `make down` | Stop services; keep database data |

Web changes reload automatically. After API edits, run `docker compose restart api`. After dependency changes, run `make up` to rebuild.
