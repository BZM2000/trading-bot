# Trading Bot Platform (ETH-USDC)

This project implements a local-first orchestration layer for an ETH-USDC trading bot that can stage limit, stop-limit, and market orders. It follows the plan in `plan.md` and provides:

- Automated daily, two-hourly, and five-minute jobs coordinated by APScheduler.
- Coinbase Advanced Trade integrations for best bid/ask snapshots, product metadata, order placement, and fill synchronisation.
- Three-stage LLM workflow (Model 1 → Model 2 → Model 3) using the OpenAI Responses API, with optional stub mode for offline testing. Model 1 produces daily strategic guidance with percentage-based sizing rules, Model 2 crafts a single tactical order (limit, stop-limit, or market), and Model 3 validates the machine-readable payload.
- PostgreSQL persistence via SQLAlchemy/Alembic for plans, prompts, orders, fills, price and portfolio snapshots, and run logs.
- HTMX FastAPI dashboard exposing current plans, orders, portfolio, and recent job runs.

## Prerequisites

- Python 3.11+
- SQLite (default) or PostgreSQL 14+ for production deployments
- OpenAI API key (Responses API access)
- Coinbase Advanced Trade API key/secret

## Environment configuration

Create a `.env` based on `.env.example`:

```bash
cp .env.example .env
```

Update the file with real credentials and desired toggles. Key variables:

- `OPENAI_API_KEY`: OpenAI Responses API key.
- `COINBASE_API_KEY` / `COINBASE_API_SECRET`: Coinbase Advanced Trade credentials.
- `DATABASE_URL`: SQLAlchemy URL. Defaults to `sqlite:///./trading_bot.db` for local testing; set your Railway Postgres URL when deploying.
- `LLM_STUB_MODE`: set to `true` for offline testing with canned LLM outputs (OpenAI key optional in this mode).
- `EXECUTION_ENABLED`: set to `true` to allow the executor to place real orders (requires Coinbase credentials; default `false`).
- `AUTO_MIGRATE_ON_START`: keep `true` so the app runs Alembic migrations automatically on startup (set `false` if you prefer manual control).
- `OPENAI_REASONING_M1` / `OPENAI_REASONING_M2` / `OPENAI_REASONING_M3` / `OPENAI_REASONING_SUMMARISER`: override reasoning effort per model (`high`, `medium`, `minimal`). Defaults align with the repository guidelines.

## Dependency installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Database migrations

Initialise the schema with Alembic (optional when `AUTO_MIGRATE_ON_START=true` because the app runs this on boot):

```bash
alembic -c alembic.ini upgrade head
```

The Alembic environment reads `DATABASE_URL` via the application settings module. SQLite users can skip this step because the default file-backed database is created on first run.

## Running the application

Start the FastAPI app with Uvicorn:

```bash
uvicorn app.main:app --reload
```

The scheduler boots automatically with three jobs:

- Daily plan at 00:00 UTC (`Model 1`).
- Tactical plan every two hours (`Model 2` + `Model 3` + execution pipeline). When a market order executes, a follow-up two-hour run is scheduled ~10 seconds later to capture the new state.
- Fill poller every five minutes.

Manual triggers (useful in development) are available:

- `POST /force/daily`
- `POST /force/2h`

## Dashboard

Navigate to `http://localhost:8000/dashboard` to view plans, orders, portfolio snapshots, and recent run logs. Sections auto-refresh via HTMX.

## Testing

Run the unit test suite with:

```bash
pytest
```

Tests cover validators, market indicator helpers, execution service logic (including market/stop-limit payloads), and Model 3 schema enforcement. They do not require external services.

## Docker

A development Dockerfile is provided for convenience:

```bash
docker build -t trading-bot .
docker run --env-file .env -p 8000:8000 trading-bot
```

Provide Railway Postgres credentials via `DATABASE_URL` when running against managed storage; otherwise the default SQLite file will be used inside the container.

## Notes & next steps

- `LLM_STUB_MODE=true` keeps the system offline-friendly during development. Toggle off when ready for real OpenAI calls.
- Override `DATABASE_URL` only when you provision a managed database (e.g. Railway Postgres); the default SQLite file supports local experimentation.
- Leave `AUTO_MIGRATE_ON_START=true` on Railway so migrations run automatically during deploys; set it to `false` only if you manage Alembic manually.
- Model 1 receives only market context and high-level run history (capped at the 20 most recent entries) to stay focused on broader strategy. Model 2 additionally sees the filtered portfolio snapshot for the tradable pair.
- `EXECUTION_ENABLED` must remain false unless you are prepared to place real orders.
- Extend `tests/` with integration tests as real API credentials become available.
