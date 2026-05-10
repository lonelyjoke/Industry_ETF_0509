from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
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
    dd = eq["equity"] / eq["equity"].cummax() - 1
    trades = result.trades
    empty_ratio = float((eq["holding_value"] <= 1).mean())
    turnover = trades["value"].sum() / initial_cash if not trades.empty else 0.0
    avg_holding_days = 0.0
    if not trades.empty and "side" in trades:
        buys = trades[trades["side"] == "BUY"]
        sells = trades[trades["side"] == "SELL"]
        if not buys.empty and not sells.empty:
            avg_holding_days = max(0.0, (sells["trade_date"].max() - buys["trade_date"].min()).days / max(len(sells), 1))
    rows = {
        "total_return": total_return,
        "annual_return": ann_ret,
        "annual_volatility": ann_vol,
        "max_drawdown": dd.min(),
        "sharpe": sharpe,
        "win_rate": float((eq["ret"] > 0).mean()),
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
    _nonempty_frame(result.trades, ["trade_date", "etf_code", "etf_name", "theme", "style", "side", "price", "shares", "value", "fee"]).to_csv(
        out / "trades.csv", index=False, encoding="utf-8-sig"
    )
    _nonempty_frame(result.positions, ["trade_date", "etf_code", "etf_name", "theme", "style", "shares", "close", "weight"]).to_csv(
        out / "positions.csv", index=False, encoding="utf-8-sig"
    )
    weekly = _with_chinese_weekly_columns(result.weekly_ranking)
    weekly.to_csv(out / "weekly_ranking.csv", index=False, encoding="utf-8-sig")
    result.fundamental_scores.to_csv(out / "fundamental_scores.csv", index=False, encoding="utf-8-sig")
    result.combined_scores.to_csv(out / "combined_scores.csv", index=False, encoding="utf-8-sig")
    perf = performance_summary(result, float(config["backtest"].get("initial_cash", 1_000_000)))
    perf.to_csv(out / "performance_summary.csv", index=False, encoding="utf-8-sig")
    holding_pnl, closed_pnl = _pnl_reports(result)
    holding_pnl.to_csv(out / "holding_pnl.csv", index=False, encoding="utf-8-sig")
    closed_pnl.to_csv(out / "closed_trade_pnl.csv", index=False, encoding="utf-8-sig")
    (out / "backtest_report.md").write_text(_markdown_report(result, perf, config, holding_pnl, closed_pnl), encoding="utf-8")

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
        "style": "风格",
        "style_score": "风格内得分",
        "style_rank": "风格内排名",
        "style_target_weight": "风格目标仓位",
        "base_style_target_weight": "基础风格目标仓位",
        "cash_target_weight": "现金目标仓位",
        "market_state": "市场状态",
        "market_score": "市场状态分数",
        "index_trend_score": "指数趋势分",
        "breadth_score": "ETF宽度分",
        "risk_score": "回撤风险分",
        "structure_score": "结构行情分",
        "margin_risk_score": "融资风险分",
        "margin_balance_percentile": "融资余额分位",
        "margin_balance_change": "融资余额变化率",
        "strong_etf_ratio": "强势ETF占比",
        "top3_ret60": "Top3_60日收益",
        "top3_relative_ret60": "Top3相对收益",
        "positive_ret60_ratio": "60日正收益占比",
        "kept_by_buffer": "是否因缓冲保留",
        "dividend_yield_abs": "股息率",
        "dividend_yield_percentile": "股息率分位",
        "dividend_spread": "红利利差",
        "dividend_spread_percentile": "红利利差分位",
        "amount_crowding": "成交额拥挤度",
        "relative_ret_60": "相对沪深300_60日收益",
        "weighted_pb": "成分加权PB",
        "pb_percentile": "PB历史分位",
        "valuation_score": "估值得分",
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


def _markdown_report(result: BacktestResult, perf: pd.DataFrame, config: dict, holding_pnl: pd.DataFrame, closed_pnl: pd.DataFrame) -> str:
    p = perf.iloc[0].to_dict()
    lines = [
        "# ETF 行业轮动回测报告",
        "",
        "## 策略说明",
        "",
        f"本次策略版本为 `{config.get('strategy', {}).get('version', 'unknown')}`。策略采用“市场状态分层 + 三风格分仓 + 风格内部ETF轮动”的结构，不使用机器学习，也不做参数寻优。",
        "",
        "### 1. 市场状态如何判断",
        "",
        "市场状态分为 `strong`、`neutral`、`weak`、`crisis`。系统先用沪深300和ETF池计算市场状态分数，再决定成长、稳定红利、周期价值和现金的基础仓位。",
        "",
        "市场状态分数由以下部分组成：",
        "",
        "- 指数趋势分：沪深300收盘价、MA60、MA120、MA250。指数在中长期均线之上加分，跌破中长期趋势扣分。",
        "- ETF宽度分：ETF池中收盘价高于MA60的比例。宽度越高，说明行业赚钱效应越广。",
        "- 回撤风险分：沪深300近60日最大回撤。快速下跌时扣分。",
        "- 结构行情分：如果Top3 ETF的60日收益较强、ETF池中正收益比例较高，且相对沪深300有超额收益，则加分。",
        "- 融资风险分：使用Tushare `margin` 的融资余额分位。如果融资余额处于高分位且指数跌破MA20，说明杠杆过热后转弱，降低风险资产仓位。",
        "",
        "### 2. 风格仓位如何分配",
        "",
        "基础风格仓位如下：",
        "",
        _dict_table(config["strategy"]["style_allocation"]),
        "",
        "v0.4 会在基础仓位上做两类修正：",
        "",
        "- 强结构行情成立时，中性或弱市场可以适度提高成长/周期卫星仓位，减少现金。",
        "- 融资风险较高时，降低成长和周期价值仓位，提高现金。",
        "",
        "### 3. ETF池如何划分",
        "",
        "- `growth`：医药、半导体、芯片、人工智能、军工、新能源车、光伏。",
        "- `stable_value`：银行、消费、电力、红利。重点关注稳定现金流、股息和估值性价比。",
        "- `cyclical_value`：证券、地产、有色、煤炭、钢铁。周期价值不是防御资产，只有趋势确认时才参与。",
        "",
        "### 4. 风格内部如何挑选标的",
        "",
        "每个风格内部单独打分并排序。默认每个风格选择Top 1；如果当前持仓仍在风格内Top 2，或新候选分数优势不足，会尽量保留旧持仓，减少换手。",
        "",
        "成长池因子权重：",
        "",
        _factor_table(config["strategy"]["growth_factors"]),
        "",
        "稳定红利池因子权重：",
        "",
        _factor_table(config["strategy"]["stable_value_factors"]),
        "",
        "周期价值池因子权重：",
        "",
        _factor_table(config["strategy"]["cyclical_value_factors"]),
        "",
        "### 5. 新增因子解释",
        "",
        "- 红利利差：成分股加权股息率减去10年国债收益率，用来衡量红利资产相对无风险利率是否仍有吸引力。",
        "- 成交额拥挤度：20日平均成交额相对120日平均成交额的偏离。过高说明短期资金拥挤，成长和周期标的会被惩罚。",
        "- 相对沪深300收益：ETF 60日收益减去沪深300 60日收益。周期价值必须跑赢市场才算真正强势。",
        "- 融资风险：融资余额处于历史高位且指数转弱时，降低成长和周期仓位。",
        "",
        "### 6. 交易执行",
        "",
        f"- 调仓频率：`{config.get('backtest', {}).get('rebalance_frequency')}`。",
        f"- 执行价格：`{config.get('backtest', {}).get('execution_price')}`。",
        f"- 手续费率：`{config.get('backtest', {}).get('commission_rate')}`。",
        f"- 仓位容忍带：`{config.get('strategy', {}).get('rebalance_tolerance')}`，仓位偏离较小时不交易。",
        "",
        "## 绩效摘要",
        "",
        f"- 总收益: {p.get('total_return', 0):.2%}",
        f"- 年化收益: {p.get('annual_return', 0):.2%}",
        f"- 年化波动率: {p.get('annual_volatility', 0):.2%}",
        f"- 最大回撤: {p.get('max_drawdown', 0):.2%}",
        f"- 夏普比率: {p.get('sharpe', 0):.2f}",
        f"- 胜率: {p.get('win_rate', 0):.2%}",
        f"- 交易次数: {int(p.get('trade_count', 0))}",
        f"- 换手率: {p.get('turnover', 0):.2f}",
        f"- 空仓比例: {p.get('cash_ratio', 0):.2%}",
        "",
    ]
    if "benchmark_total_return" in p:
        lines += [
            "## 基准对比",
            "",
            f"- 基准总收益: {p.get('benchmark_total_return', 0):.2%}",
            f"- 基准年化收益: {p.get('benchmark_annual_return', 0):.2%}",
            "",
        ]
    if not result.weekly_ranking.empty:
        latest = result.weekly_ranking.sort_values("signal_date").tail(1).iloc[0]
        lines += [
            "## 最近市场状态",
            "",
            f"- 日期: {latest.get('signal_date')}",
            f"- 市场状态: `{latest.get('market_state')}`",
            f"- 市场状态分数: {latest.get('market_score')}",
            f"- 指数趋势分: {latest.get('index_trend_score')}",
            f"- ETF宽度分: {latest.get('breadth_score')}",
            f"- 回撤风险分: {latest.get('risk_score')}",
            f"- 结构行情分: {latest.get('structure_score')}",
            f"- 融资风险分: {latest.get('margin_risk_score')}",
            f"- 融资余额分位: {_fmt_pct(latest.get('margin_balance_percentile'))}",
            f"- 强势ETF占比: {_fmt_pct(latest.get('strong_etf_ratio'))}",
            "",
        ]
        selected = result.weekly_ranking[result.weekly_ranking["selected"]].tail(12)
        lines += ["## 最近入选记录", ""]
        if selected.empty:
            lines += ["最近没有入选标的。", ""]
        else:
            cols = ["signal_date", "etf_code", "etf_name", "theme", "style", "style_score", "target_weight", "dividend_spread", "amount_crowding", "relative_ret_60"]
            lines += [_to_markdown(selected[[c for c in cols if c in selected.columns]])]
    if not result.trades.empty:
        lines += ["", "## 最近换仓记录", ""]
        cols = ["trade_date", "etf_code", "etf_name", "theme", "style", "side", "price", "shares", "value", "fee"]
        lines += [_to_markdown(result.trades.tail(20)[cols])]
    if not result.positions.empty:
        last_date = result.positions["trade_date"].max()
        latest_pos = result.positions[result.positions["trade_date"].eq(last_date)].copy()
        lines += ["", "## 最新持仓", "", _to_markdown(latest_pos[["trade_date", "etf_code", "etf_name", "theme", "style", "shares", "close", "weight"]])]
    if not holding_pnl.empty:
        lines += ["", "## 当前持仓盈亏", "", _to_markdown(holding_pnl)]
    if not closed_pnl.empty:
        lines += ["", "## 已平仓盈亏复查", "", _to_markdown(closed_pnl.tail(20))]
    lines += [
        "",
        "## 数据问题提示",
        "",
        "- 基本面数据问题会写入 `fundamental_data_issues.csv`。",
        "- 融资余额和利率数据问题会写入 `market_data_issues.csv`。",
        "- 如果某个ETF缺少成分映射，会回退到手工配置的股息率和基本面分数。",
    ]
    return "\n".join(lines)


def _factor_table(factors: dict) -> str:
    rows = [{"因子": k, "权重": v} for k, v in factors.items()]
    return _to_markdown(pd.DataFrame(rows))


def _dict_table(d: dict) -> str:
    return _to_markdown(pd.DataFrame([{"市场状态": k, **v} for k, v in d.items()]))


def _fmt_pct(value) -> str:
    try:
        if pd.isna(value):
            return ""
        return f"{float(value):.2%}"
    except Exception:
        return ""


def _to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].map(lambda x: f"{x:.4f}" if pd.notna(x) else "")
    out = out.fillna("").astype(str)
    header = "| " + " | ".join(out.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(out.columns)) + " |"
    rows = ["| " + " | ".join(row) + " |" for row in out.to_numpy()]
    return "\n".join([header, sep] + rows)


def _pnl_reports(result: BacktestResult) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades = result.trades.copy()
    if trades.empty:
        return pd.DataFrame(), pd.DataFrame()
    trades["trade_date"] = pd.to_datetime(trades["trade_date"])
    lots: dict[str, list[dict]] = {}
    closed_rows = []
    for _, tr in trades.sort_values("trade_date").iterrows():
        code = tr["etf_code"]
        if tr["side"] == "BUY":
            lots.setdefault(code, []).append(
                {
                    "shares": float(tr["shares"]),
                    "cost": float(tr["value"]) + float(tr["fee"]),
                    "buy_date": tr["trade_date"],
                    "etf_name": tr.get("etf_name", code),
                    "theme": tr.get("theme", ""),
                    "style": tr.get("style", ""),
                }
            )
            continue
        qty_left = float(tr["shares"])
        proceeds_total = float(tr["value"]) - float(tr["fee"])
        while qty_left > 1e-8 and lots.get(code):
            lot = lots[code][0]
            qty = min(qty_left, lot["shares"])
            cost = lot["cost"] * qty / lot["shares"]
            proceeds = proceeds_total * qty / float(tr["shares"]) if float(tr["shares"]) else 0.0
            pnl = proceeds - cost
            closed_rows.append(
                {
                    "sell_date": tr["trade_date"],
                    "buy_date": lot["buy_date"],
                    "etf_code": code,
                    "etf_name": tr.get("etf_name", lot.get("etf_name", code)),
                    "theme": tr.get("theme", lot.get("theme", "")),
                    "style": tr.get("style", lot.get("style", "")),
                    "shares": qty,
                    "sell_price": float(tr["price"]),
                    "cost": cost,
                    "proceeds": proceeds,
                    "pnl": pnl,
                    "pnl_pct": pnl / cost if cost else 0.0,
                    "holding_days": (tr["trade_date"] - lot["buy_date"]).days,
                    "exit_type": "take_profit" if pnl > 0 else "stop_loss_or_rebalance",
                }
            )
            lot["shares"] -= qty
            lot["cost"] -= cost
            qty_left -= qty
            if lot["shares"] <= 1e-8:
                lots[code].pop(0)

    latest_pos = result.positions.copy()
    if latest_pos.empty:
        return pd.DataFrame(), pd.DataFrame(closed_rows)
    latest_pos["trade_date"] = pd.to_datetime(latest_pos["trade_date"])
    latest_date = latest_pos["trade_date"].max()
    latest_pos = latest_pos[(latest_pos["trade_date"].eq(latest_date)) & (~latest_pos["etf_code"].eq("CASH"))]
    holding_rows = []
    for _, pos in latest_pos.iterrows():
        code = pos["etf_code"]
        remaining_cost = sum(lot["cost"] for lot in lots.get(code, []))
        market_value = float(pos["shares"]) * float(pos["close"])
        pnl = market_value - remaining_cost
        holding_rows.append(
            {
                "trade_date": latest_date,
                "etf_code": code,
                "etf_name": pos.get("etf_name", code),
                "theme": pos.get("theme", ""),
                "style": pos.get("style", ""),
                "shares": float(pos["shares"]),
                "close": float(pos["close"]),
                "cost": remaining_cost,
                "market_value": market_value,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl / remaining_cost if remaining_cost else 0.0,
                "weight": float(pos["weight"]),
            }
        )
    return pd.DataFrame(holding_rows), pd.DataFrame(closed_rows)
