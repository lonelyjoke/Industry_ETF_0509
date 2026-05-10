from __future__ import annotations

import pandas as pd


def intraday_buy_filter(df: pd.DataFrame, max_premium: float = 0.05) -> tuple[bool, str]:
    """60-minute execution filter. Empty data means module is unavailable, not a hard failure."""
    if df.empty or len(df) < 60:
        return True, "intraday_unavailable"
    out = df.copy()
    if "trade_time" in out.columns:
        out = out.sort_values("trade_time")
    out["ma20h"] = out["close"].rolling(20).mean()
    out["ma60h"] = out["close"].rolling(60).mean()
    last = out.iloc[-1]
    if pd.isna(last["ma60h"]) or pd.isna(last["ma20h"]):
        return True, "intraday_insufficient"
    premium = last["close"] / last["ma20h"] - 1
    recent = out.tail(8)["close"].diff().dropna()
    continuous_weak = len(recent.tail(4)) == 4 and (recent.tail(4) < 0).all()
    ma20_up = out["ma20h"].iloc[-1] > out["ma20h"].iloc[-4] if len(out) >= 64 else False
    ok = (
        last["close"] > last["ma60h"]
        and (last["ma20h"] > last["ma60h"] or ma20_up)
        and not continuous_weak
        and premium <= max_premium
    )
    reason = "intraday_pass" if ok else "intraday_block_chasing_or_weak"
    return bool(ok), reason
