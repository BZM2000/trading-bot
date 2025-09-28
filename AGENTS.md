# Repository Guidelines

## Project Structure & Module Organization
FastAPI boots from `app/main.py`; configuration is centralised in `app/config.py`. Trading logic and Coinbase clients sit under `app/coinbase/`, while LLM orchestration lives in `app/llm/` (Models 1–3 plus the summariser). Persistence code resides in `app/db/` with SQLAlchemy models, session helpers, and Alembic migrations inside `app/db/migrations/versions`. Scheduler jobs and HTMX dashboard routes share the `app/scheduler/` and `app/dashboard/` packages. Tests mirror this layout inside `tests/`.

## Build, Test & Development Commands
Create a virtualenv with `python -m venv .venv && source .venv/bin/activate`, then install dependencies via `pip install -r requirements.txt`. Run `uvicorn app.main:app --reload` for the API, dashboard, and background scheduler. Keep the schema current with `alembic -c alembic.ini upgrade head`, and generate revisions using `alembic revision --autogenerate -m "short description"`. Execute `pytest` (optionally `-k` or `-vv`) before every push.

## Coding Style & Naming Conventions
Stick to PEP 8 with four-space indentation and type hints on public functions. Use `snake_case` for functions, variables, and Alembic revisions, `PascalCase` for SQLAlchemy and Pydantic models, and `UPPER_CASE` for constants such as product IDs. Align response schemas with Coinbase payloads, and add concise module docstrings when behaviour is non-obvious. No auto-formatter is enforced, so rely on `pytest --collect-only` or `python -m compileall app tests` to catch syntax slips.

## Testing Guidelines
Unit tests belong in `tests/test_*.py` with descriptive method names. Stub Coinbase and OpenAI calls by setting `LLM_STUB_MODE=true` and `EXECUTION_ENABLED=false` in `.env`; this makes integration tests deterministic and removes the need for live keys. Prefer fixture builders over hard-coded JSON and add database assertions when migrations introduce new fields.

## Commit & Pull Request Guidelines
Follow Conventional Commit prefixes (`feat:`, `fix:`, `chore:`) written in the imperative voice. Include migration files alongside related model changes, and note any new environment variables or scheduler endpoints in the description. Pull requests should document manual test results and, when dashboard templates change, attach updated screenshots or terminal captures.

## Environment & Safety Checks
Copy `.env.example` to `.env` and fill the OpenAI and Coinbase secrets plus `DATABASE_URL`. Locally you can rely on the bundled SQLite fallback, but Railway deployments must use the managed Postgres URL. `AUTO_MIGRATE_ON_START=true` runs Alembic on startup—leave it enabled unless you manage migrations manually. Portfolio prompts already ignore non-ETH/USDC balances, keeping LLM context focused; verify this behaviour after modifying account parsing. Scheduler endpoints at `POST /force/daily` and `POST /force/2h` help trigger runs during QA.
