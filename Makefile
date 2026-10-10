.PHONY: install dev backend frontend test lint fmt eval eval-baseline synth record-demo build serve

PY := PYTHONPATH=backend uv run
UVICORN := uv run uvicorn app.main:app --app-dir backend

install:
	command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
	uv sync
	npm --prefix frontend install

dev: install
	@trap 'kill 0' EXIT; \
	$(UVICORN) --reload --reload-dir backend --port 8000 & \
	npm --prefix frontend run dev -- --port 5173 & \
	wait

backend:
	$(UVICORN) --reload --reload-dir backend --port 8000

frontend:
	npm --prefix frontend run dev -- --port 5173

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	@! grep -rEn 'sk-ant-[A-Za-z0-9_-]{10,}|AIza[0-9A-Za-z_-]{30,}' --include='*.py' --include='*.ts' --include='*.tsx' --include='*.json' --include='*.md' --exclude-dir=node_modules --exclude-dir=.venv . || (echo "possible API key committed" && exit 1)

fmt:
	uv run ruff format .
	uv run ruff check --fix .

eval:
	$(PY) python -m app.evaluation.runner --subset full --provider replay --gate

eval-baseline:
	$(PY) python -m app.evaluation.runner --subset full --provider replay --write-baseline

synth:
	@echo "WARNING: regenerating fixtures changes replay fingerprints; re-record afterwards."
	$(PY) python -m app.evaluation.synth.generator

record-demo:
	$(PY) python backend/scripts/record_demo.py

build:
	npm --prefix frontend ci
	npm --prefix frontend run build
	uv sync --no-dev

# Single port: FastAPI serves the built SPA from frontend/dist at http://localhost:8000
serve:
	npm --prefix frontend ci
	npm --prefix frontend run build
	$(UVICORN) --port 8000
