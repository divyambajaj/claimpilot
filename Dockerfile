# ClaimPilot: keyless hosted demo (replay provider). Build: docker build -t claimpilot .
# Stage 1: build the React SPA.
FROM node:24-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime. FastAPI serves /api and the built SPA from one port.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

COPY backend/app backend/app
# Exactly what the app reads at runtime (config.py, seed.py, evaluation/runner.py)
COPY data/policies data/policies
COPY data/rulesets data/rulesets
COPY data/demo_receipts data/demo_receipts
COPY data/eval data/eval
COPY data/replay data/replay
COPY --from=frontend /app/frontend/dist frontend/dist

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LLM_PROVIDER=replay \
    SEED_DEMO=1 \
    DATABASE_URL=sqlite:////tmp/app.db \
    REPLAY_DELAY_S=0.3 \
    PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT}"]
