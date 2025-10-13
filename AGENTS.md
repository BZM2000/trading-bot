# Repository Guidelines

## Project Structure & Module Organization
The entrypoint is `app/main.py`, which wires FastAPI, the APScheduler orchestrator, and the HTMX dashboard. Key packages are `app/coinbase` (Advanced Trade client), `app/llm` (multi-step prompts), `app/scheduler` (jobs and orchestration), `app/db` (SQLAlchemy models, sessions, Alembic migrations under `app/db/migrations`), and `app/dashboard` (templates and routes). Tests mirror these modules in `tests/`. Root assets (`requirements.txt`, `pytest.ini`, `Dockerfile`) support local and container flows, with Alembic helpers under `scripts/alembic`.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` — set up the Python 3.11 environment.
- `pip install -r requirements.txt` — install runtime and test dependencies.
- `uvicorn app.main:app --reload` — start the API, dashboard, and scheduler; auto-migrations run when enabled.
- `alembic -c alembic.ini upgrade head` — apply migrations manually if auto-run is disabled.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indents and explicit type hints, matching `app/main.py` and `app/config.py`. Keep module and function names `snake_case`, classes `PascalCase`, and extend existing Pydantic models for new settings or payloads. Prefer absolute imports via the `app.` package and use `app.logging` utilities to keep JSON logs consistent.

## LLM Prompt vs Execution Fee Buffers
Prompts tell the models to assume ≈0.15% maker and ≈0.25% taker fees so they stay focused on high-level edges. The scheduler still applies internal safety cushions (0.35%/0.75%) when sizing BUY orders to cover real-world slippage and taker risk. This intentional mismatch keeps prompts simple while guarding execution.

## Testing Guidelines
Tests live in `tests/test_*.py` and use pytest. Mirror new modules with targeted test files that cover validation, scheduler filters, and database helpers. Default `.env` should set `LLM_STUB_MODE=true` and `EXECUTION_ENABLED=false` so the suite runs offline. When migrations adjust schemas, update `tests/test_db_migrate.py` accordingly.

## Commit & Pull Request Guidelines
History favours conventional commits (`fix: normalise candle timestamps`). Write imperative subjects under 72 characters and keep each commit scoped. Pull requests should include a brief behaviour summary, linked issues, configuration or migration callouts, screenshots for dashboard changes, and test evidence (`pytest`, manual `/force/*` trigger). Highlight follow-up work for reviewer awareness.

## Security & Configuration Tips
Secrets belong in `.env` copied from `.env.example`; never commit them. Use `app.db.url_normaliser` to coerce database URLs and prefer the default SQLite database for local work. This is a live working trading bot deployed on railway.com. Any change can be deployed to railway through railway CLI which is installed and authenticated and ready to use. 

## Adding New Database Tables
Define a SQLAlchemy model in `app/db/models.py`, scaffold an Alembic migration under `app/db/migrations/versions`, and add CRUD wrappers plus targeted tests (usually in `tests/test_db_migrate.py`). Keep enum names stable, reuse existing helpers in `app/db/crud.py`, and document build steps if the change affects deployment automation.
