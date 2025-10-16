# Trading Bot Platform (ETH-USDC)

Local-first orchestration layer for ETH-USDC trading strategies built on FastAPI, APScheduler, Coinbase Advanced Trade, and a lightweight HTMX dashboard. The project is optimised for experimentation while keeping a path to production.

> **Important:** Leave `EXECUTION_ENABLED=false` unless you understand and accept the risk of placing live orders. The default configuration keeps the bot in research/paper-trading mode.

## Table of Contents
- [Highlights](#highlights)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Scheduler & Manual Triggers](#scheduler--manual-triggers)
- [Dashboard](#dashboard)
- [Database & Migrations](#database--migrations)
- [Testing](#testing)
- [Native Extensions](#native-extensions)
- [Deployment Options](#deployment-options)
- [Safety & Responsible Use](#safety--responsible-use)
- [Contributing](#contributing)
- [License](#license)

## Highlights

- Multi-stage LLM planning pipeline (Model 1 -> Model 2 -> Model 3) with stub mode for offline development.
- Coinbase Advanced Trade integration for product metadata, order placement, fill synchronisation, and market data snapshots.
- APScheduler-based orchestration for plan, order, monitor, and PnL refresh cycles, with manual triggers for local testing.
- SQLAlchemy models with Alembic migrations covering plans, prompts, orders, fills, price snapshots, and run logs.
- HTMX dashboard surfacing current plans, open orders, portfolio state, and scheduler activity without full reloads.
- Local-first configurations, Docker support, and Railway-friendly deployment defaults.

## Architecture

- `app/main.py` wires FastAPI endpoints, the HTMX dashboard routes, and the scheduler bootstrap.
- `app/coinbase` encapsulates Coinbase Advanced Trade clients and helpers.
- `app/llm` defines the multi-step prompt pipeline, validation logic, and guardrails.
- `app/scheduler` hosts scheduled jobs, orchestration helpers, and manual triggers.
- `app/db` provides SQLAlchemy models, sessions, CRUD wrappers, and Alembic migrations.
- `app/dashboard` renders HTMX views for monitoring the bot.

Project layout:

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

## Getting Started

### Prerequisites

- Python 3.11
- (Optional) Coinbase Advanced Trade API credentials for live execution
- A `.env` file derived from `.env.example`

### Local Setup

1. Clone the repository and create a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install runtime and test dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy configuration defaults and customise as needed:

   ```bash
   cp .env.example .env
   ```

4. Launch the application:

   ```bash
   uvicorn app.main:app --reload
   ```

   Uvicorn exposes the API at `http://localhost:8000`, mounts the HTMX dashboard, and boots the scheduler.

5. (Optional) Run the test suite to validate your environment:

   ```bash
   pytest
   ```

## Configuration

Environment variables live in `.env` (never commit real credentials). Key settings include:

- `OPENAI_API_KEY` - OpenAI Responses API key. Optional when `LLM_STUB_MODE=true`.
- `LLM_STUB_MODE` - Set to `true` for canned model responses during tests and development.
- `OPENAI_REASONING_M1`, `OPENAI_REASONING_M2`, `OPENAI_REASONING_M3`, `OPENAI_REASONING_SUMMARISER` - Tune reasoning effort (`minimal`, `medium`, or `high`) per prompt stage.
- `COINBASE_API_KEY`, `COINBASE_API_SECRET` - Coinbase Advanced Trade credentials used when execution is enabled.
- `DATABASE_URL` - SQLAlchemy connection string (defaults to `sqlite:///./trading_bot.db`). Override for PostgreSQL deployments.
- `AUTO_MIGRATE_ON_START` - Automatically run Alembic migrations when the app boots (`true` is recommended).
- `EXECUTION_ENABLED` - `false` by default; set `true` only when ready to submit live orders.
- `DASHBOARD_BASIC_AUTH_ENABLED`, `DASHBOARD_BASIC_USER`, `DASHBOARD_BASIC_PASSWORD_HASH` - Enable HTTP Basic auth for the dashboard and supply the PBKDF2-SHA256 hash of your password.

Additional toggles live in `app/config.py`; extend the Pydantic settings model if you introduce new variables. The LLM prompts assume ~0.15% maker and ~0.25% taker fees, while the scheduler pads BUY sizing with internal 0.35%/0.75% cushions to guard against slippage; this deliberate mismatch keeps prompts focused on strategy while execution remains conservative.

## Scheduler & Manual Triggers

- Plan process runs at 00:00 UTC to capture the daily market narrative (Model 1).
- Order process executes the tactical pipeline (Model 2/3 + execution) and is scheduled by monitor runs.
- Monitor process runs every minute to sync open orders and fills, triggering the order process once the book clears.
- PnL process captures portfolio performance snapshots every six hours.

Manual endpoints for local development:

- `POST /force/plan`
- `POST /force/order`
- `POST /force/pnl`

When market orders fill, the scheduler queues a follow-up order run to process the updated state.

## Dashboard

Visit `http://localhost:8000/dashboard` to review the latest plans, open orders, portfolio snapshots, and scheduler history. HTMX keeps panels refreshed without page reloads. Enable HTTP Basic auth via environment variables when exposing the dashboard beyond localhost.

## Database & Migrations

Alembic migrations reside under `app/db/migrations`. With `AUTO_MIGRATE_ON_START=true`, the application handles upgrades automatically. For manual control run:

```bash
alembic -c alembic.ini upgrade head
```

The default SQLite database is file-backed and created on first run; switch to PostgreSQL for production workloads. When adding tables, define SQLAlchemy models in `app/db/models.py`, scaffold migrations, extend CRUD helpers, and cover changes in `tests/test_db_migrate.py`.

## Testing

Run the suite with:

```bash
pytest
```

Ensure `LLM_STUB_MODE=true` and `EXECUTION_ENABLED=false` in your `.env` to prevent external API calls or live orders during tests.

## Native Extensions

Optional Rust helpers accelerate PnL aggregation and order/fill reconciliation. Build them with [maturin](https://github.com/PyO3/maturin):

```bash
pip install maturin
maturin develop -m app/pnl_native/Cargo.toml
```

Without the compiled extension, Python fallbacks remain active so deployments without Rust toolchains continue to function.

## Deployment Options

- **Local (Uvicorn):** `uvicorn app.main:app --reload` boots the API, dashboard, and scheduler with auto-migrations enabled when configured.
- **Docker:** Build and run for parity with production:

  ```bash
  docker build -t trading-bot .
  docker run --env-file .env -p 8000:8000 trading-bot
  ```

  Provide a PostgreSQL `DATABASE_URL` in managed environments; otherwise the container defaults to SQLite.

- **Railway or cloud:** The repository is Railway-ready. Authenticate with the Railway CLI, supply environment variables (including `DATABASE_URL` and API keys), and deploy the image or use the provided Dockerfile.

## Safety & Responsible Use

- Cryptocurrency trading carries significant financial risk - use this project at your own risk and validate every change before enabling live execution.
- Keep `EXECUTION_ENABLED=false` until strategy logic and order flows are thoroughly reviewed.
- Store secrets exclusively in `.env`; never commit them to version control.
- Rotate Coinbase credentials regularly and scope permissions to the ETH-USDC pair.
- Review LLM outputs when disabling stub mode; human-in-the-loop validation is strongly recommended prior to live trading.

## Contributing

Contributions are welcome:

- Follow PEP 8, use explicit type hints, and prefer absolute imports under the `app.` namespace.
- Keep JSON logging consistent by reusing helpers from `app.logging`.
- Mirror new modules with targeted tests under `tests/`, including migration coverage.
- Use conventional commits (e.g., `fix: normalise candle timestamps`) and keep each commit scoped.
- Open an issue to discuss significant changes before submitting a pull request.

## License

No open-source license is published yet. Choose and document an appropriate license before the project is made public.
