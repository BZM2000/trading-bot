Scope recap

Market: ETH‑USDC (spot only).

Schedules (UTC): Daily at 00:00 → Model 1 (24‑hour plan). Every 2h → Model 2 proposes 0–2 limit orders (at most one BUY and one SELL). Every 5m → poll fills; if any fill occurs, run Model 2 immediately.

Order rules: limit only; GTD 2h expiry; post_only=true; maintain ≤2 open orders in total (one buy + one sell).

Drift check: after Model 2+3 produce orders but before placement, re‑fetch price; if move vs the price at Model 2 start ≥ 0.5%, rerun Model 2+3 now.

No portfolio caps. Enforce a minimum distance from current mid‑price (default: 0.15%, configurable).

Context:

Model 1 sees the last seven Model‑1 prompt/response histories (compressed to 500 words each) and brief details of all executed orders in the last 7 days.

Model 2 sees today’s daily plan, the last seven Model‑2 histories (500‑word compaction), executed orders in the last 24h, and the latest portfolio.

OpenAI features: Responses API with web_search tool for Model 1 & 2; Structured Outputs for Model 3 to guarantee valid JSON. 
platform.openai.com
+3
platform.openai.com
+3
platform.openai.com
+3

Coinbase features you’ll call: Create Order using GTD fulfilment (limit_limit_gtd with end_time and post_only), Get Best Bid/Ask, Get Product (increments/min sizes), Get Product Candles, and List Orders/List Fills. 
Coinbase Developer Docs
+4
Coinbase Developer Docs
+4
Coinbase Developer Docs
+4

1) Local project setup

1.1 Scaffold repo

/app
  main.py                    # FastAPI app entry + APScheduler
  config.py                  # env, constants, toggles
  logging.py                 # structured logs

  /db
    models.py                # SQLAlchemy models
    session.py               # engine + session factory
    crud.py                  # data access helpers
    migrations/              # Alembic

  /coinbase
    client.py                # REST client init + low-level calls
    market.py                # price/market digest (candles, EMA/RSI)
    validators.py            # increments/min-size/min-distance checks
    exec.py                  # place_orders(), sync_open_and_fills()

  /llm
    client.py                # Responses API wrapper (tools on/off)
    prompts.py               # system + user templates (M1/M2/M3)
    schemas.py               # JSON schema for Model 3
    summariser.py            # 500-word compactor (gpt-5-mini)
    usage.py                 # usage metering (request/response sizes)

  /scheduler
    jobs.py                  # daily(), two_hourly(), five_minute_poller()
    orchestration.py         # shared flow, locking, drift logic

  /dashboard
    routes.py                # FastAPI views
    templates/               # Jinja2/HTMX templates

requirements.txt
.env.example
Dockerfile  (for local runs if you prefer)


1.2 Dependencies

fastapi, uvicorn[standard], pydantic, httpx

sqlalchemy, alembic, psycopg[binary]

apscheduler

python-dateutil, numpy, pandas

tenacity

openai (latest; Responses API + tools + structured outputs) 
platform.openai.com
+1

coinbase-advanced-py (official SDK entry point page links to docs) 
coinbase.github.io

1.3 Local services

Run PostgreSQL locally (Docker or local install).

Prepare .env with: OPENAI_API_KEY, COINBASE_API_KEY, COINBASE_API_SECRET, DATABASE_URL, APP_TIMEZONE=UTC, PRODUCT_ID=ETH-USDC, MIN_DISTANCE_PCT=0.0015, PRICE_DRIFT_PCT=0.005.

2) Data model & migrations

2.1 SQLAlchemy models

RunLog(id, kind={'daily','2h','5m','manual'}, started_at, finished_at, status, usage_json, error_text)

PromptHistoryDaily(id, ts, prompt_text, response_text, compact_summary_500w, sources_json)

PromptHistory2H(id, ts, prompt_text, response_text, compact_summary_500w, sources_json)

ExecutedOrder(order_id, ts_submitted, ts_filled, side, limit_price, base_size, status, filled_size, client_order_id, end_time, product_id)

OpenOrder(order_id, side, limit_price, base_size, status, client_order_id, end_time, product_id)

PortfolioSnapshot(id, ts, balances_json) (ETH/USDC available + total)

PriceSnapshot(id, ts, product_id, best_bid, best_ask, mid)

DailyPlan(id, ts, raw_text, machine_json)

TwoHourPlan(id, ts, t0_mid, raw_text, machine_json)

2.2 Alembic

Create initial migration; run locally.

3) Coinbase layer

3.1 REST client

Build a thin wrapper that authenticates via the SDK and retries transient errors (Tenacity).

Expose helpers:

get_product(product_id) → increments/min sizes. (Used for rounding and minimum checks.) 
Coinbase Developer Docs

get_best_bid_ask(product_id) → mid = (bid+ask)/2. (Used for T0/T1 snapshots and min‑distance.) 
Coinbase Developer Docs

get_candles(product_id, start, end, granularity) → build market digests. 
Coinbase Developer Docs

list_orders(...), list_fills(...) → sync open orders & detect fills. 
Coinbase Developer Docs

create_order_limit_gtd(side, limit_price, base_size, end_time_iso, post_only=True) → calls Create Order using the limit GTD configuration (limit_limit_gtd) with post_only. 
Coinbase Developer Docs

3.2 Validation & normalisation

validators.round_price_by_increment(price, quote_increment)

validators.round_size_by_increment(size, base_increment)

validators.enforce_minimums(size, price, base_min_size, quote_min_size)

validators.enforce_min_distance(mid, price, min_distance_pct)

validators.ensure_unique_sides(orders) → at most one BUY and one SELL.

3.3 Market digest

Using candles and best bid/ask, compute: last price, 24h range, last‑2h range, basic realised vol, EMA(15/60), RSI(14), typical spread; serialise to a compact JSON blob.

4) OpenAI layer

4.1 Responses API wrapper

llm/client.py:

call_model_1(context) → model: gpt‑5‑reasoning‑high, tools=[{"type":"web_search"}]. Save usage_json for later measurement. 
platform.openai.com
+1

call_model_2(context) → model: gpt‑5‑reasoning‑medium, with web_search. 
platform.openai.com

shape_orders(model2_text) → model: gpt‑5‑mini‑reasoning‑minimal, with Structured Outputs (JSON schema below) so the output is guaranteed parseable. 
platform.openai.com
+1

4.2 JSON schema (Model 3)

{
  "type":"object",
  "properties":{
    "orders":{
      "type":"array","minItems":0,"maxItems":2,
      "items":{
        "type":"object",
        "properties":{
          "side":{"type":"string","enum":["BUY","SELL"]},
          "limit_price":{"type":"string","pattern":"^[0-9]+(\\.[0-9]+)?$"},
          "base_size":{"type":"string","pattern":"^[0-9]+(\\.[0-9]+)?$"},
          "time_in_force":{"type":"string","enum":["GTD"]},
          "post_only":{"type":"boolean","const":true},
          "ttl_seconds":{"type":"integer","enum":[7200]}
        },
        "required":["side","limit_price","base_size","time_in_force","post_only","ttl_seconds"],
        "additionalProperties":false
      }
    }
  },
  "required":["orders"],
  "additionalProperties":false
}


(Executor converts ttl_seconds to end_time ISO8601 and calls Coinbase Create Order with limit_limit_gtd + post_only.) 
Coinbase Developer Docs

4.3 Prompt templates

System (shared)

Only ETH‑USDC spot.

Orders must be limit GTD 2h, post_only true; at most one BUY and one SELL per cycle.

Keep proposed limit prices outside the min‑distance buffer (default 0.15% from current mid).

No market or stop orders.

Model 1 (Daily, 00:00)

Inputs: latest portfolio snapshot; compact market digest (24h); last seven Model‑1 compact summaries; all executed orders in last 7 days (brief single‑line entries: ts, side, px, size, outcome); selected web_search findings.

Output: a 24‑hour plan (bias, likely range, invalidation, themes) and a small machine‑readable tail section (JSON‑ish) with constraints/leanings for Model 2.

Tooling: web_search enabled. 
platform.openai.com

Model 2 (Every 2h)

Inputs: today’s daily plan, last seven Model‑2 compact summaries, executed orders (24h), latest portfolio, short 2–4h digest, selected web_search snippets.

Output: prose describing 0–2 limit orders (at most one BUY and one SELL), each with side, indicative price/size rationale.

Tooling: web_search enabled. 
platform.openai.com

Model 3 (Immediately after Model 2)

Input: the Model 2 prose.

Output: JSON strictly matching the schema above (Structured Outputs). 
platform.openai.com

5) History compaction to 500 words (how we’ll do it)

Goal: Preserve the “thinking and evidence” from each daily/2‑hour run without blowing up context.
Approach (llm/summariser.py):

Build a summarisation prompt for gpt‑5‑mini:

Input: original prompt, model output, any cited sources list, and outcomes since last run (if known).

Instruction: “Produce a 500‑word concise summary covering: market view, key signals used, proposed actions, explicit price ranges/levels, invalidations, and short rationale. Include a three‑line ‘Machine hints’ block capturing levers for the next run (e.g., mean‑reversion vs breakout, prefer buy‑the‑dip vs sell‑the‑rip). Keep it factual; do not invent data.”

Call the API; store the result as compact_summary_500w and a short sources_json list (URLs/titles from web_search, if any).

For Model 1 keep 7 most recent; same for Model 2. Old ones roll off.

This gives richer memory than 150 tokens while remaining predictable, and it is cheap to generate with the small model.

6) Orchestration & scheduling (local only)

6.1 APScheduler (started in main.py)

Jobs:

daily() — cron at 0 0 * * * (UTC).

two_hourly() — cron at 0 */2 * * * (UTC).

five_minute_poller() — interval every 5 minutes.

6.2 daily() flow

Fetch portfolio snapshot; executed orders (past 7 days); build 24h market digest (candles). 
Coinbase Developer Docs

Load last 7 Model‑1 compact summaries.

Call Model 1 with web_search; store raw text + machine hints; build and save a 500‑word compact summary. 
platform.openai.com

Save DailyPlan; record API usage metrics.

6.3 two_hourly() flow

Take T0 mid‑price snapshot via Get Best Bid/Ask; persist snapshot. 
Coinbase Developer Docs

Load today’s DailyPlan, last 7 Model‑2 compact summaries, executed orders (24h), latest portfolio, 2–4h digest.

Call Model 2 (web_search enabled); store raw text. 
platform.openai.com

Call Model 3 to produce strict JSON. 
platform.openai.com

Validate & normalise:

Round to product increments; enforce minimum sizes via Get Product metadata. 
Coinbase Developer Docs

Enforce ≤2 orders and unique sides; enforce min‑distance from T0 mid.

Drift check: pull mid again (T1). If relative move vs T0 ≥ 0.5%, rerun steps 2–5 immediately once (avoid loops). 
Coinbase Developer Docs

Convert ttl_seconds=7200 → end_time=now+2h (UTC ISO). Place orders with Create Order using limit GTD configuration and post_only=true. Save order IDs. 
Coinbase Developer Docs

Save TwoHourPlan; compact summary (500 words); update dashboard.

6.4 five_minute_poller() flow

Sync open orders and fills (List Orders / List Fills). If any fill detected (partial or full), immediately call two_hourly() (no wait). 
Coinbase Developer Docs

Remove expired/filled from OpenOrder; insert into ExecutedOrder; store a portfolio snapshot.

6.5 Concurrency & safety

Use an async lock (or DB advisory lock) so that only one two_hourly() run is active at a time.

Always pass a unique client_order_id when creating orders to avoid duplicates.

7) Dashboard (local)

7.1 Endpoints

/dashboard — cards for:

Today’s Daily Plan (Model 1 summary + machine hints).

Current 2‑hour Plan (Model 2 summary + the JSON from Model 3).

Open orders (id, side, price, size, end_time, status).

Recent fills (time, side, price, size).

Portfolio (ETH, USDC).

Run log with statuses and API usage counts.

/healthz — basic OK + DB check.

/force/daily, /force/2h — manual runs for local testing.

7.2 Implementation

FastAPI + Jinja2/HTMX; simple table views.

No authentication for local tests (bind to localhost).

8) Execution pipeline (JSON → live orders)

8.1 Data class

@dataclass
class PlannedOrder:
    side: Literal["BUY","SELL"]
    limit_price: Decimal
    base_size: Decimal
    end_time: datetime  # now + 2h, UTC
    post_only: bool = True


8.2 Steps

Fetch product metadata → run rounding & minimum checks. 
Coinbase Developer Docs

Enforce unique sides, ≤2 orders, and min‑distance vs current mid.

Call Coinbase Create Order with limit_limit_gtd + post_only. Store order_id and client_order_id. 
Coinbase Developer Docs

9) Local test plan (no cloud deployment yet)

9.1 Configuration & dry runs

Set up .env and DB.

Run uvicorn app.main:app --reload.

Exercise /force/daily and /force/2h with LLM stubs (switch in llm/client.py to return canned outputs) to verify the scheduler → validation → executor path without touching real APIs.

9.2 Coinbase integration (small live test or sandbox)

Fetch Get Product for ETH‑USDC and verify increments/min sizes are honoured by validators. 
Coinbase Developer Docs

Call Get Best Bid/Ask and store mid; confirm drift check logic triggers on simulated change. 
Coinbase Developer Docs

Place two tiny GTD post_only orders (one buy and one sell) and ensure they appear as open; confirm they auto‑expire in ~2h; verify they are deleted from OpenOrder and moved into ExecutedOrder on expiry/fill. 
Coinbase Developer Docs

9.3 LLM end‑to‑end (real calls)

Run a real daily cycle (Model 1) and two‑hour cycle (Model 2 → Model 3).

Confirm:

Model 1/2 use web_search (view the sources captured in sources_json). 
platform.openai.com

Model 3 emits valid JSON per schema; executor places orders.

The 500‑word compact summaries are created and stored.

API usage is captured in RunLog.usage_json (request/response sizes, counts).

9.4 Failure & edge cases

Simulate API 429/5xx → verify retries and back‑off.

Simulate invalid Model 2 outputs → Model 3 still yields valid JSON or the validator rejects with a clear error and the job logs it.

Ensure overlapping two_hourly() runs cannot happen (lock works).

Simulate price drift ≥0.5% → re‑run once, not endlessly.

Definition of local “done”

All three schedules run on a developer machine.

Dashboard shows the latest plans, orders, fills, portfolio, and run statuses.

At least one full cycle has placed GTD post_only orders and cleaned them up correctly from DB on fill/expiry.

10) Deliverables for the coding agent

Codebase matching the structure above.

Alembic migration for all tables.

Coinbase client with helpers for product meta, best bid/ask, candles, orders, fills. 
Coinbase Developer Docs
+3
Coinbase Developer Docs
+3
Coinbase Developer Docs
+3

Validators and unit tests.

LLM wrappers: Model 1 & 2 with web_search, Model 3 with Structured Outputs; plus the 500‑word summariser (gpt‑5‑mini). 
platform.openai.com
+2
platform.openai.com
+2

Scheduler with three jobs and manual endpoints.

Dashboard with the views listed.

Local test scripts and a short readme for running the full loop locally.

Usage metering that records request/response sizes and counts (so you learn natural usage without any preset limits).

Notes

The official Advanced Trade docs confirm GTD time‑in‑force and post‑only support via the Create Order configuration. 
Coinbase Developer Docs
+1

Use Get Best Bid/Ask for fast mid‑price snapshots used in drift checks and the min‑distance rule. 
Coinbase Developer Docs

Use Get Product to pull base_increment, quote_increment, and minimum sizes for ETH‑USDC so your rounding and validation are exact. 
Coinbase Developer Docs

Responses API provides both the web_search tool (for Model 1 & 2) and Structured Outputs (for Model 3), which aligns perfectly with your architecture.