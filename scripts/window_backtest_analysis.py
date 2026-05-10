from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data import DataClient
from src.utils import annualize_return, load_config


OUTPUT_DIR = PROJECT_ROOT / "outputs"


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "无数据"
    cols = list(df.columns)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def format_percent(x: float) -> str:
    return "" if pd.isna(x) else f"{x:.2%}"


def load_benchmark(config: dict) -> tuple[str, pd.DataFrame]:
    bench_code = config.get("data", {}).get("market_index_code", "000300.SH")
    client = DataClient(config, refresh=False)
    bench = client.get_index_daily(
        bench_code,
        config.get("data", {}).get("start_date"),
        config.get("data", {}).get("end_date"),
    )
    if bench.empty:
        return bench_code, pd.DataFrame(columns=["trade_date", "close"])
    return bench_code, bench[["trade_date", "close"]].dropna().sort_values("trade_date")


def slice_metrics(eq: pd.DataFrame, trades: pd.DataFrame, bench: pd.DataFrame, name: str, start, end) -> dict | None:
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    window = eq[(eq["trade_date"] >= start) & (eq["trade_date"] <= end)].copy()
    if len(window) < 2:
        return None

    total_return = window["equity"].iloc[-1] / window["equity"].iloc[0] - 1
    annual_return = annualize_return(total_return, len(window))
    annual_volatility = window["daily_ret"].std(ddof=0) * np.sqrt(252)
    sharpe = annual_return / annual_volatility if annual_volatility > 0 else 0.0
    drawdown = window["equity"] / window["equity"].cummax() - 1
    window_trades = trades[(trades["trade_date"] >= start) & (trades["trade_date"] <= end)] if not trades.empty else pd.DataFrame()
    turnover = window_trades["value"].sum() / window["equity"].iloc[0] if not window_trades.empty else 0.0

    benchmark_total_return = np.nan
    benchmark_annual_return = np.nan
    if not bench.empty:
        b = bench[(bench["trade_date"] >= start) & (bench["trade_date"] <= end)]
        if len(b) > 1:
            benchmark_total_return = b["close"].iloc[-1] / b["close"].iloc[0] - 1
            benchmark_annual_return = annualize_return(benchmark_total_return, len(b))

    return {
        "窗口": name,
        "开始日期": window["trade_date"].iloc[0].date().isoformat(),
        "结束日期": window["trade_date"].iloc[-1].date().isoformat(),
        "交易日数": len(window),
        "策略收益": total_return,
        "策略年化": annual_return,
        "年化波动": annual_volatility,
        "最大回撤": float(drawdown.min()),
        "夏普": sharpe,
        "交易次数": int(len(window_trades)),
        "换手率": turnover,
        "平均现金仓位": float((window["cash"] / window["equity"]).mean()),
        "基准收益": benchmark_total_return,
        "基准年化": benchmark_annual_return,
        "超额收益": total_return - benchmark_total_return if pd.notna(benchmark_total_return) else np.nan,
    }


def build_window_summary(eq: pd.DataFrame, trades: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, group in eq.groupby(eq["trade_date"].dt.year):
        label = f"{year}" if year < eq["trade_date"].dt.year.max() else f"{year}YTD"
        rows.append(slice_metrics(eq, trades, bench, label, group["trade_date"].min(), group["trade_date"].max()))

    start = eq["trade_date"].min().normalize()
    end = eq["trade_date"].max().normalize()
    current = pd.Timestamp(start.year, start.month, 1)
    while current + pd.DateOffset(months=24) <= end + pd.DateOffset(days=1):
        window_end = current + pd.DateOffset(months=24) - pd.DateOffset(days=1)
        rows.append(slice_metrics(eq, trades, bench, f"{current.date()}~{window_end.date()}", current, window_end))
        current += pd.DateOffset(months=6)

    latest_start = end - pd.DateOffset(months=24) + pd.DateOffset(days=1)
    rows.append(slice_metrics(eq, trades, bench, f"最近24个月({latest_start.date()}~{end.date()})", latest_start, end))
    return pd.DataFrame([r for r in rows if r is not None])


def readable_summary(summary: pd.DataFrame) -> pd.DataFrame:
    pretty = summary.copy()
    percent_cols = ["策略收益", "策略年化", "年化波动", "最大回撤", "换手率", "平均现金仓位", "基准收益", "基准年化", "超额收益"]
    for col in percent_cols:
        pretty[col] = pd.to_numeric(pretty[col], errors="coerce").map(format_percent)
    pretty["夏普"] = pd.to_numeric(pretty["夏普"], errors="coerce").map(lambda x: "" if pd.isna(x) else f"{x:.2f}")
    return pretty


def factor_rows() -> list[tuple[str, str, str, str, str]]:
    return [
        ("ret_20", "成长", "0.10", "越高越好", "近20个交易日收益率，捕捉短期强度，但权重较低，避免只追短线。"),
        ("ret_60", "成长/稳定红利/周期价值", "0.25/0.05/0.20", "越高越好", "近60个交易日收益率，是行业轮动的核心中期动量。"),
        ("ret_120", "成长/周期价值", "0.15/0.15", "越高越好", "近120个交易日收益率，用来确认中长期趋势不是短反弹。"),
        ("relative_ret_60", "成长/周期价值", "0.15/0.20", "越高越好", "ETF近60日收益减沪深300近60日收益，衡量是否有相对大盘的超额强度。"),
        ("trend_structure", "成长", "0.15", "越高越好", "价格站上关键均线且短均线强于长均线时更高。"),
        ("vol_20", "成长/稳定红利/周期价值", "-0.10/-0.10/-0.10", "越低越好", "近20日年化波动率，惩罚短期剧烈波动。"),
        ("premium_20", "成长", "-0.10", "越低越好", "当前价格相对20日均线偏离度，偏离过大说明可能短线过热。"),
        ("amount_crowding", "成长/周期价值", "-0.05/-0.05", "越低越好", "近20日成交额相对近120日成交额的放大程度，用来识别拥挤交易。"),
        ("valuation_percentile", "成长", "-0.05", "越低越好", "估值历史分位，成长池里估值越高越扣分。"),
        ("dividend_yield_abs", "稳定红利/周期价值", "0.15/0.05", "越高越好", "成分股加权估算的股息率绝对水平，偏向真实红利资产。"),
        ("dividend_yield_percentile", "稳定红利", "0.15", "越高越好", "当前股息率在同类/自身历史中的相对位置，避免只看绝对值。"),
        ("dividend_spread", "稳定红利", "0.20", "越高越好", "股息率减10年国债收益率，衡量红利资产相对无风险利率的吸引力。"),
        ("dividend_spread_percentile", "稳定红利", "0.15", "越高越好", "红利利差的历史分位，用来判断红利吸引力是否处在较好位置。"),
        ("valuation_score", "稳定红利/周期价值", "0.15/0.15", "越高越好", "由PB/PE自身历史分位换算，估值越便宜得分越高。"),
        ("drawdown_risk_60", "稳定红利/周期价值", "-0.05/-0.10", "越低越好", "近60日最大回撤风险，周期价值惩罚更重。"),
        ("index_trend_score", "市场状态", "状态分", "越高越好", "沪深300相对MA60/MA120/MA250的位置，用来判断大盘趋势层级。"),
        ("breadth_score", "市场状态", "状态分", "越高越好", "ETF池里站上MA60的比例，衡量市场赚钱效应宽度。"),
        ("risk_score", "市场状态", "状态分", "越高越好", "沪深300近60日回撤风险，深回撤时降低风险预算。"),
        ("structure_score", "市场状态/仓位修正", "状态分", "越高越好", "Top3 ETF强度、正收益ETF占比、相对沪深300超额共同确认结构性行情。"),
        ("margin_risk_score", "市场状态/仓位修正", "风险扣分", "越低越危险", "融资余额高分位且指数跌破MA20时视为杠杆过热后转弱，降低成长和周期仓位。"),
    ]


def write_report(summary: pd.DataFrame, pretty: pd.DataFrame, bench_code: str, start_date, end_date) -> None:
    year_mask = pretty["窗口"].astype(str).str.match(r"^\d{4}(YTD)?$")
    factor_df = pd.DataFrame(factor_rows(), columns=["因子", "使用位置", "权重", "方向", "解释"])
    lines = [
        "# v0.4 窗口回测与因子解释",
        "",
        f"- 回测区间：{start_date} 到 {end_date}",
        f"- 基准：{bench_code}",
        "- 说明：窗口结果是在同一条 v0.4 净值曲线上切片统计，不重新调参，不重跑新参数。",
        "",
        "## 分年度窗口",
        "",
        markdown_table(pretty[year_mask]),
        "",
        "## 滚动24个月窗口",
        "",
        markdown_table(pretty[~year_mask]),
        "",
        "## 因子解释",
        "",
        markdown_table(factor_df),
        "",
    ]
    (OUTPUT_DIR / "window_backtest_report.md").write_text("\n".join(lines), encoding="utf-8")
    factor_df.to_csv(OUTPUT_DIR / "factor_explanations.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    config = load_config()
    equity = pd.read_csv(OUTPUT_DIR / "equity_curve.csv", parse_dates=["trade_date"]).sort_values("trade_date")
    equity["daily_ret"] = equity["equity"].pct_change().fillna(0.0)
    trades = pd.read_csv(OUTPUT_DIR / "trades.csv", parse_dates=["trade_date"])
    bench_code, benchmark = load_benchmark(config)

    summary = build_window_summary(equity, trades, benchmark)
    pretty = readable_summary(summary)
    summary.to_csv(OUTPUT_DIR / "window_backtest_summary.csv", index=False, encoding="utf-8-sig")
    pretty.to_csv(OUTPUT_DIR / "window_backtest_summary_readable.csv", index=False, encoding="utf-8-sig")
    write_report(summary, pretty, bench_code, equity["trade_date"].min().date(), equity["trade_date"].max().date())
    print("窗口回测分析已输出到 outputs/window_backtest_report.md")


if __name__ == "__main__":
    main()
