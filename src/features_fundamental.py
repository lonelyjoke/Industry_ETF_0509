from __future__ import annotations

import pandas as pd


def compute_fundamental_scores(config: dict, as_of_dates: list[pd.Timestamp]) -> pd.DataFrame:
    """Lightweight v0.1 fundamental module.

    With low Tushare permissions, strict point-in-time weighted fundamentals are often unavailable.
    v0.1 therefore uses configured manual industry scores as a safe fallback and keeps all rows
    date-stamped so real PIT factors can replace them later.
    """

    if not config.get("data", {}).get("use_fundamental", True):
        return pd.DataFrame()
    manual = config.get("manual_fundamental_scores", {})
    universe = pd.DataFrame(config.get("etf_universe", []))
    rows = []
    for dt in as_of_dates:
        for _, etf in universe.iterrows():
            if not bool(etf.get("enable_fundamental", True)):
                continue
            theme = etf["theme"]
            base = float(manual.get(theme, 0.5))
            rows.append(
                {
                    "trade_date": pd.Timestamp(dt),
                    "etf_code": etf["etf_code"],
                    "theme": theme,
                    "valuation_percentile": pd.NA,
                    "valuation_score": base,
                    "roe_score": pd.NA,
                    "net_profit_growth_score": pd.NA,
                    "revenue_growth_score": pd.NA,
                    "fundamental_score": base,
                    "fundamental_source": "manual_config_fallback",
                    "valuation_filter_pass": True,
                }
            )
    return pd.DataFrame(rows)


def merge_fundamental(daily_scores: pd.DataFrame, fundamental_scores: pd.DataFrame) -> pd.DataFrame:
    if daily_scores.empty:
        return daily_scores
    out = daily_scores.copy()
    if fundamental_scores.empty:
        out["fundamental_score"] = pd.NA
        out["valuation_filter_pass"] = True
        return out
    cols = ["trade_date", "etf_code", "fundamental_score", "valuation_percentile", "valuation_filter_pass"]
    return out.merge(fundamental_scores[cols], on=["trade_date", "etf_code"], how="left")
