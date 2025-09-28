# Trading Bot Platform (ETH-USDC)

This project implements a local-first orchestration layer for an ETH-USDC limit-order trading bot. It follows the plan in `plan.md` and provides:

- Automated daily, two-hourly, and five-minute jobs coordinated by APScheduler.
- Coinbase Advanced Trade integrations for best bid/ask snapshots, product metadata, order placement, and fill synchronisation.
- Three-stage LLM workflow (Model 1 → Model 2 → Model 3) using the OpenAI Responses API, with optional stub mode for offline testing.
- PostgreSQL persistence via SQLAlchemy/Alembic for plans, prompts, orders, fills, price and portfolio snapshots, and run logs.
- HTMX FastAPI dashboard exposing current plans, orders, portfolio, and recent job runs.

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
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
- `DATABASE_URL`: SQLAlchemy URL (e.g. `postgresql+psycopg://user:pass@localhost:5432/trading_bot`).
- `LLM_STUB_MODE`: set to `true` for offline testing with canned LLM outputs.
- `EXECUTION_ENABLED`: set to `true` to allow the executor to place real orders (default `false`).
- `OPENAI_REASONING_M1` / `OPENAI_REASONING_M2` / `OPENAI_REASONING_M3` / `OPENAI_REASONING_SUMMARISER`: override reasoning effort per model (`high`, `medium`, `minimal`). Defaults align with the repository guidelines.

## Dependency installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Database migrations

Initialise the schema with Alembic:

```bash
alembic -c alembic.ini upgrade head
```

The Alembic environment reads `DATABASE_URL` via the application settings module.

## Running the application

Start the FastAPI app with Uvicorn:

```bash
uvicorn app.main:app --reload
```

The scheduler boots automatically with three jobs:

- Daily plan at 00:00 UTC (`Model 1`).
- Tactical plan every two hours (`Model 2` + `Model 3` + execution pipeline).
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

Tests cover validators, market indicator helpers, and Model 3 schema enforcement. They do not require external services.

## Docker

A development Dockerfile is provided for convenience:

```bash
docker build -t trading-bot .
docker run --env-file .env -p 8000:8000 trading-bot
```

Ensure the container can reach PostgreSQL and has valid API credentials.

## Notes & next steps

- `LLM_STUB_MODE=true` keeps the system offline-friendly during development. Toggle off when ready for real OpenAI calls.
- `EXECUTION_ENABLED` must remain false unless you are prepared to place real orders.
- Extend `tests/` with integration tests as real API credentials become available.
