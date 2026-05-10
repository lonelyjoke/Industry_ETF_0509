import numpy as np
import pandas as pd

from src.backtest import run_backtest
from src.universe import load_universe
from src.utils import load_config


def _price_frame(offset: float = 0.0):
    dates = pd.bdate_range("2023-01-01", periods=180)
    close = np.linspace(1 + offset, 2 + offset, len(dates))
    return pd.DataFrame(
        {
            "trade_date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000000,
            "amount": 80000000,
        }
    )


def test_backtest_runs_with_synthetic_data():
    cfg = load_config("config.yaml")
    cfg["backtest"]["top_k"] = 1
    cfg["data"]["use_fundamental"] = False
    universe = load_universe(cfg).head(2)
    price_data = {universe.iloc[0]["etf_code"]: _price_frame(0), universe.iloc[1]["etf_code"]: _price_frame(0.2)}
    benchmark = _price_frame(0.1)
    result = run_backtest(price_data, universe, benchmark, cfg)
    assert not result.equity_curve.empty
    assert "equity" in result.equity_curve.columns
    assert not result.weekly_ranking.empty
