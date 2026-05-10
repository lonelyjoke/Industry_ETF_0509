from __future__ import annotations

import pandas as pd

from .features_fundamental import merge_fundamental
from .utils import safe_zscore


def classify_market(snapshot: pd.DataFrame, benchmark_row: pd.Series | None, market_context: pd.Series | None = None) -> dict:
    """Explainable four-level market regime classifier."""
    width = float((snapshot["close"] > snapshot["ma60"]).fillna(False).mean()) if not snapshot.empty else 0.0
    if width >= 0.60:
        breadth_score = 2
    elif width >= 0.40:
        breadth_score = 1
    elif width >= 0.25:
        breadth_score = 0
    else:
        breadth_score = -1

    trend_score = 0
    risk_score = 0
    if benchmark_row is not None and not benchmark_row.empty:
        close = benchmark_row.get("close")
        ma60 = benchmark_row.get("ma60")
        ma120 = benchmark_row.get("ma120")
        ma250 = benchmark_row.get("ma250")
        if pd.notna(close) and pd.notna(ma120) and pd.notna(ma60):
            if close > ma120 and ma60 > ma120:
                trend_score = 2
            elif close > ma120:
                trend_score = 1
            elif pd.notna(ma250) and close > ma250:
                trend_score = 0
            else:
                trend_score = -1
        dd60 = benchmark_row.get("max_drawdown_60")
        if pd.notna(dd60):
            if dd60 <= -0.15:
                risk_score = -2
            elif dd60 <= -0.08:
                risk_score = -1

    structure = _structure_score(snapshot)
    margin_risk = 0
    margin_balance_percentile = pd.NA
    margin_balance_change = pd.NA
    if market_context is not None and not market_context.empty:
        margin_risk = int(market_context.get("margin_risk_score", 0) or 0)
        margin_balance_percentile = market_context.get("margin_balance_percentile", pd.NA)
        margin_balance_change = market_context.get("margin_balance_change", pd.NA)

    total = trend_score + breadth_score + risk_score + structure["structure_score"] + margin_risk
    if total >= 3:
        state = "strong"
    elif total >= 1:
        state = "neutral"
    elif total >= -1:
        state = "weak"
    else:
        state = "crisis"
    return {
        "market_state": state,
        "market_score": total,
        "index_trend_score": trend_score,
        "breadth_score": breadth_score,
        "risk_score": risk_score,
        "structure_score": structure["structure_score"],
        "top3_ret60": structure["top3_ret60"],
        "positive_ret60_ratio": structure["positive_ret60_ratio"],
        "top3_relative_ret60": structure["top3_relative_ret60"],
        "margin_risk_score": margin_risk,
        "margin_balance_percentile": margin_balance_percentile,
        "margin_balance_change": margin_balance_change,
        "strong_etf_ratio": width,
    }


def _structure_score(snapshot: pd.DataFrame) -> dict:
    if snapshot.empty or "ret_60" not in snapshot.columns:
        return {"structure_score": 0, "top3_ret60": 0.0, "positive_ret60_ratio": 0.0, "top3_relative_ret60": 0.0}
    ret = pd.to_numeric(snapshot["ret_60"], errors="coerce").dropna()
    if ret.empty:
        return {"structure_score": 0, "top3_ret60": 0.0, "positive_ret60_ratio": 0.0, "top3_relative_ret60": 0.0}
    top3 = ret.sort_values(ascending=False).head(3).mean()
    positive_ratio = float((ret > 0).mean())
    if "relative_ret_60" in snapshot.columns:
        rel = pd.to_numeric(snapshot["relative_ret_60"], errors="coerce").dropna().sort_values(ascending=False).head(3).mean()
    else:
        rel = 0.0
    score = 1 if top3 > 0.10 and positive_ratio >= 0.40 and rel > 0 else 0
    return {"structure_score": score, "top3_ret60": float(top3), "positive_ret60_ratio": positive_ratio, "top3_relative_ret60": float(rel)}


def _style_score(group: pd.DataFrame, factors: dict[str, float]) -> pd.Series:
    score = pd.Series(0.0, index=group.index)
    for col, weight in factors.items():
        if col not in group.columns:
            continue
        values = pd.to_numeric(group[col], errors="coerce")
        if values.notna().sum() == 0:
            continue
        score += weight * safe_zscore(values.fillna(values.median()))
    return score


def _trend_pass_by_style(df: pd.DataFrame) -> pd.Series:
    growth = df["style"].eq("growth")
    stable = df["style"].eq("stable_value")
    cyclical = df["style"].eq("cyclical_value")
    out = pd.Series(False, index=df.index)
    out.loc[growth] = df.loc[growth, "trend_pass"].fillna(False)
    out.loc[stable] = ((df.loc[stable, "close"] > df.loc[stable, "ma60"]) | (df.loc[stable, "close"] > df.loc[stable, "ma120"])).fillna(False)
    out.loc[cyclical] = (
        (df.loc[cyclical, "close"] > df.loc[cyclical, "ma60"])
        & (df.loc[cyclical, "ma20"] > df.loc[cyclical, "ma60"])
        & (df.loc[cyclical, "ret_60"] > 0)
    ).fillna(False)
    return out


def _select_for_style(
    ranked: pd.DataFrame,
    style: str,
    style_weight: float,
    config: dict,
    current_holdings: set[str],
) -> list[int]:
    if style_weight <= 0 or ranked.empty:
        return []
    top_k = int(config["strategy"].get("style_top_k", {}).get(style, 1))
    keep_rank = int(config["strategy"].get("keep_if_rank_within", 2))
    buffer = float(config["strategy"].get("switch_buffer", 0.20))
    eligible = ranked[ranked["style"].eq(style)].copy()
    if eligible.empty:
        return []
    eligible = eligible.sort_values("style_score", ascending=False)
    eligible["style_rank"] = range(1, len(eligible) + 1)

    held = eligible[eligible["etf_code"].isin(current_holdings)]
    if top_k == 1 and not held.empty:
        held_row = held.iloc[0]
        top_row = eligible.iloc[0]
        rank_ok = int(held_row["style_rank"]) <= keep_rank
        score_gap = float(top_row["style_score"] - held_row["style_score"])
        if rank_ok or score_gap < buffer:
            return [held_row.name]
    return eligible.head(top_k).index.tolist()


def build_weekly_ranking(
    snapshot: pd.DataFrame,
    fundamental_scores: pd.DataFrame,
    benchmark_row: pd.Series | None,
    config: dict,
    current_holdings: set[str] | None = None,
    market_context: pd.Series | None = None,
) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    current_holdings = current_holdings or set()
    out = merge_fundamental(snapshot.copy(), fundamental_scores)
    out["style"] = out.get("style", "stable_value").fillna("stable_value")

    liq_threshold = config["strategy"].get("liquidity_threshold", 30000000)
    if out["avg_amount_20"].notna().any():
        out["liquidity_pass"] = out["avg_amount_20"] >= liq_threshold
    else:
        out["liquidity_pass"] = out["avg_volume_20"].fillna(0) > 0
    out["trend_filter_pass"] = _trend_pass_by_style(out)
    out["valuation_filter_pass"] = out.get("valuation_filter_pass", True)
    out["intraday_filter_pass"] = True

    market = classify_market(out, benchmark_row, market_context)
    base_allocations = config["strategy"]["style_allocation"][market["market_state"]]
    allocations = _adjust_allocations(base_allocations, market, config)
    for key, value in market.items():
        out[key] = value
    out["market_filter_pass"] = True
    out["style_target_weight"] = out["style"].map(allocations).fillna(0.0)
    out["base_style_target_weight"] = out["style"].map(base_allocations).fillna(0.0)
    out["cash_target_weight"] = allocations.get("cash", 0.0)

    out["style_score"] = 0.0
    growth_idx = out["style"].eq("growth")
    stable_idx = out["style"].eq("stable_value")
    cyclical_idx = out["style"].eq("cyclical_value")
    if growth_idx.any():
        out.loc[growth_idx, "style_score"] = _style_score(out.loc[growth_idx], config["strategy"]["growth_factors"])
    if stable_idx.any():
        out.loc[stable_idx, "style_score"] = _style_score(out.loc[stable_idx], config["strategy"]["stable_value_factors"])
    if cyclical_idx.any():
        out.loc[cyclical_idx, "style_score"] = _style_score(out.loc[cyclical_idx], config["strategy"]["cyclical_value_factors"])
    out["technical_score"] = out["style_score"]
    out["final_score"] = out["style_score"]

    out["selected"] = False
    out["target_weight"] = 0.0
    out["style_rank"] = pd.NA
    out["kept_by_buffer"] = False

    eligible = out[out["liquidity_pass"] & out["trend_filter_pass"] & out["valuation_filter_pass"]].copy()
    min_score = config["backtest"].get("min_final_score")
    if min_score is not None:
        eligible = eligible[eligible["final_score"] >= float(min_score)]

    selected_indices: list[int] = []
    for style in ["growth", "stable_value", "cyclical_value"]:
        style_weight = float(allocations.get(style, 0.0))
        picks = _select_for_style(eligible, style, style_weight, config, current_holdings)
        if not picks:
            continue
        selected_indices.extend(picks)
        style_picks = eligible.loc[picks]
        per_weight = style_weight / len(style_picks)
        out.loc[picks, "target_weight"] = per_weight
        out.loc[picks, "selected"] = True

    ranked_parts = [group.sort_values("style_score", ascending=False) for _, group in out.groupby("style")]
    ranked_all = pd.concat(ranked_parts) if ranked_parts else out
    for _, group in ranked_all.groupby("style"):
        out.loc[group.index, "style_rank"] = range(1, len(group) + 1)
    out.loc[out["selected"] & out["etf_code"].isin(current_holdings), "kept_by_buffer"] = True
    return out.sort_values(["selected", "style", "style_score"], ascending=[False, True, False])


def _adjust_allocations(base: dict, market: dict, config: dict) -> dict:
    adj = dict(base)
    params = config["strategy"].get("allocation_adjustment", {})
    cash_key = "cash"
    if market.get("structure_score", 0) >= 1:
        if market["market_state"] == "neutral":
            add = float(params.get("structure_neutral_growth_add", 0.10))
            adj["growth"] = adj.get("growth", 0) + add
            adj[cash_key] = adj.get(cash_key, 0) - add
        elif market["market_state"] == "weak":
            g = float(params.get("structure_weak_growth_add", 0.05))
            c = float(params.get("structure_weak_cyclical_add", 0.05))
            adj["growth"] = adj.get("growth", 0) + g
            adj["cyclical_value"] = adj.get("cyclical_value", 0) + c
            adj[cash_key] = adj.get(cash_key, 0) - g - c
    if market.get("margin_risk_score", 0) <= -1:
        gcut = float(params.get("margin_growth_cut", 0.10))
        ccut = float(params.get("margin_cyclical_cut", 0.05))
        adj["growth"] = max(0.0, adj.get("growth", 0) - gcut)
        adj["cyclical_value"] = max(0.0, adj.get("cyclical_value", 0) - ccut)
        adj[cash_key] = adj.get(cash_key, 0) + gcut + ccut
    adj["growth"] = min(adj.get("growth", 0), float(params.get("max_growth", 0.60)))
    adj["cyclical_value"] = min(adj.get("cyclical_value", 0), float(params.get("max_cyclical_value", 0.20)))
    adj["stable_value"] = max(adj.get("stable_value", 0), float(params.get("min_stable_value", 0.25)))
    adj[cash_key] = max(adj.get(cash_key, 0), 0.0)
    total = sum(adj.values())
    if total > 1.0:
        scale = 1.0 / total
        for key in adj:
            adj[key] *= scale
    return adj
