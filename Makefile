PYTHON ?= python
PIP ?= $(PYTHON) -m pip

.PHONY: install-dev lint format-check test db-upgrade db-downgrade \
	pre-commit-install pre-commit-check compose-config up down

install-dev:
	$(PIP) install -r services/api/requirements-dev.txt -r services/worker/requirements.txt pre-commit

lint:
	ruff check services/api services/worker eval

format-check:
	ruff format --check services/api services/worker eval

test:
	cd services/api && pytest
	cd services/worker && pytest
	pytest eval/tests

db-upgrade:
	cd services/api && alembic upgrade head

db-downgrade:
	cd services/api && alembic downgrade -1

pre-commit-install:
	pre-commit install

pre-commit-check:
	pre-commit run --all-files

compose-config:
	docker compose config --quiet

up:
	docker compose up --build

down:
	docker compose down
