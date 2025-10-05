# Trading Bot Platform (ETH-USDC)

Local-first orchestration layer for ETH-USDC trading strategies built on FastAPI, APScheduler, Coinbase Advanced Trade, and a lightweight HTMX dashboard.

**Important:** Keep `EXECUTION_ENABLED=false` unless you understand and accept the risk of placing live orders. The default configuration is safe for research and paper trading.

## Features

- Multi-stage LLM planning pipeline (Model 1 → Model 2 → Model 3) with stub mode for offline development.
- Coinbase Advanced Trade integrations for product metadata, order placement, fill synchronisation, and market data snapshots.
- APScheduler-based job orchestration for daily strategy, two-hour tactical plans, and five-minute fill polling.
- SQLAlchemy models with Alembic migrations for plans, prompts, orders, fills, price snapshots, and run logs.
- HTMX dashboard surfacing current plans, open orders, portfolio state, and scheduler activity.

## Architecture Overview

- `app/main.py` wires FastAPI, the dashboard routes, and the scheduler.
- `app/coinbase` encapsulates Coinbase Advanced Trade clients and helpers.
- `app/llm` defines the multi-step prompt pipeline and validation logic.
- `app/scheduler` hosts scheduled jobs, orchestration helpers, and manual triggers.
- `app/db` provides SQLAlchemy models, sessions, and Alembic migrations.
- `app/dashboard` renders HTMX views for monitoring the bot.

## Quickstart

1. Clone the repository and create a Python 3.11 virtual environment.
2. Activate the environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Copy configuration defaults and tailor them to your environment:

   ```bash
   cp .env.example .env
   ```

4. Start the application:

   ```bash
   uvicorn app.main:app --reload
   ```

Uvicorn will expose the API at `http://localhost:8000`, mount the HTMX dashboard, and boot the scheduler.

## Configuration

Set environment variables in `.env` (never commit real credentials):

- `OPENAI_API_KEY` – OpenAI Responses API key. Optional when `LLM_STUB_MODE=true`.
- `COINBASE_API_KEY` / `COINBASE_API_SECRET` – Coinbase Advanced Trade credentials used when execution is enabled.
- `DATABASE_URL` – SQLAlchemy URL (defaults to `sqlite:///./trading_bot.db`). Override for PostgreSQL deployments.
- `LLM_STUB_MODE` – `true` to use canned model responses for tests and development.
- `EXECUTION_ENABLED` – `false` by default; set `true` only when ready to submit live orders.
- `AUTO_MIGRATE_ON_START` – runs Alembic migrations automatically when the app boots (`true` is recommended).
- `OPENAI_REASONING_M1`, `OPENAI_REASONING_M2`, `OPENAI_REASONING_M3`, `OPENAI_REASONING_SUMMARISER` – tune reasoning effort per model (`minimal`, `medium`, or `high`).
- `DASHBOARD_BASIC_AUTH_ENABLED`, `DASHBOARD_BASIC_USER`, `DASHBOARD_BASIC_PASSWORD_HASH` – enable HTTP Basic auth for the dashboard and store the PBKDF2-SHA256 hash of your password.

Additional toggles live in `app/config.py`; extend the Pydantic settings model if you introduce new variables.

## Scheduler Jobs & Manual Triggers

- Daily strategy refresh at 00:00 UTC (Model 1).
- Two-hour tactical plan generation and validation (Model 2 + Model 3 + execution pipeline).
- Five-minute fill poller to capture fills placed outside the bot.

Development-friendly endpoints allow manual execution:

- `POST /force/daily`
- `POST /force/2h`

When market orders execute, the scheduler queues a follow-up run to capture the updated state.

## Database & Migrations

Alembic migrations live under `app/db/migrations`. When `AUTO_MIGRATE_ON_START=true`, the application applies them automatically. For manual control run:

```bash
alembic -c alembic.ini upgrade head
```

The default SQLite database is file-backed and created on first run; switch to PostgreSQL for production environments.

## Dashboard

Visit `http://localhost:8000/dashboard` to review the latest plans, open orders, portfolio snapshots, and scheduler history. HTMX keeps the panels updated without requiring full page reloads.

## Testing

Run the test suite with:

```bash
pytest
```

Ensure `LLM_STUB_MODE=true` and `EXECUTION_ENABLED=false` in your `.env` so tests do not call external services or place orders.

## Native Extensions

The project ships optional Rust helpers for PnL aggregation and order/fill reconciliation. Build them locally with [maturin](https://github.com/PyO3/maturin):

```bash
pip install maturin
maturin develop -m app/pnl_native/Cargo.toml
```

When the native module is not compiled the Python fallback remains active, so deployments without Rust tooling continue to function.

## Docker

Build and run the container image for parity with production deployments:

```bash
docker build -t trading-bot .
docker run --env-file .env -p 8000:8000 trading-bot
```

Provide a PostgreSQL `DATABASE_URL` when running in managed environments such as Railway; otherwise the container falls back to SQLite.

## Project Layout

```
app/
  coinbase/      # Coinbase Advanced Trade client and helpers
  dashboard/     # HTMX routes, templates, and assets
  db/            # SQLAlchemy models, sessions, and migrations
  llm/           # Prompt orchestration and validation logic
  scheduler/     # APScheduler jobs and orchestration helpers
  main.py        # FastAPI entrypoint wiring API, scheduler, and dashboard
scripts/alembic  # Alembic command helpers
tests/           # Pytest suites mirroring application modules
plan.md          # High-level build plan and decision record
```

## Responsible Use & Security

- Store secrets in `.env` only; never commit them to version control.
- Leave `EXECUTION_ENABLED=false` until you have verified order logic with sandbox data.
- Rotate Coinbase credentials regularly and restrict permissions to the minimum required for trading the ETH-USDC pair.
- Review model outputs when disabling stub mode; human-in-the-loop validation is strongly recommended before enabling live execution.

## Contributing

Contributions are welcome. Align with the repository guidelines:

- Follow PEP 8 and use explicit type hints.
- Use absolute imports under the `app.` namespace and JSON logging utilities from `app.logging`.
- Add targeted tests under `tests/` for new behaviour, including database migrations.
- Squash work into conventional commits (e.g., `fix: normalise candle timestamps`).

Open an issue to discuss significant changes before submitting a pull request.

## License

The project is currently provided without a published license. Contact the maintainers for usage questions and select an open-source license before wider distribution.
