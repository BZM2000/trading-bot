from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import FastAPI

from app.coinbase import (
    CoinbaseClient,
    ExecutionService,
    MarketService,
    OrderType,
    PlannedOrder,
    ProductConstraints,
)
from app.dashboard import pnl
from app.coinbase.validators import round_size
from app.config import Settings, get_settings
from app.db import RunKind, RunStatus, session_scope
from app.db import crud
from app.db.models import OrderSide, OrderStatus, RunLog
from app.llm import LLMClient, LLMResult, Model1Context, Model2Context, Model3Context, prompts
from app.llm.schemas import Model3Response
from app.llm.summariser import summarise_to_500_words
from app.llm.usage import UsageTracker


logger = logging.getLogger("scheduler.orchestrator")

MIN_ORDER_NOTIONAL_USDC = Decimal("10")
MAKER_FEE_BUFFER_RATE = Decimal("0.0035")  # maker-style (post-only) cushion
TAKER_FEE_BUFFER_RATE = Decimal("0.0075")  # taker-style cushion for stops/market
MARKET_FOLLOW_UP_DELAY_SECONDS = 10




def _currencies_for_product(product_id: str) -> set[str]:
    for separator in ("-", "/"):
        if separator in product_id:
            base, quote = product_id.split(separator, 1)
            return {base.upper(), quote.upper()}
    return {product_id.upper()}


def filter_portfolio_balances(product_id: str, balances: dict[str, Any]) -> dict[str, Any]:
    allowed = _currencies_for_product(product_id)
    filtered: dict[str, Any] = {}
    for currency, snapshot in balances.items():
        if not currency:
            continue
        if currency.upper() in allowed:
            filtered[currency] = snapshot
    return filtered

class SchedulerOrchestrator:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._planning_lock = asyncio.Lock()
        self._two_hour_lock = asyncio.Lock()

    @asynccontextmanager
    async def _planning_guard(self, kind: RunKind, triggered_by: str):
        if self._planning_lock.locked():
            logger.info(
                "Delaying %s run until current plan finishes",
                kind.value,
                extra={"triggered_by": triggered_by},
            )
        await self._planning_lock.acquire()
        try:
            yield
        finally:
            self._planning_lock.release()

    async def run_daily(self, *, triggered_by: str = "schedule") -> None:
        async with self._planning_guard(RunKind.DAILY, triggered_by):
            usage = UsageTracker()
            run_id = self._start_run(RunKind.DAILY, triggered_by)
            try:
                history, executed_summary = self._load_daily_context()
                async with CoinbaseClient(settings=self.settings) as cb_client:
                    market_service = MarketService(cb_client)
                    snapshot = await market_service.current_snapshot(self.settings.product_id)
                    market_overview = self._format_market_snapshot(snapshot)
                    self._record_price_snapshot(snapshot)

                async with LLMClient(settings=self.settings, usage_tracker=usage) as llm:
                    context = Model1Context(
                        market_overview=market_overview,
                        recent_daily_history=history,
                        executed_orders_summary=executed_summary,
                    )
                    llm_result = await llm.run_model1(context)
                    summary_text = await summarise_to_500_words(llm, llm_result.text)

                self._persist_daily_plan(context, llm_result, summary_text)
                self._finish_run(run_id, RunStatus.SUCCESS, usage, extra={"triggered_by": triggered_by})
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Daily job failed")
                self._finish_run(run_id, RunStatus.FAILED, usage, error=str(exc), extra={"triggered_by": triggered_by})
                raise

    async def run_two_hourly(self, *, triggered_by: str = "schedule") -> None:
        async with self._planning_guard(RunKind.TWO_HOURLY, triggered_by):
            if not self._two_hour_lock.locked():
                logger.info("Starting two-hour job", extra={"triggered_by": triggered_by})
            async with self._two_hour_lock:
                usage = UsageTracker()
                run_id = self._start_run(RunKind.TWO_HOURLY, triggered_by)
                try:
                    await self._execute_two_hourly(run_id, usage, triggered_by)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.exception("Two-hour job failed")
                    self._finish_run(run_id, RunStatus.FAILED, usage, error=str(exc), extra={"triggered_by": triggered_by})
                    raise

    async def run_pnl_refresh(self) -> None:
        usage = UsageTracker()
        run_id = self._start_run(RunKind.MANUAL, "pnl-refresh")
        try:
            async with CoinbaseClient(settings=self.settings) as client:
                summary = await pnl.calculate_pnl_summary(client, product_id=self.settings.product_id)
            summary_json = pnl.summary_to_json(summary)
            with session_scope(self.settings) as session:
                crud.record_pnl_snapshot(
                    session,
                    product_id=self.settings.product_id,
                    summary_json=summary_json,
                )
            self._finish_run(
                run_id,
                RunStatus.SUCCESS,
                usage,
                extra={"snapshot_ts": datetime.now(timezone.utc).isoformat()},
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("PnL refresh failed")
            self._finish_run(run_id, RunStatus.FAILED, usage, error=str(exc))
            raise

    async def _execute_two_hourly(self, run_id: int, usage: UsageTracker, triggered_by: str) -> None:
        history, executed_summary = self._load_two_hour_context()
        daily_plan_text = self._latest_daily_plan_text()
        if daily_plan_text is None:
            raise RuntimeError("Daily plan not found; model 2 cannot run")

        async with CoinbaseClient(settings=self.settings) as cb_client:
            market_service = MarketService(cb_client)
            product = await cb_client.get_product(self.settings.product_id)
            constraints = ProductConstraints.from_product(product, self.settings.min_distance_pct)
            execution = ExecutionService(cb_client, product_id=self.settings.product_id, constraints=constraints)

            async with LLMClient(settings=self.settings, usage_tracker=usage) as llm:
                additional_validation_notes = ""
                for attempt in (1, 2):
                    market_snapshot = await market_service.current_snapshot(self.settings.product_id)
                    self._record_price_snapshot(market_snapshot)

                    portfolio_balances = await self._capture_portfolio_snapshot(cb_client)
                    market_snapshot_text = self._format_market_snapshot(market_snapshot)
                    constraints_text = self._format_constraints(constraints, market_snapshot.mid)
                    model2_context = Model2Context(
                        daily_plan=daily_plan_text,
                        recent_two_hour_history=history,
                        executed_orders_summary=executed_summary,
                        portfolio_snapshot=self._format_portfolio_snapshot(portfolio_balances),
                        market_snapshot=market_snapshot_text,
                        constraint_notes=constraints_text,
                    )
                    model2_result = await llm.run_model2(model2_context)

                    validation_notes = self._build_validation_notes(constraints, market_snapshot.mid)
                    if additional_validation_notes:
                        validation_notes = f"{validation_notes} {additional_validation_notes}".strip()
                    model3_context = Model3Context(model2_output=model2_result.text, validation_notes=validation_notes)
                    model3_response: Model3Response = await llm.run_model3(model3_context)
                    planned_orders = model3_response.to_planned_orders()
                    planned_orders = self._apply_quote_buffer(
                        planned_orders,
                        portfolio_balances,
                        constraints,
                    )
                    has_market_order = any(order.order_type is OrderType.MARKET for order in planned_orders)

                    if planned_orders:
                        drift_ok = await self._check_price_drift(market_service, market_snapshot.mid)
                        if not drift_ok and attempt == 1:
                            logger.info("Price drift exceeded threshold; re-running Model 2/3")
                            history.insert(0, f"Previous run drifted at {datetime.now(timezone.utc).isoformat()}")
                            continue

                    await self._persist_two_hour_plan(
                        model2_context,
                        model2_result,
                        model3_response,
                        planned_orders,
                        llm,
                        market_snapshot.mid,
                    )

                    placed_order_responses = []
                    if planned_orders and self.settings.execution_enabled:
                        try:
                            placed_order_responses = await execution.place_orders(planned_orders, mid_price=market_snapshot.mid)
                        except ValueError as exc:
                            logger.warning("Order validation failed: %s", exc)
                            if attempt == 1:
                                timestamp = datetime.now(timezone.utc).isoformat()
                                history.insert(0, f"{timestamp}Z :: Last attempt rejected: {exc}")
                                additional_validation_notes = f"Previous attempt rejected: {exc}."
                                continue
                            raise
                    with session_scope(self.settings) as session:
                        sync_result = await execution.sync_open_and_fills(session)
                    self._finish_run(
                        run_id,
                        RunStatus.SUCCESS,
                        usage,
                        extra={
                            "triggered_by": triggered_by,
                            "planned_orders": [self._planned_order_to_dict(order) for order in planned_orders],
                            "placed_orders": placed_order_responses,
                        },
                    )
                    if has_market_order:
                        self._schedule_market_followup(triggered_by="market_followup")
                    return

            raise RuntimeError("Model 2/3 failed to produce a plan after drift checks")

    async def run_fill_poller(self) -> None:
        new_fills: list[str] = []
        open_orders: list[crud.OpenOrderRecord] = []
        async with self._planning_guard(RunKind.FIVE_MINUTE, "schedule"):
            usage = UsageTracker()
            run_id = self._start_run(RunKind.FIVE_MINUTE, "schedule")
            try:
                async with CoinbaseClient(settings=self.settings) as cb_client:
                    execution = ExecutionService(
                        cb_client,
                        product_id=self.settings.product_id,
                        constraints=None,
                    )
                    with session_scope(self.settings) as session:
                        sync_result = await execution.sync_open_and_fills(session)
                    open_orders = sync_result.open_orders
                    new_fills = [
                        record.order_id
                        for record in sync_result.executed_orders
                        if record.order_id in sync_result.changed_order_ids
                        and record.status == OrderStatus.FILLED
                    ]
                self._finish_run(
                    run_id,
                    RunStatus.SUCCESS,
                    usage,
                    extra={"new_fills": new_fills},
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Fill poller failed")
                self._finish_run(run_id, RunStatus.FAILED, usage, error=str(exc))
                raise

        if not open_orders and not self._two_hour_lock.locked():
            await self.run_two_hourly(triggered_by="no_open_orders")

    def _start_run(self, kind: RunKind, triggered_by: str) -> int:
        with session_scope(self.settings) as session:
            payload = {"triggered_by": triggered_by} if triggered_by != "schedule" else None
            run_log = crud.log_run_start(session, kind, usage_json=payload)
            return run_log.id

    def _finish_run(
        self,
        run_id: Optional[int],
        status: RunStatus,
        usage: UsageTracker,
        *,
        error: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        if not run_id:
            return
        with session_scope(self.settings) as session:
            run: RunLog | None = session.get(RunLog, run_id)
            if not run:
                return
            usage_payload = {
                "records": usage.to_json(),
                "totals": usage.totals(),
            }
            if extra:
                usage_payload.update(extra)
            crud.log_run_finish(
                session,
                run,
                status=status,
                error_text=error,
                usage_json=usage_payload,
            )

    def _load_daily_context(self) -> tuple[list[str], list[str]]:
        with session_scope(self.settings) as session:
            history_models = crud.get_recent_prompt_history(session, RunKind.DAILY, limit=7)
            executed_orders = crud.executed_orders_since(
                session,
                datetime.now(timezone.utc) - timedelta(days=7),
                product_id=self.settings.product_id,
            )
            executed_orders = [
                order
                for order in executed_orders
                if order.status not in {OrderStatus.OPEN, OrderStatus.NEW}
            ]
            executed_orders = executed_orders[:20]
        history = [self._format_prompt_history_entry(item.ts, item.compact_summary_500w or item.response_text) for item in history_models]
        executed_summary = [self._format_executed_order(order) for order in executed_orders]
        return history, executed_summary

    def _load_two_hour_context(self) -> tuple[list[str], list[str]]:
        with session_scope(self.settings) as session:
            history_models = crud.get_recent_prompt_history(session, RunKind.TWO_HOURLY, limit=12)
            executed_orders = crud.recent_executed_orders(
                session,
                hours=24,
                product_id=self.settings.product_id,
            )
            executed_orders = [
                order
                for order in executed_orders
                if order.status in {OrderStatus.FILLED, OrderStatus.EXPIRED}
            ]
            executed_orders = executed_orders[:20]
        history = [self._format_prompt_history_entry(item.ts, item.compact_summary_500w or item.response_text) for item in history_models]
        executed_summary = [self._format_executed_order(order) for order in executed_orders]
        return history, executed_summary

    def _persist_daily_plan(self, context: Model1Context, llm_result: LLMResult, summary_text: str) -> None:
        now = datetime.now(timezone.utc)
        sources = self._extract_sources(llm_result.response)
        with session_scope(self.settings) as session:
            crud.save_daily_plan(session, crud.PlanRecord(ts=now, raw_text=llm_result.text, machine_json=None))
            crud.save_prompt_history(
                session,
                RunKind.DAILY,
                crud.PromptRecord(
                    ts=now,
                    prompt_text=prompts.build_model1_user_prompt(context),
                    response_text=llm_result.text,
                    compact_summary_500w=summary_text,
                    sources_json=sources,
                ),
            )

    async def _persist_two_hour_plan(
        self,
        context: Model2Context,
        model2_result: LLMResult,
        model3_response: Model3Response,
        planned_orders: list[PlannedOrder],
        llm: LLMClient,
        mid_price: Any,
    ) -> None:
        now = datetime.now(timezone.utc)
        machine_json = model3_response.model_dump(mode="json")
        summary_text = await summarise_to_500_words(llm, model2_result.text)
        mid_value = mid_price if isinstance(mid_price, Decimal) else Decimal(str(mid_price or "0"))
        with session_scope(self.settings) as session:
            crud.save_two_hour_plan(
                session,
                crud.TwoHourPlanRecord(
                    ts=now,
                    t0_mid=mid_value,
                    raw_text=model2_result.text,
                    machine_json=machine_json,
                ),
            )
            crud.save_prompt_history(
                session,
                RunKind.TWO_HOURLY,
                crud.PromptRecord(
                    ts=now,
                    prompt_text=prompts.build_model2_user_prompt(context),
                    response_text=model2_result.text,
                    compact_summary_500w=summary_text,
                    sources_json=self._extract_sources(model2_result.response),
                ),
            )

    async def _capture_portfolio_snapshot(self, client: CoinbaseClient) -> dict[str, Any]:
        response = await client.list_accounts(limit=250)
        balances: dict[str, Any] = {}
        for account in response.get("accounts", []):
            currency = account.get("currency")
            balances[currency] = {
                "available": account.get("available_balance", {}).get("value"),
                "hold": account.get("hold", {}).get("value"),
                "balance": account.get("balance", {}).get("value"),
            }
        filtered_balances = filter_portfolio_balances(self.settings.product_id, balances)
        with session_scope(self.settings) as session:
            crud.record_portfolio_snapshot(
                session,
                crud.PortfolioSnapshotRecord(ts=datetime.now(timezone.utc), balances_json=filtered_balances),
            )
        return filtered_balances

    async def _check_price_drift(self, market_service: MarketService, start_mid: Any) -> bool:
        current = await market_service.current_snapshot(self.settings.product_id)
        self._record_price_snapshot(current)
        drift = abs(current.mid - start_mid) / start_mid
        return drift < self.settings.price_drift_pct

    def _schedule_market_followup(self, *, triggered_by: str) -> None:
        async def _delayed_two_hourly() -> None:
            await asyncio.sleep(MARKET_FOLLOW_UP_DELAY_SECONDS)
            try:
                await self.run_two_hourly(triggered_by=triggered_by)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Follow-up two-hour run after market order failed")

        logger.info(
            "Scheduling follow-up two-hour run after market order",
            extra={"triggered_by": triggered_by, "delay_seconds": MARKET_FOLLOW_UP_DELAY_SECONDS},
        )
        asyncio.create_task(_delayed_two_hourly())

    def _record_price_snapshot(self, snapshot) -> None:
        with session_scope(self.settings) as session:
            crud.record_price_snapshot(
                session,
                crud.PriceSnapshotRecord(
                    ts=datetime.now(timezone.utc),
                    product_id=self.settings.product_id,
                    best_bid=snapshot.best_bid,
                    best_ask=snapshot.best_ask,
                    mid=snapshot.mid,
                ),
            )

    def _latest_daily_plan_text(self) -> Optional[str]:
        with session_scope(self.settings) as session:
            plan = crud.latest_daily_plan(session)
            return plan.raw_text if plan else None

    def _format_prompt_history_entry(self, ts: datetime, text: str) -> str:
        snippet = text.strip().splitlines()
        truncated = " ".join(snippet)[:500]
        return f"{ts.isoformat()}Z :: {truncated}"

    def _format_executed_order(self, order) -> str:
        ts = (order.ts_filled or order.ts_submitted).isoformat()
        price_part = f"{order.base_size} @ {order.limit_price}"
        if getattr(order, "stop_price", None):
            price_part += f" (stop {order.stop_price})"
        return f"{ts} {order.side.value} {price_part} → {order.status.value}"

    def _apply_quote_buffer(
        self,
        planned_orders: list[PlannedOrder],
        balances: dict[str, Any],
        constraints: ProductConstraints,
    ) -> list[PlannedOrder]:
        if not planned_orders:
            return planned_orders

        available_quote = self._available_quote_balance(balances)
        if available_quote is None:
            return planned_orders

        spend_cap = available_quote
        if spend_cap <= Decimal("0"):
            if any(order.side is OrderSide.BUY for order in planned_orders):
                logger.info(
                    "Dropping BUY orders: insufficient USDC after applying fee cushions",
                    extra={
                        "available_usdc": str(available_quote),
                    },
                )
            return [order for order in planned_orders if order.side is not OrderSide.BUY]

        remaining_cap = spend_cap
        adjusted_orders: list[PlannedOrder] = []
        for order in planned_orders:
            if order.side is not OrderSide.BUY:
                adjusted_orders.append(order)
                continue

            cost = order.limit_price * order.base_size
            fee_rate = self._fee_buffer_rate(order)
            total_cost = cost * (Decimal("1") + fee_rate)
            if total_cost <= remaining_cap:
                adjusted_orders.append(order)
                remaining_cap = max(remaining_cap - total_cost, Decimal("0"))
                continue

            denominator = order.limit_price * (Decimal("1") + fee_rate)
            max_base = remaining_cap / denominator if denominator else Decimal("0")
            max_base = round_size(max_base, constraints)
            if max_base <= Decimal("0") or max_base < constraints.min_size:
                logger.info(
                    "Dropping BUY order: fee cushion reduces quote below minimum size",
                    extra={
                        "available_usdc": str(available_quote),
                        "limit_price": str(order.limit_price),
                        "fee_buffer_rate": str(fee_rate),
                    },
                )
                continue

            adjusted_orders.append(
                PlannedOrder(
                    side=order.side,
                    limit_price=order.limit_price,
                    base_size=max_base,
                    end_time=order.end_time,
                    post_only=order.post_only,
                    stop_price=order.stop_price,
                    order_type=order.order_type,
                )
            )
            adjusted_cost = order.limit_price * max_base
            adjusted_total = adjusted_cost * (Decimal("1") + fee_rate)
            remaining_cap = max(remaining_cap - adjusted_total, Decimal("0"))

        return adjusted_orders

    def _fee_buffer_rate(self, order: PlannedOrder) -> Decimal:
        if order.order_type is OrderType.LIMIT and order.post_only:
            return MAKER_FEE_BUFFER_RATE
        return TAKER_FEE_BUFFER_RATE

    def _available_quote_balance(self, balances: dict[str, Any]) -> Optional[Decimal]:
        quote_currency = self._quote_currency()
        snapshot = balances.get(quote_currency)
        if not snapshot:
            return None
        value = snapshot.get("available")
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            logger.warning(
                "Failed to parse available balance",
                extra={"quote_currency": quote_currency, "raw_value": value},
            )
            return None

    def _quote_currency(self) -> str:
        product_id = self.settings.product_id or ""
        for separator in ("-", "/"):
            if separator in product_id:
                _, quote = product_id.split(separator, 1)
                return quote.upper()
        return product_id.upper()

    def _format_portfolio_snapshot(self, balances: dict[str, Any]) -> str:
        lines = []
        for currency, entry in balances.items():
            lines.append(
                f"{currency}: available={entry.get('available')} hold={entry.get('hold')} total={entry.get('balance')}"
            )
        return "\n".join(lines) if lines else "(no balances for target product)"

    def _format_constraints(self, constraints: ProductConstraints, mid_price) -> str:
        threshold = mid_price * constraints.min_distance_pct if mid_price else None
        distance_pct = constraints.min_distance_pct * Decimal(100)
        parts = [
            f"Min distance: {distance_pct:.4f}%",
            f"Price increment: {constraints.price_increment}",
            f"Size increment: {constraints.size_increment}",
            f"Minimum size: {constraints.min_size}",
        ]
        if threshold is not None:
            max_buy = mid_price - threshold
            min_sell = mid_price + threshold
            parts.append(f"Distance at current mid: {threshold}")
            parts.append(f"Max BUY limit: ≤ {max_buy}")
            parts.append(f"Min SELL limit: ≥ {min_sell}")
        parts.append(f"Min order notional: ≥ {MIN_ORDER_NOTIONAL_USDC} USDC")
        parts.append("Stop-limits: BUY stops must sit above the mid by the same distance, SELL stops below it.")
        return ", ".join(parts)

    def _format_market_snapshot(self, snapshot) -> str:
        parts = [
            f"Mid price: {snapshot.mid}",
            f"Best bid: {snapshot.best_bid}",
            f"Best ask: {snapshot.best_ask}",
        ]
        if snapshot.ema_fast:
            parts.append(f"EMA fast: {snapshot.ema_fast}")
        if snapshot.ema_slow:
            parts.append(f"EMA slow: {snapshot.ema_slow}")
        if snapshot.rsi is not None:
            parts.append(f"RSI: {snapshot.rsi:.2f}")
        return " | ".join(parts)

    def _planned_order_to_dict(self, order: PlannedOrder) -> dict[str, Any]:
        data: dict[str, Any] = {
            "side": order.side.value,
            "limit_price": str(order.limit_price),
            "base_size": str(order.base_size),
            "end_time": order.end_time.isoformat(),
            "order_type": order.order_type.value,
        }
        if order.stop_price is not None:
            data["stop_price"] = str(order.stop_price)
        return data

    def _extract_sources(self, response: dict[str, Any]) -> Optional[list[Any]]:
        if not response:
            return None
        output = response.get("output") or response.get("outputs")
        if not output:
            return None
        if isinstance(output, list):
            return output
        return [output]

    def _build_validation_notes(self, constraints: ProductConstraints, mid_price) -> str:
        return (
            f"Constraints: min distance {constraints.min_distance_pct}, price increment"
            f" {constraints.price_increment}, size increment {constraints.size_increment}."
            f" Current mid: {mid_price}"
        )

    def _latest_mid_price(self, session) -> Any:
        snapshot = crud.latest_price_snapshot(session, self.settings.product_id)
        return snapshot.mid if snapshot else None


def get_orchestrator(app: FastAPI) -> SchedulerOrchestrator:
    orchestrator = getattr(app.state, "orchestrator", None)
    if orchestrator is None:
        orchestrator = SchedulerOrchestrator()
        app.state.orchestrator = orchestrator
    return orchestrator
