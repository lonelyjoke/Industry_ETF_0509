from __future__ import annotations

import pandas as pd

from .features_daily import score_cross_section
from .features_fundamental import merge_fundamental


def market_exposure(snapshot: pd.DataFrame, benchmark_row: pd.Series | None, config: dict) -> tuple[float, bool]:
    if benchmark_row is not None and not benchmark_row.empty and pd.notna(benchmark_row.get("ma120")):
        allowed = benchmark_row["close"] > benchmark_row["ma120"]
        return (1.0 if allowed else 0.0), bool(allowed)
    total = len(snapshot)
    if total == 0:
        return 0.0, False
    breadth = float(snapshot["trend_pass"].fillna(False).mean())
    if breadth < 0.30:
        return 0.0, False
    if breadth < 0.50:
        return 0.5, True
    return 1.0, True


def build_weekly_ranking(
    snapshot: pd.DataFrame,
    fundamental_scores: pd.DataFrame,
    benchmark_row: pd.Series | None,
    config: dict,
) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    out = score_cross_section(snapshot, config)
    out = merge_fundamental(out, fundamental_scores)
    liq_threshold = config["strategy"].get("liquidity_threshold", 30000000)
    if out["avg_amount_20"].notna().any():
        out["liquidity_pass"] = out["avg_amount_20"] >= liq_threshold
    else:
        out["liquidity_pass"] = out["avg_volume_20"].fillna(0) > 0
    out["trend_filter_pass"] = out["trend_pass"].fillna(False)
    out["valuation_filter_pass"] = out.get("valuation_filter_pass", True)

    f_available = out["fundamental_score"].notna().any()
    tw = config["strategy"].get("technical_weight", 0.70)
    fw = config["strategy"].get("fundamental_weight", 0.30)
    if f_available:
        out["final_score"] = tw * out["technical_score"] + fw * out["fundamental_score"].fillna(0.5)
    else:
        out["final_score"] = out["technical_score"]

    exposure, market_ok = market_exposure(out, benchmark_row, config)
    out["market_filter_pass"] = market_ok
    out["market_exposure"] = exposure
    out["intraday_filter_pass"] = True
    out["selected"] = False
    out["target_weight"] = 0.0

    eligible = out[out["liquidity_pass"] & out["trend_filter_pass"] & out["valuation_filter_pass"] & out["market_filter_pass"]].copy()
    min_score = config["backtest"].get("min_final_score")
    if min_score is not None:
        eligible = eligible[eligible["final_score"] >= float(min_score)]
    top_k = int(config["backtest"].get("top_k", 1))
    if exposure > 0 and not eligible.empty:
        selected_idx = eligible.sort_values("final_score", ascending=False).head(top_k).index
        out.loc[selected_idx, "selected"] = True
        out.loc[selected_idx, "target_weight"] = exposure / len(selected_idx)
    return out.sort_values(["selected", "final_score"], ascending=[False, False])
