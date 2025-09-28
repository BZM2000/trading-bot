import math

import pandas as pd

from app.coinbase.market import calculate_ema, calculate_rsi


def test_calculate_ema_matches_pandas() -> None:
    values = [float(i) for i in range(1, 21)]
    period = 5
    ema = calculate_ema(values, period)
    expected = pd.Series(values).ewm(span=period, adjust=False).mean().iloc[-1]
    assert ema is not None
    assert math.isclose(ema, expected, rel_tol=1e-9)


def test_calculate_rsi_bounds() -> None:
    values = [45, 46, 47, 50, 48, 47, 46, 47, 48, 49, 50, 49, 48, 47, 48, 49]
    rsi = calculate_rsi(values, period=5)
    assert rsi is not None
    assert 0 <= rsi <= 100


def test_indicators_return_none_when_insufficient_data() -> None:
    assert calculate_ema([1.0, 2.0], period=5) is None
    assert calculate_rsi([1.0, 2.0], period=5) is None
