# Backend Assessment

FastAPI + PostgreSQL API with a React order workspace.

## Setup

Requires Docker with Compose v2 and Make. Run from the project root:

```sh
cp .env.example .env
make up
make migrate
```

The migrations also add 5 warehouses and 10 products priced in USD, with varied stock across warehouses.

## Usage

- Open the [web app](http://localhost:5173) to create orders, edit items before checkout, enter shipping details, and view order results.
- Warehouses are maintained as internal fulfillment data and are read-only through the API.
- Use the [API docs](http://localhost:8000/docs) to explore and try the endpoints.

Warehouse coordinates use mock locations in Mar del Plata. Order checkout geocodes its own address snapshot.

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

All list endpoints accept `limit` (default 50, maximum 100) and `offset` (default 0). Responses remain arrays. The order catalog supports paginated name/SKU search.

## Logging

The API writes one JSON object per line to stdout. Use `make api-logs` to follow
logs locally; production log collectors can ingest the container output directly.
Set `LOG_LEVEL` to `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, or `CRITICAL`.
`ENVIRONMENT` is included in every event. Restart the API after configuration changes.

Every HTTP response includes a generated `X-Request-ID` (also exposed through CORS).
Use it to correlate request events with checkout events. Request logs include the
method, route template, status and duration in milliseconds; 4xx responses use
WARNING and 5xx/errors use ERROR. Startup and shutdown are logged too. Uvicorn's
raw access logs are replaced by these structured request events.

Checkout logs record order creation, replay, payment success, cancellation reason,
and uncertain payment outcomes (`order.payment_pending`), using order IDs. A pending
payment warning means the payment attempt failed or timed out and may have succeeded;
the existing behavior preserves reserved inventory for that order.

Application events omit request/response bodies, query strings, raw URL paths,
headers, addresses, payment data and idempotency keys. Exceptions include their type
and stack locations, without exception messages, source lines or local variables.
When adding logs, use fixed event names and the allowed structured fields in
`app/infrastructure/logging.py`; never interpolate customer input or credentials.
Third-party log messages are formatted but are not automatically scrubbed, so review
any additional library logging before enabling it. Configure retention and rotation
in the deployment's container runtime or log collector.
