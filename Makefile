.PHONY: up down build logs api-logs web-logs test check migrate migration api-shell web-shell db-shell

up:
	docker compose up --build -d --wait
down:
	docker compose down
build:
	docker compose build
logs:
	docker compose logs -f
api-logs:
	docker compose logs -f api
web-logs:
	docker compose logs -f web
test:
	docker compose run --rm api pytest
check:
	docker compose run --rm api ruff check .
	docker compose run --rm api ruff format --check .
	docker compose run --rm api pytest
	docker compose run --rm web npm run check
migrate:
	docker compose run --rm api alembic upgrade head
migration:
	@test -n "$(name)" || (echo 'Usage: make migration name="create_orders"'; exit 1)
	docker compose run --rm api alembic revision --autogenerate -m "$(name)"
api-shell:
	docker compose exec api sh
web-shell:
	docker compose exec web sh
db-shell:
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'
