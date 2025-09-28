# Repository Guidelines

## Project Structure & Module Organization
FastAPI entry point `app/main.py`; `app/config.py` exposes typed settings. Domain packages: `app/coinbase/` for Advanced Trade clients and validators, `app/llm/` for the three-model workflow, `app/scheduler/` for APScheduler jobs, and `app/db/` for SQLAlchemy models, CRUD helpers, and Alembic scripts (`app/db/migrations/versions`). Dashboard routes and HTMX templates live in `app/dashboard/`. Shared logging is in `app/logging.py`. Tests mirror these modules under `tests/`.

## Build, Test, and Development Commands
`python -m venv .venv && source .venv/bin/activate` creates an isolated environment. `pip install -r requirements.txt` installs runtime plus pytest dependencies. `alembic -c alembic.ini upgrade head` syncs schema with the database named by `DATABASE_URL`; skip it when you stick with the default SQLite file. `uvicorn app.main:app --reload` starts the API, dashboard, and scheduler. `pytest` executes the suite; add `-k` filters or `-vv` for details. Run `alembic revision --autogenerate -m "desc"` after model changes.

## Coding Style & Naming Conventions
Follow PEP 8 with four-space indentation and explicit type hints. Use `snake_case` for functions and variables, `PascalCase` for classes and Pydantic models, and `UPPER_CASE` for constants such as product IDs. Group SQLAlchemy model fields by logical entity and align column names with Coinbase payloads. With no enforced formatter, run `python -m compileall app tests` or `pytest --collect-only` to catch syntax issues before pushing.

## Testing Guidelines
Unit tests live in `tests/test_*.py`. Mirror new modules with matching test files and mock external calls via `httpx` or `pytest` monkeypatching. Set `LLM_STUB_MODE=true` and `EXECUTION_ENABLED=false` in `.env` when exercising flows that touch OpenAI or order placement; those toggles make API keys optional for local runs. Use `pytest --maxfail=1 --disable-warnings` before review and prefer fixture-based data builders over live API calls.

## Commit & Pull Request Guidelines
This checkout lacks Git history, so default to Conventional Commits (`feat:`, `fix:`, `chore:`) in imperative mood, e.g., `feat: add fill reconciliation job`. Keep commits focused and include migration files with the code they support. Pull requests must outline intent, list new environment variables, explain testing performed, and attach dashboard screenshots when templates change.

## Environment & Safety Checks
Copy `.env.example` to `.env`, populate API keys, and leave `EXECUTION_ENABLED=false` until live trading is intentional. The app falls back to `sqlite:///./trading_bot.db` when `DATABASE_URL` is unset; set your Railway Postgres URL before running migrations. Portfolio snapshots and prompts are filtered to the product’s base and quote currencies to minimise irrelevant context. `AUTO_MIGRATE_ON_START=true` keeps Alembic in sync during deploys; disable only if you run migrations out-of-band. Trigger scheduler flows quickly with `POST /force/daily` or `POST /force/2h` during local testing, and reset the database if Alembic downgrades are required. Model defaults target `gpt-5` (high reasoning) for Model 1, `gpt-5` (medium reasoning) for Model 2, and `gpt-5-mini` (minimal reasoning) for Model 3 plus the summariser; override via `OPENAI_MODEL_M*` and `OPENAI_REASONING_*` env vars when experimenting.
