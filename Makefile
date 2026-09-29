# BizGrips Territory Engine — standard project commands.
# Windows users without GNU make: use `.\dev.ps1 <target>` (same targets).

ifeq ($(OS),Windows_NT)
PY := venv/Scripts/python.exe
VENV_CMD := python -m venv venv
else
PY := venv/bin/python
VENV_CMD := python3 -m venv venv
endif

SCENARIO ?= denver_suburban_available

.PHONY: setup test test-cov lint format dev db-upgrade db-revision seed-fixtures import-data clean

setup:
	@test -d venv || $(VENV_CMD)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Setup complete. Run 'make test' then 'make dev'."

test:
	$(PY) -m pytest -q

test-cov:
	$(PY) -m pytest -q --cov=app --cov-report=term-missing

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

dev:
	$(PY) -m uvicorn app.main:app --reload --port 8000

db-upgrade:
	$(PY) -m alembic upgrade head

# usage: make db-revision m="add something"
db-revision:
	$(PY) -m alembic revision --autogenerate -m "$(m)"

seed-fixtures:
	$(PY) scripts/seed_fixtures.py --scenario $(SCENARIO)

import-data:
	$(PY) scripts/import_geography.py
	$(PY) scripts/import_census.py

clean:
	$(PY) -c "import shutil,glob; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache','.ruff_cache','htmlcov','build'] + glob.glob('**/__pycache__', recursive=True)]"
