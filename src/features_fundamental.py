from __future__ import annotations

from pathlib import Path
import time

import numpy as np
import pandas as pd

from .data import DataClient
from .utils import ensure_dir


ISSUE_COLUMNS = ["trade_date", "scope", "issue", "detail"]


def compute_fundamental_scores(config: dict, as_of_dates: list[pd.Timestamp]) -> pd.DataFrame:
    """Compute low-frequency ETF fundamental proxies.

    v0.3 tries to estimate ETF/industry dividend yield and valuation by constituent
    aggregation. It falls back to manual config scores when constituent or daily_basic
    data is unavailable, and records data issues for review.
    """

    if not config.get("data", {}).get("use_fundamental", True):
        return pd.DataFrame()

    universe = pd.DataFrame(config.get("etf_universe", []))
    as_of = pd.to_datetime(pd.Series(as_of_dates).drop_duplicates()).sort_values()
    if as_of.empty or universe.empty:
        return pd.DataFrame()

    fund_dir = ensure_dir("data/fundamental")
    issues: list[dict] = []
    monthly_dates = as_of.groupby(as_of.dt.to_period("M")).max().tolist()
    monthly = _compute_monthly_fundamentals(config, universe, monthly_dates, fund_dir, issues)
    manual = _manual_fundamentals(config, universe, monthly_dates)
    if monthly.empty:
        monthly = manual
    else:
        monthly = _fill_monthly_fallback(monthly, manual)

    scores = []
    for _, etf in universe.iterrows():
        code = etf["etf_code"]
        m = monthly[monthly["etf_code"].eq(code)].sort_values("trade_date")
        if m.empty:
            continue
        for dt in as_of:
            hist = m[m["trade_date"] <= dt]
            if hist.empty:
                row = m.iloc[0].copy()
            else:
                row = hist.iloc[-1].copy()
            row["trade_date"] = pd.Timestamp(dt)
            scores.append(row)
    out = pd.DataFrame(scores)
    if out.empty:
        return out

    out = out.sort_values(["etf_code", "trade_date"]).reset_index(drop=True)
    out["pb_percentile"] = out.groupby("etf_code")["weighted_pb"].transform(_rolling_percentile)
    out["pe_percentile"] = out.groupby("etf_code")["weighted_pe_ttm"].transform(_rolling_percentile)
    out["valuation_percentile"] = out[["pb_percentile", "pe_percentile"]].mean(axis=1, skipna=True)
    out["valuation_score"] = 1 - out["valuation_percentile"]
    out = _add_dividend_spread(config, out, issues)
    out["dividend_yield_percentile"] = out.groupby("trade_date")["dividend_yield_abs"].rank(pct=True)
    out["dividend_spread_percentile"] = out.groupby("trade_date")["dividend_spread"].rank(pct=True)
    out["valuation_score"] = out["valuation_score"].fillna(out["manual_score"])
    out["dividend_yield_percentile"] = out["dividend_yield_percentile"].fillna(0.5)
    out["dividend_spread_percentile"] = out["dividend_spread_percentile"].fillna(0.5)
    out["growth_fundamental_score"] = out["manual_score"]
    out["roe_score"] = out.get("roe_score", pd.Series(pd.NA, index=out.index))
    out["fundamental_score"] = (
        0.40 * out["valuation_score"].fillna(out["manual_score"])
        + 0.35 * out["dividend_yield_percentile"].fillna(0.5)
        + 0.25 * out["manual_score"].fillna(0.5)
    )
    out["valuation_filter_pass"] = ~((out["valuation_percentile"] > 0.90) & (out["source"].ne("manual_fallback")))
    out = out.rename(columns={"source": "fundamental_source"})

    issue_path = Path("outputs") / "fundamental_data_issues.csv"
    ensure_dir("outputs")
    pd.DataFrame(issues, columns=ISSUE_COLUMNS).to_csv(issue_path, index=False, encoding="utf-8-sig")
    out.to_csv(fund_dir / "fundamental_scores_monthly_mapped.csv", index=False, encoding="utf-8-sig")
    return out


def _compute_monthly_fundamentals(
    config: dict,
    universe: pd.DataFrame,
    monthly_dates: list[pd.Timestamp],
    fund_dir: Path,
    issues: list[dict],
) -> pd.DataFrame:
    cache_path = fund_dir / "weighted_fundamentals_monthly.csv"
    if cache_path.exists():
        cached = pd.read_csv(cache_path)
        cached["trade_date"] = pd.to_datetime(cached["trade_date"])
        return cached

    client = DataClient(config, refresh=False)
    constituents = _load_constituents(client, universe, issues)
    if constituents.empty:
        issues.append({"scope": "all", "issue": "no_constituents", "detail": "未能获取任何指数或行业成分"})
        return pd.DataFrame()

    rows = []
    for dt in monthly_dates:
        trade_date = pd.Timestamp(dt)
        trade_date_str = trade_date.strftime("%Y%m%d")
        try:
            basic = client.cached_call("daily_basic", {"trade_date": trade_date_str})
        except Exception as exc:
            issues.append({"trade_date": trade_date_str, "scope": "daily_basic", "issue": "fetch_failed", "detail": str(exc)})
            continue
        if basic.empty:
            issues.append({"trade_date": trade_date_str, "scope": "daily_basic", "issue": "empty", "detail": "daily_basic 返回空"})
            continue
        for col in ["dv_ttm", "pb", "pe_ttm", "circ_mv"]:
            if col in basic.columns:
                basic[col] = pd.to_numeric(basic[col], errors="coerce")
        for _, etf in universe.iterrows():
            code = etf["etf_code"]
            c = constituents[constituents["etf_code"].eq(code)].copy()
            if c.empty:
                issues.append({"trade_date": trade_date_str, "scope": code, "issue": "no_constituents", "detail": "无可用成分，使用手工降级"})
                continue
            c = c[(pd.to_datetime(c["in_date"], errors="coerce") <= trade_date) & (c["out_date"].isna() | (pd.to_datetime(c["out_date"], errors="coerce") > trade_date))]
            merged = c.merge(basic, left_on="con_code", right_on="ts_code", how="left")
            merged = merged.dropna(subset=["pb", "circ_mv"], how="all")
            if merged.empty:
                issues.append({"trade_date": trade_date_str, "scope": code, "issue": "no_daily_basic_match", "detail": "成分股无估值匹配"})
                continue
            weights = _weights(merged)
            dividend = np.nansum(weights * (merged["dv_ttm"].fillna(0).to_numpy() / 100.0))
            pb = np.nansum(weights * merged["pb"].fillna(np.nan).to_numpy())
            pe = _weighted_harmonic_pe(merged, weights)
            rows.append(
                {
                    "trade_date": trade_date,
                    "etf_code": code,
                    "theme": etf["theme"],
                    "style": etf.get("style", ""),
                    "dividend_yield_abs": dividend,
                    "weighted_pb": pb if pd.notna(pb) and pb > 0 else np.nan,
                    "weighted_pe_ttm": pe,
                    "constituent_count": len(merged),
                    "source": "constituent_weighted",
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out.to_csv(cache_path, index=False, encoding="utf-8-sig")
    return out


def _load_constituents(client: DataClient, universe: pd.DataFrame, issues: list[dict]) -> pd.DataFrame:
    rows = []
    for _, etf in universe.iterrows():
        code = etf["etf_code"]
        idx = etf.get("tracking_index_code")
        sw = etf.get("sw_industry_code")
        if idx:
            try:
                w = client.cached_call("index_weight", {"index_code": idx})
                if not w.empty:
                    w["etf_code"] = code
                    rows.append(w.rename(columns={"index_code": "source_index"}))
                    continue
            except Exception as exc:
                issues.append({"scope": code, "issue": "index_weight_failed", "detail": str(exc)})
        if sw:
            try:
                m = client.cached_call("index_member", {"index_code": sw})
                if not m.empty:
                    m = m.copy()
                    m["etf_code"] = code
                    m["source_index"] = sw
                    m["weight"] = np.nan
                    rows.append(m)
                    continue
                issues.append({"scope": code, "issue": "index_member_empty", "detail": sw})
            except Exception as exc:
                issues.append({"scope": code, "issue": "index_member_failed", "detail": f"{sw}: {exc}"})
        else:
            issues.append({"scope": code, "issue": "no_index_mapping", "detail": "tracking_index_code 和 sw_industry_code 均为空"})
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["in_date"] = pd.to_datetime(out.get("in_date"), errors="coerce")
    out["out_date"] = pd.to_datetime(out.get("out_date"), errors="coerce")
    return out[["etf_code", "source_index", "con_code", "in_date", "out_date", "weight"]]


def _weights(df: pd.DataFrame) -> np.ndarray:
    if "weight" in df.columns and df["weight"].notna().sum() > 0:
        w = pd.to_numeric(df["weight"], errors="coerce").fillna(0).to_numpy()
    elif "circ_mv" in df.columns and df["circ_mv"].notna().sum() > 0:
        w = pd.to_numeric(df["circ_mv"], errors="coerce").fillna(0).to_numpy()
    else:
        w = np.ones(len(df), dtype=float)
    total = np.nansum(w)
    if total <= 0:
        return np.ones(len(df), dtype=float) / max(len(df), 1)
    return w / total


def _weighted_harmonic_pe(df: pd.DataFrame, weights: np.ndarray) -> float:
    pe = pd.to_numeric(df.get("pe_ttm"), errors="coerce")
    valid = pe.notna() & (pe > 0)
    if valid.sum() == 0:
        return np.nan
    w = weights[valid.to_numpy()]
    p = pe[valid].to_numpy()
    denom = np.nansum(w * (1 / p))
    return float(1 / denom) if denom > 0 else np.nan


def _rolling_percentile(s: pd.Series, window: int = 36) -> pd.Series:
    values = []
    for i in range(len(s)):
        hist = s.iloc[max(0, i - window + 1) : i + 1].dropna()
        if len(hist) < 6 or pd.isna(s.iloc[i]):
            values.append(np.nan)
        else:
            values.append(float((hist <= s.iloc[i]).mean()))
    return pd.Series(values, index=s.index)


def _manual_fundamentals(config: dict, universe: pd.DataFrame, monthly_dates: list[pd.Timestamp]) -> pd.DataFrame:
    manual = config.get("manual_fundamental_scores", {})
    dividends = config.get("manual_dividend_yield", {})
    rows = []
    for dt in monthly_dates:
        for _, etf in universe.iterrows():
            theme = etf["theme"]
            rows.append(
                {
                    "trade_date": pd.Timestamp(dt),
                    "etf_code": etf["etf_code"],
                    "theme": theme,
                    "style": etf.get("style", ""),
                    "dividend_yield_abs": float(dividends.get(theme, 0.0)),
                    "weighted_pb": np.nan,
                    "weighted_pe_ttm": np.nan,
                    "constituent_count": 0,
                    "source": "manual_fallback",
                    "manual_score": float(manual.get(theme, 0.5)),
                }
            )
    return pd.DataFrame(rows)


def _fill_monthly_fallback(monthly: pd.DataFrame, manual: pd.DataFrame) -> pd.DataFrame:
    key = ["trade_date", "etf_code"]
    out = manual.merge(monthly, on=key, how="left", suffixes=("_manual", ""))
    for col in ["theme", "style", "dividend_yield_abs", "weighted_pb", "weighted_pe_ttm", "constituent_count", "source"]:
        manual_col = f"{col}_manual"
        if manual_col in out.columns:
            out[col] = out[col].combine_first(out[manual_col]) if col in out.columns else out[manual_col]
    out["source"] = out["source"].fillna("manual_fallback")
    out["manual_score"] = out["manual_score"].fillna(0.5)
    cols = ["trade_date", "etf_code", "theme", "style", "dividend_yield_abs", "weighted_pb", "weighted_pe_ttm", "constituent_count", "source", "manual_score"]
    return out[cols]


def merge_fundamental(daily_scores: pd.DataFrame, fundamental_scores: pd.DataFrame) -> pd.DataFrame:
    if daily_scores.empty:
        return daily_scores
    out = daily_scores.copy()
    if fundamental_scores.empty:
        out["fundamental_score"] = pd.NA
        out["valuation_filter_pass"] = True
        out["dividend_yield_abs"] = pd.NA
        out["dividend_yield_percentile"] = pd.NA
        out["valuation_score"] = pd.NA
        out["roe_score"] = pd.NA
        out["growth_fundamental_score"] = pd.NA
        return out
    cols = [
        "trade_date",
        "etf_code",
        "fundamental_score",
        "valuation_percentile",
        "valuation_filter_pass",
        "valuation_score",
        "roe_score",
        "growth_fundamental_score",
        "dividend_yield_abs",
        "dividend_yield_percentile",
        "dividend_spread",
        "dividend_spread_percentile",
        "weighted_pb",
        "weighted_pe_ttm",
        "pb_percentile",
        "pe_percentile",
        "fundamental_source",
        "constituent_count",
    ]
    present = [c for c in cols if c in fundamental_scores.columns]
    return out.merge(fundamental_scores[present], on=["trade_date", "etf_code"], how="left")


def _add_dividend_spread(config: dict, scores: pd.DataFrame, issues: list[dict]) -> pd.DataFrame:
    out = scores.copy()
    client = DataClient(config, refresh=False)
    yield_rows = []
    unique_dates = pd.to_datetime(out["trade_date"].drop_duplicates()).sort_values()
    monthly_dates = pd.Series(unique_dates).groupby(pd.Series(unique_dates).dt.to_period("M")).max().tolist()
    for dt in monthly_dates:
        date_str = dt.strftime("%Y%m%d")
        risk_free = pd.NA
        try:
            y = client.cached_call("yc_cb", {"trade_date": date_str})
            if str(client.last_source).startswith("api:"):
                time.sleep(3.1)
            if not y.empty:
                yy = y.copy()
                yy["curve_term"] = pd.to_numeric(yy["curve_term"], errors="coerce")
                yy["yield"] = pd.to_numeric(yy["yield"], errors="coerce")
                gov = yy[yy["curve_name"].astype(str).str.contains("国债", na=False)]
                if gov.empty:
                    gov = yy
                gov = gov.dropna(subset=["curve_term", "yield"])
                if not gov.empty:
                    idx = (gov["curve_term"] - 10).abs().idxmin()
                    risk_free = float(gov.loc[idx, "yield"]) / 100.0
            else:
                issues.append({"trade_date": date_str, "scope": "yc_cb", "issue": "empty", "detail": "yc_cb返回空"})
        except Exception as exc:
            issues.append({"trade_date": date_str, "scope": "yc_cb", "issue": "fetch_failed", "detail": str(exc)})
        yield_rows.append({"trade_date": dt, "risk_free_10y": risk_free})
    yields = pd.DataFrame(yield_rows)
    out = pd.merge_asof(
        out.sort_values("trade_date"),
        yields.sort_values("trade_date"),
        on="trade_date",
        direction="backward",
    )
    out["risk_free_10y"] = pd.to_numeric(out["risk_free_10y"], errors="coerce")
    out["dividend_spread"] = out["dividend_yield_abs"] - out["risk_free_10y"]
    out["dividend_spread"] = out["dividend_spread"].fillna(out["dividend_yield_abs"])
    return out
