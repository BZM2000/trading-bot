from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd

from app.coinbase.client import BestBidAsk, Candle, CoinbaseClient


@dataclass(slots=True)
class MarketSnapshot:
    product_id: str
    best_bid: Decimal
    best_ask: Decimal
    mid: Decimal
    ema_fast: Optional[Decimal]
    ema_slow: Optional[Decimal]
    rsi: Optional[float]
    candles: list[Candle]
    price_time: Optional[str] = None


class MarketService:
    def __init__(self, client: CoinbaseClient) -> None:
        self.client = client

    async def current_snapshot(
        self,
        product_id: str,
        *,
        ema_fast_period: int = 12,
        ema_slow_period: int = 26,
        rsi_period: int = 14,
        candle_granularity: str = "FIVE_MINUTE",
        candle_limit: int = 200,
    ) -> MarketSnapshot:
        best = await self.client.get_best_bid_ask(product_id)
        candles = await self.client.get_product_candles(
            product_id,
            granularity=candle_granularity,
            limit=max(candle_limit, ema_slow_period + 2, rsi_period + 2),
        )

        closes = [c.close for c in candles]
        ema_fast_value = calculate_ema(closes, ema_fast_period)
        ema_slow_value = calculate_ema(closes, ema_slow_period)
        rsi_value = calculate_rsi(closes, rsi_period)

        mid = (Decimal(best.best_bid) + Decimal(best.best_ask)) / 2

        return MarketSnapshot(
            product_id=product_id,
            best_bid=Decimal(best.best_bid),
            best_ask=Decimal(best.best_ask),
            mid=mid,
            ema_fast=Decimal(str(ema_fast_value)) if ema_fast_value is not None else None,
            ema_slow=Decimal(str(ema_slow_value)) if ema_slow_value is not None else None,
            rsi=rsi_value,
            candles=candles,
            price_time=best.time.isoformat() if isinstance(best, BestBidAsk) else None,
        )


def calculate_ema(values: list[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    series = pd.Series(values).astype(float)
    ema_series = series.ewm(span=period, adjust=False).mean()
    return float(ema_series.iloc[-1])


def calculate_rsi(values: list[float], period: int) -> Optional[float]:
    if len(values) < period + 1 or period <= 0:
        return None
    series = pd.Series(values).astype(float)
    delta = series.diff().dropna()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain).rolling(window=period).mean().iloc[-1]
    avg_loss = pd.Series(loss).rolling(window=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)
