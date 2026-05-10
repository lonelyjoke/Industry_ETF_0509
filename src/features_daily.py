from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import safe_zscore


def add_daily_features(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy().sort_values("trade_date")
    ma_short = cfg["strategy"].get("ma_short", 20)
    ma_medium = cfg["strategy"].get("ma_medium", 60)
    ma_long = cfg["strategy"].get("ma_long", 120)

    out["ma20"] = out["close"].rolling(ma_short).mean()
    out["ma60"] = out["close"].rolling(ma_medium).mean()
    out["ma120"] = out["close"].rolling(ma_long).mean()
    out["ma250"] = out["close"].rolling(250).mean()
    out["ret_20"] = out["close"].pct_change(20)
    out["ret_60"] = out["close"].pct_change(60)
    out["ret_120"] = out["close"].pct_change(120)
    out["daily_ret"] = out["close"].pct_change()
    out["vol_20"] = out["daily_ret"].rolling(20).std() * np.sqrt(252)
    rolling_high = out["close"].rolling(60).max()
    out["max_drawdown_60"] = out["close"] / rolling_high - 1
    out["drawdown_risk_60"] = -out["max_drawdown_60"]
    out["premium_20"] = out["close"] / out["ma20"] - 1
    out["avg_amount_20"] = out["amount"].rolling(20).mean() if "amount" in out.columns else np.nan
    out["avg_amount_120"] = out["amount"].rolling(120).mean() if "amount" in out.columns else np.nan
    out["amount_crowding"] = out["avg_amount_20"] / out["avg_amount_120"] - 1
    out["avg_volume_20"] = out["volume"].rolling(20).mean() if "volume" in out.columns else np.nan
    out["trend_pass"] = (out["close"] > out["ma60"]) & (out["ma20"] > out["ma60"])
    out["trend_structure"] = (
        (out["close"] > out["ma60"]).astype(float)
        + (out["ma20"] > out["ma60"]).astype(float)
        + (out["ma60"] > out["ma120"]).astype(float)
    )
    return out


def score_cross_section(snapshot: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    out = snapshot.copy()
    factors = cfg["strategy"].get("technical_factors") or {
        "ret_20": 0.20,
        "ret_60": 0.35,
        "ret_120": 0.25,
        "vol_20": -0.10,
        "premium_20": -0.10,
    }
    score = pd.Series(0.0, index=out.index)
    for col, weight in factors.items():
        if col not in out.columns:
            continue
        score += weight * safe_zscore(out[col].astype(float))
    out["technical_score"] = score
    return out


def weekly_signal_dates(trading_dates: pd.Series) -> list[pd.Timestamp]:
    dates = pd.to_datetime(pd.Series(trading_dates).drop_duplicates()).sort_values()
    if dates.empty:
        return []
    weekly = pd.DataFrame({"trade_date": dates})
    weekly["week"] = weekly["trade_date"].dt.to_period("W-FRI")
    return weekly.groupby("week")["trade_date"].max().tolist()


def biweekly_signal_dates(trading_dates: pd.Series) -> list[pd.Timestamp]:
    weekly = weekly_signal_dates(trading_dates)
    return weekly[::2]
