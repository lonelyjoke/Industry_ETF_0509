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
    out["ret_20"] = out["close"].pct_change(20)
    out["ret_60"] = out["close"].pct_change(60)
    out["ret_120"] = out["close"].pct_change(120)
    out["daily_ret"] = out["close"].pct_change()
    out["vol_20"] = out["daily_ret"].rolling(20).std() * np.sqrt(252)
    rolling_high = out["close"].rolling(60).max()
    out["max_drawdown_60"] = out["close"] / rolling_high - 1
    out["premium_20"] = out["close"] / out["ma20"] - 1
    out["avg_amount_20"] = out["amount"].rolling(20).mean() if "amount" in out.columns else np.nan
    out["avg_volume_20"] = out["volume"].rolling(20).mean() if "volume" in out.columns else np.nan
    out["trend_pass"] = (out["close"] > out["ma60"]) & (out["ma20"] > out["ma60"])
    return out


def score_cross_section(snapshot: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    out = snapshot.copy()
    factors = cfg["strategy"]["technical_factors"]
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
