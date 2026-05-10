import numpy as np
import pandas as pd

from src.features_daily import add_daily_features, score_cross_section
from src.utils import load_config


def test_daily_features_and_scores():
    cfg = load_config("config.yaml")
    dates = pd.bdate_range("2023-01-01", periods=150)
    base = pd.DataFrame(
        {
            "trade_date": dates,
            "open": np.linspace(1, 2, len(dates)),
            "high": np.linspace(1.01, 2.01, len(dates)),
            "low": np.linspace(0.99, 1.99, len(dates)),
            "close": np.linspace(1, 2, len(dates)),
            "volume": 1000000,
            "amount": 50000000,
        }
    )
    feat = add_daily_features(base, cfg)
    assert "ret_60" in feat.columns
    snap = feat.tail(2).copy()
    snap["etf_code"] = ["A", "B"]
    scored = score_cross_section(snap, cfg)
    assert "technical_score" in scored.columns
