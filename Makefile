PY ?= python

.PHONY: install lint format test eval migrate-check run-api run-worker run-watcher ui

install:
	$(PY) -m pip install -e ".[dev]"

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests
	$(PY) -m mypy

format:
	$(PY) -m ruff format src tests
	$(PY) -m ruff check --fix src tests

test:
	$(PY) -m pytest -q

# Gates arrive in M11; until then this is a no-op.
eval:
	@if [ -f eval/run_eval.py ]; then $(PY) -m eval.run_eval; else echo "eval: not implemented yet (M11)"; fi

# Alembic arrives in M1; until then this is a no-op.
migrate-check:
	@if [ -f alembic.ini ]; then $(PY) scripts/migrate_check.py; else echo "migrate-check: no migrations yet (M1)"; fi

run-api:
	$(PY) -m uvicorn genie_copilot.api.main:app --reload

run-worker:
	$(PY) -m genie_copilot.orchestrator.worker

run-watcher:
	$(PY) -m genie_copilot.watcher.s3_watcher

ui:
	cd ui && npm install && npm run build
