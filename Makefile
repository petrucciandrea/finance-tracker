# Convenience commands for local development.
# Run `make help` to list them.

.PHONY: help up down logs test test-cov migrate migrate-down purge purge-dry lint fmt shell-backend shell-db

help:
	@echo "up             - start all services (docker compose up -d)"
	@echo "down           - stop all services"
	@echo "logs           - tail backend logs"
	@echo "test           - run the pytest suite inside the backend container"
	@echo "test-cov       - run pytest with coverage report"
	@echo "migrate        - apply Alembic migrations (upgrade head)"
	@echo "migrate-down   - roll back the last migration"
	@echo "purge          - apply the data retention rules (permanent)"
	@echo "purge-dry      - show what purge would remove, change nothing"
	@echo "lint           - run ruff + mypy on the backend"
	@echo "fmt            - auto-format backend code with ruff"
	@echo "shell-backend  - open a shell in the backend container"
	@echo "shell-db       - open a psql shell on the dev database"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f backend

# Runs against db_test (TEST_DATABASE_URL). db_test now has a named
# volume, so this is a safety net (harmless if already up to date), not a
# workaround for a resetting DB — see test-reset-db for actually wiping it.
test: migrate-test
	docker compose exec backend pytest -v

test-cov:
	docker compose exec backend pytest --cov=app --cov-report=term-missing

migrate:
	docker compose exec backend alembic upgrade head

# Applies migrations to db_test. Its data lives in a named volume, so this
# is usually a no-op; `make test` runs it first as a safety net.
migrate-test:
	docker compose exec -e DATABASE_URL=postgresql+psycopg://postgres:postgres@db_test:5432/finance_tracker_test backend alembic upgrade head

# Use this when the test DB is in a broken/inconsistent state (e.g. it
# thinks it's fully migrated but tables are missing) or you just want a
# guaranteed-clean slate. Wipes db_test's volume entirely.
test-reset-db:
	docker compose down -v db_test
	docker compose up -d db_test
	sleep 3
	$(MAKE) migrate-test

# Data retention (see backend/app/services/retention.py). Schedule `purge` on the
# host (cron) — the app does not run it by itself.
purge:
	docker compose exec backend python -m app.purge

purge-dry:
	docker compose exec backend python -m app.purge --dry-run

migrate-down:
	docker compose exec backend alembic downgrade -1

lint:
	docker compose exec backend ruff check .
	docker compose exec backend mypy app

fmt:
	docker compose exec backend ruff format .

shell-backend:
	docker compose exec backend bash

shell-db:
	docker compose exec db psql -U postgres -d finance_tracker