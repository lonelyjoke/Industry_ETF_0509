from __future__ import annotations

import pandas as pd

from .data import DataClient
from .utils import ensure_dir


ISSUE_COLUMNS = ["trade_date", "scope", "issue", "detail"]


def compute_market_context(config: dict, signal_dates: list[pd.Timestamp], benchmark: pd.DataFrame) -> pd.DataFrame:
    """Compute low-frequency market context for v0.4.

    The v0.4 market layer uses margin balance as a risk-temperature proxy. If
    Tushare cannot return margin data, the backtest keeps running with neutral
    values and records the issue for the final report.
    """

    if not signal_dates:
        return pd.DataFrame()

    client = DataClient(config, refresh=False)
    rows = []
    issues = []
    bench = benchmark.copy()
    if not bench.empty:
        bench["trade_date"] = pd.to_datetime(bench["trade_date"])
        bench = bench.sort_values("trade_date")

    for dt in pd.to_datetime(signal_dates):
        date_str = dt.strftime("%Y%m%d")
        margin_balance = pd.NA
        margin_buy = pd.NA
        try:
            df = client.cached_call("margin", {"trade_date": date_str})
            if not df.empty:
                numeric = df.copy()
                for col in ["rzye", "rzmre", "rzrqye"]:
                    if col in numeric.columns:
                        numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
                if "rzrqye" in numeric.columns:
                    margin_balance = numeric["rzrqye"].sum()
                elif "rzye" in numeric.columns:
                    margin_balance = numeric["rzye"].sum()
                margin_buy = numeric["rzmre"].sum() if "rzmre" in numeric.columns else pd.NA
            else:
                issues.append(
                    {
                        "trade_date": date_str,
                        "scope": "margin",
                        "issue": "empty",
                        "detail": "margin returned no rows",
                    }
                )
        except Exception as exc:
            issues.append({"trade_date": date_str, "scope": "margin", "issue": "fetch_failed", "detail": str(exc)})

        bench_row = bench[bench["trade_date"] <= dt].tail(1)
        below_ma20 = False
        if not bench_row.empty and {"close", "ma20"}.issubset(bench_row.columns):
            ma20 = bench_row.iloc[0]["ma20"]
            below_ma20 = bool(bench_row.iloc[0]["close"] < ma20) if pd.notna(ma20) else False
        rows.append(
            {
                "trade_date": dt,
                "margin_balance": margin_balance,
                "margin_buy": margin_buy,
                "index_below_ma20": below_ma20,
            }
        )

    out = pd.DataFrame(rows).sort_values("trade_date")
    out["margin_balance"] = pd.to_numeric(out["margin_balance"], errors="coerce")
    out["margin_buy"] = pd.to_numeric(out["margin_buy"], errors="coerce")
    out["margin_balance_percentile"] = _rolling_percentile(out["margin_balance"], window=78)
    out["margin_balance_change"] = out["margin_balance"].pct_change(2, fill_method=None)
    out["margin_buy_ratio"] = out["margin_buy"] / out["margin_balance"]
    out["margin_risk_score"] = 0

    high = out["margin_balance_percentile"] > 0.85
    very_high = out["margin_balance_percentile"] > 0.95
    out.loc[high & out["index_below_ma20"], "margin_risk_score"] = -1
    out.loc[very_high & out["index_below_ma20"], "margin_risk_score"] = -2

    ensure_dir("outputs")
    pd.DataFrame(issues, columns=ISSUE_COLUMNS).to_csv("outputs/market_data_issues.csv", index=False, encoding="utf-8-sig")
    ensure_dir("data/fundamental")
    out.to_csv("data/fundamental/market_context.csv", index=False, encoding="utf-8-sig")
    return out


def _rolling_percentile(s: pd.Series, window: int) -> pd.Series:
    values = []
    for i in range(len(s)):
        hist = s.iloc[max(0, i - window + 1) : i + 1].dropna()
        if len(hist) < 6 or pd.isna(s.iloc[i]):
            values.append(pd.NA)
        else:
            values.append(float((hist <= s.iloc[i]).mean()))
    return pd.Series(values, index=s.index)
