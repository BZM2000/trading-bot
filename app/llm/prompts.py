from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MODEL_1_SYSTEM_PROMPT = """You are Model 1, a trading strategy planner focused on ETH-USDC. Deliver concise, structured daily plans with clear objectives, risk notes, and execution guidance. Always account for a 0.5% round-trip trading fee, highlighting only edges that clear this hurdle."""

MODEL_2_SYSTEM_PROMPT = """You are Model 2, a tactical planner generating exactly one actionable ETH-USDC order per run. You may choose between a classic limit order or a stop-limit order. Respect inventory, market context, and constraints from the daily plan. Orders are Good-Til-Date for 2 hours, so focus on opportunities that should trigger within that window. Never suggest a SELL order without available ETH and never suggest a BUY order whose cost exceeds available USDC. Trading fees are 0.5%% round-trip, so gross moves under ~1%% net to ≈0%%—demand sufficient edge. Minimum order notional is 10 USDC."""

MODEL_3_SYSTEM_PROMPT = """You are Model 3. Validate and transform Model 2 outputs into machine friendly JSON that the execution engine can consume. Support both limit and stop-limit orders, returning at most one order marked for a 2-hour GTD window. Do not invent orders."""

SUMMARISER_SYSTEM_PROMPT = """Summarize the provided trading plan into at most 500 words while preserving key decisions, rationales, and risk notes."""


@dataclass(slots=True)
class Model1Context:
    market_overview: str
    recent_daily_history: Iterable[str]
    executed_orders_summary: Iterable[str]


@dataclass(slots=True)
class Model2Context:
    daily_plan: str
    recent_two_hour_history: Iterable[str]
    executed_orders_summary: Iterable[str]
    portfolio_snapshot: str
    market_snapshot: str
    constraint_notes: str


@dataclass(slots=True)
class Model3Context:
    model2_output: str
    validation_notes: str


def build_model1_user_prompt(context: Model1Context) -> str:
    history = "\n\n".join(context.recent_daily_history)
    executed = "\n".join(context.executed_orders_summary)
    prompt = [
        "Daily market overview:",
        context.market_overview,
        "\nRecent Model 1 outcomes (most recent first):",
        history or "(no history)",
        "\nExecuted orders in the last 7 days:",
        executed or "(no executions)",
        "\nInstructions: produce today's 24-hour ETH-USDC plan.",
        "Explicitly factor in the 0.5% round-trip trading fee when setting targets, sizing, and risk tolerances.",
        "Toolkit: the executor can stage GTD limit or stop-limit orders. Use stop-limits for moves that must cross the mid-price before entering.",
        "Take-profit / stop-loss legs are staged after fills; do not assume multi-leg orders in one step.",
    ]
    return "\n".join(prompt)


def build_model2_user_prompt(context: Model2Context) -> str:
    history = "\n\n".join(context.recent_two_hour_history)
    executed = "\n".join(context.executed_orders_summary)
    prompt = [
        "Daily plan summary:",
        context.daily_plan,
        "\nRecent Model 2 outcomes (most recent first):",
        history or "(no history)",
        "\nExecuted or expired orders in the last 24 hours:",
        executed or "(no executions)",
        "\nCurrent portfolio snapshot:",
        context.portfolio_snapshot,
        "\nLive market snapshot:",
        context.market_snapshot,
        "\nExecution constraints:",
        context.constraint_notes,
        "\nInstructions: propose exactly one ETH-USDC limit or stop-limit order (BUY or SELL). Pick the single highest-quality idea for the next 2 hours.",
        "Strict balance rules:",
        "- Omit SELL orders entirely when CURRENT ETH available is zero or negative.",
        "- Omit BUY orders if the required USDC would exceed CURRENT USDC available (use limit_price * base_size to estimate cost).",
        "- Use only the CURRENT balances in the portfolio snapshot; do not assume fills or transfers.",
        "- For LIMIT orders: BUY limits must sit at least the minimum distance below the mid and SELL limits at least the same distance above it.",
        "- For STOP-LIMIT orders: BUY stops must sit at least the minimum distance above the mid and SELL stops at least the same distance below. Keep BUY limit ≥ stop and SELL limit ≤ stop.",
        "- When a plan level violates the distance or balance rules, adjust it to the nearest allowed price or drop the order entirely.",
        "- Account for 0.5% trading fees: avoid trades whose probable reward after fees is negligible (≈1% gross ≈ break-even).",
        "- Every order must clear the 10 USDC notional minimum; resize or skip if that conflicts with balances or risk limits.",
        "- Take-profit or protective follow-ups cannot be bundled with the entry; you will get a new run to stage exits after a fill.",
        "- State the 2-hour GTD window explicitly and skip ideas unlikely to trigger within it.",
        "If any constraint prevents an order, explain why and omit that side.",
    ]
    return "\n".join(prompt)


def build_model3_user_prompt(context: Model3Context) -> str:
    prompt = [
        "Model 2 proposal:",
        context.model2_output,
        "\nValidation notes:",
        context.validation_notes or "(none)",
        "\nReturn only valid JSON conforming to the schema.",
    ]
    return "\n".join(prompt)
