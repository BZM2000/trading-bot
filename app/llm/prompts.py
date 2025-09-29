from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MODEL_1_SYSTEM_PROMPT = """You are Model 1, a trading strategy planner focused on ETH-USDC. Deliver concise, structured daily plans with clear objectives, risk notes, and execution guidance."""

MODEL_2_SYSTEM_PROMPT = """You are Model 2, a tactical planner generating up to two actionable limit orders for ETH-USDC. Respect inventory, market context, and constraints from the daily plan. Never suggest a SELL order without available ETH and never suggest a BUY order whose cost exceeds available USDC."""

MODEL_3_SYSTEM_PROMPT = """You are Model 3. Validate and transform Model 2 outputs into machine friendly JSON that the execution engine can consume. Do not invent orders."""

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
        "\nExecuted orders in the last 24 hours:",
        executed or "(no executions)",
        "\nCurrent portfolio snapshot:",
        context.portfolio_snapshot,
        "\nLive market snapshot:",
        context.market_snapshot,
        "\nExecution constraints:",
        context.constraint_notes,
        "\nInstructions: propose up to two ETH-USDC limit orders (at most one BUY and one SELL).",
        "Strict balance rules:",
        "- Omit SELL orders entirely when CURRENT ETH available is zero or negative.",
        "- Omit BUY orders if the required USDC would exceed CURRENT USDC available (use limit_price * base_size to estimate cost).",
        "- Use only the CURRENT balances in the portfolio snapshot; do not assume fills or transfers.",
        "- Ensure BUY limits are at least the minimum distance below the current mid and SELL limits at least the minimum distance above it.",
        "- When a plan level violates the distance or balance rules, adjust it to the nearest allowed price or drop the order entirely.",
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
