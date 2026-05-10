from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from .backtest import BacktestResult
from .utils import annualize_return, ensure_dir


def performance_summary(result: BacktestResult, initial_cash: float) -> pd.DataFrame:
    eq = result.equity_curve.copy()
    eq["ret"] = eq["equity"].pct_change().fillna(0.0)
    total_return = eq["equity"].iloc[-1] / initial_cash - 1
    ann_ret = annualize_return(total_return, len(eq))
    ann_vol = eq["ret"].std(ddof=0) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    peak = eq["equity"].cummax()
    dd = eq["equity"] / peak - 1
    trades = result.trades
    positions = result.positions
    empty_ratio = float((eq["holding_value"] <= 1).mean())
    turnover = trades["value"].sum() / initial_cash if not trades.empty else 0.0
    avg_holding_days = 0.0
    if not trades.empty and "side" in trades:
        buys = trades[trades["side"] == "BUY"]
        sells = trades[trades["side"] == "SELL"]
        if not buys.empty and not sells.empty:
            avg_holding_days = max(0.0, (sells["trade_date"].max() - buys["trade_date"].min()).days / max(len(sells), 1))
    win_rate = float((eq["ret"] > 0).mean())
    rows = {
        "total_return": total_return,
        "annual_return": ann_ret,
        "annual_volatility": ann_vol,
        "max_drawdown": dd.min(),
        "sharpe": sharpe,
        "win_rate": win_rate,
        "trade_count": 0 if trades.empty else len(trades),
        "avg_holding_days": avg_holding_days,
        "turnover": turnover,
        "cash_ratio": empty_ratio,
    }
    if not result.benchmark.empty and "close" in result.benchmark.columns:
        bench = result.benchmark.dropna(subset=["close"]).copy()
        if len(bench) > 1:
            bench_total = bench["close"].iloc[-1] / bench["close"].iloc[0] - 1
            rows["benchmark_total_return"] = bench_total
            rows["benchmark_annual_return"] = annualize_return(bench_total, len(bench))
    return pd.DataFrame([rows])


def save_outputs(result: BacktestResult, config: dict, output_dir: str | Path = "outputs") -> None:
    out = ensure_dir(output_dir)
    result.equity_curve.to_csv(out / "equity_curve.csv", index=False, encoding="utf-8-sig")
    _nonempty_frame(result.trades, ["trade_date", "etf_code", "side", "price", "shares", "value", "fee"]).to_csv(
        out / "trades.csv", index=False, encoding="utf-8-sig"
    )
    _nonempty_frame(result.positions, ["trade_date", "etf_code", "shares", "close", "weight"]).to_csv(
        out / "positions.csv", index=False, encoding="utf-8-sig"
    )
    weekly = _with_chinese_weekly_columns(result.weekly_ranking)
    weekly.to_csv(out / "weekly_ranking.csv", index=False, encoding="utf-8-sig")
    result.fundamental_scores.to_csv(out / "fundamental_scores.csv", index=False, encoding="utf-8-sig")
    result.combined_scores.to_csv(out / "combined_scores.csv", index=False, encoding="utf-8-sig")
    perf = performance_summary(result, float(config["backtest"].get("initial_cash", 1_000_000)))
    perf.to_csv(out / "performance_summary.csv", index=False, encoding="utf-8-sig")

    eq = result.equity_curve.copy()
    eq["trade_date"] = pd.to_datetime(eq["trade_date"])
    plt.figure(figsize=(10, 4))
    plt.plot(eq["trade_date"], eq["equity"], label="strategy")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out / "equity_curve.png", dpi=150)
    plt.close()

    dd = eq["equity"] / eq["equity"].cummax() - 1
    plt.figure(figsize=(10, 4))
    plt.fill_between(eq["trade_date"], dd, 0, alpha=0.4)
    plt.tight_layout()
    plt.savefig(out / "drawdown.png", dpi=150)
    plt.close()


def _with_chinese_weekly_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    aliases = {
        "signal_date": "日期",
        "etf_code": "ETF代码",
        "etf_name": "ETF名称",
        "theme": "主题",
        "technical_score": "技术面得分",
        "fundamental_score": "基本面得分",
        "final_score": "综合得分",
        "liquidity_pass": "是否通过流动性过滤",
        "trend_filter_pass": "是否通过趋势过滤",
        "valuation_filter_pass": "是否通过估值过滤",
        "market_filter_pass": "是否通过市场环境过滤",
        "intraday_filter_pass": "是否通过60分钟过滤",
        "selected": "最终是否入选",
        "target_weight": "目标仓位",
    }
    for src, dst in aliases.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    chinese_first = [v for v in aliases.values() if v in out.columns]
    rest = [c for c in out.columns if c not in chinese_first]
    return out[chinese_first + rest]


def _nonempty_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=columns)
    return df
