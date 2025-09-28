from app.scheduler.orchestration import filter_portfolio_balances


def test_filter_portfolio_balances_hyphen_product():
    balances = {
        "ETH": {"balance": "1"},
        "USDC": {"balance": "100"},
        "BTC": {"balance": "0.5"},
    }

    filtered = filter_portfolio_balances("ETH-USDC", balances)

    assert set(filtered.keys()) == {"ETH", "USDC"}


def test_filter_portfolio_balances_slash_product():
    balances = {
        "eth": {"balance": "1"},
        "USDT": {"balance": "50"},
        "SOL": {"balance": "2"},
    }

    filtered = filter_portfolio_balances("eth/usdt", balances)

    assert set(filtered.keys()) == {"eth", "USDT"}


def test_filter_portfolio_balances_handles_missing_currency():
    balances = {
        None: {"balance": "0"},
        "BTC": {"balance": "0.1"},
    }

    filtered = filter_portfolio_balances("ETH-USDC", balances)

    assert filtered == {}
