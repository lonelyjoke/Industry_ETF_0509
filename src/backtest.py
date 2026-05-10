from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .features_daily import add_daily_features, biweekly_signal_dates, weekly_signal_dates
from .features_fundamental import compute_fundamental_scores
from .market_features import compute_market_context
from .strategy import build_weekly_ranking


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    weekly_ranking: pd.DataFrame
    fundamental_scores: pd.DataFrame
    combined_scores: pd.DataFrame
    benchmark: pd.DataFrame


def prepare_features(price_data: dict[str, pd.DataFrame], universe: pd.DataFrame, config: dict) -> pd.DataFrame:
    frames = []
    meta = universe.set_index("etf_code").to_dict("index")
    for code, df in price_data.items():
        if df.empty:
            continue
        feat = add_daily_features(df, config)
        feat["etf_code"] = code
        feat["etf_name"] = meta.get(code, {}).get("etf_name", code)
        feat["theme"] = meta.get(code, {}).get("theme", "")
        feat["style"] = meta.get(code, {}).get("style", "value")
        frames.append(feat)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _execution_dates(all_dates: list[pd.Timestamp], signal_dates: list[pd.Timestamp]) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(all_dates))
    mapping = {}
    for sig in signal_dates:
        later = [d for d in dates if d > sig]
        if later:
            mapping[pd.Timestamp(sig)] = later[0]
    return mapping


def run_backtest(price_data: dict[str, pd.DataFrame], universe: pd.DataFrame, benchmark: pd.DataFrame, config: dict) -> BacktestResult:
    panel = prepare_features(price_data, universe, config)
    if panel.empty:
        raise RuntimeError("没有可用 ETF 日线数据。请检查 Tushare 权限或 data/local_csv 本地CSV。")
    bench_feat = add_daily_features(benchmark, config) if not benchmark.empty else pd.DataFrame()
    if not bench_feat.empty and "ret_60" in bench_feat.columns:
        bench_ret = bench_feat[["trade_date", "ret_60", "ret_120"]].rename(columns={"ret_60": "benchmark_ret_60", "ret_120": "benchmark_ret_120"})
        panel = panel.merge(bench_ret, on="trade_date", how="left")
        panel["relative_ret_60"] = panel["ret_60"] - panel["benchmark_ret_60"]
        panel["relative_ret_120"] = panel["ret_120"] - panel["benchmark_ret_120"]
    all_dates = sorted(panel["trade_date"].drop_duplicates())
    if config["backtest"].get("rebalance_frequency", "weekly") == "biweekly":
        signal_dates = biweekly_signal_dates(pd.Series(all_dates))
    else:
        signal_dates = weekly_signal_dates(pd.Series(all_dates))
    exec_map = _execution_dates(all_dates, signal_dates)
    fundamental = compute_fundamental_scores(config, signal_dates)
    market_context = compute_market_context(config, signal_dates, bench_feat)

    initial_cash = float(config["backtest"].get("initial_cash", 1_000_000))
    commission = float(config["backtest"].get("commission_rate", 0.0003))
    slippage = float(config["backtest"].get("slippage", 0.0))
    execution_price = config["backtest"].get("execution_price", "close")
    min_trade_value = float(config["strategy"].get("min_trade_value", 1000))
    rebalance_tolerance = float(config["strategy"].get("rebalance_tolerance", 0.02))

    cash = initial_cash
    shares: dict[str, float] = {}
    equity_rows, trade_rows, pos_rows, rank_rows = [], [], [], []
    current_weights: dict[str, float] = {}
    meta = universe.set_index("etf_code").to_dict("index")

    price_pivot = panel.pivot(index="trade_date", columns="etf_code", values="close")
    valuation_pivot = price_pivot.ffill()
    open_pivot = panel.pivot(index="trade_date", columns="etf_code", values="open")

    for dt in all_dates:
        dt = pd.Timestamp(dt)
        prices = valuation_pivot.loc[dt].dropna()
        holdings_value = sum(shares.get(c, 0.0) * prices.get(c, np.nan) for c in shares)
        holdings_value = 0.0 if pd.isna(holdings_value) else holdings_value
        equity = cash + holdings_value

        signal_for_today = [sig for sig, ex in exec_map.items() if ex == dt]
        if signal_for_today:
            sig = signal_for_today[0]
            snap = panel[panel["trade_date"] == sig].copy()
            bench_row = None
            if not bench_feat.empty:
                b = bench_feat[bench_feat["trade_date"] == sig]
                bench_row = b.iloc[0] if not b.empty else None
            f = fundamental[fundamental["trade_date"] == sig] if not fundamental.empty else pd.DataFrame()
            mc = pd.Series(dtype=object)
            if not market_context.empty:
                mrow = market_context[market_context["trade_date"] == sig]
                mc = mrow.iloc[0] if not mrow.empty else pd.Series(dtype=object)
            ranking = build_weekly_ranking(snap, f, bench_row, config, current_holdings=set(shares.keys()), market_context=mc)
            if not ranking.empty:
                ranking["signal_date"] = sig
                ranking["execution_date"] = dt
                rank_rows.append(ranking)
                current_weights = dict(zip(ranking.loc[ranking["selected"], "etf_code"], ranking.loc[ranking["selected"], "target_weight"]))

                exec_prices = (open_pivot if execution_price == "open" else price_pivot).loc[dt].dropna()
                target_values = {code: equity * w for code, w in current_weights.items()}
                for code in list(shares):
                    if code not in target_values:
                        px = exec_prices.get(code, np.nan)
                        if pd.notna(px) and shares[code] > 0:
                            value = shares[code] * px * (1 - slippage)
                            fee = value * commission
                            cash += value - fee
                            info = meta.get(code, {})
                            trade_rows.append({
                                "trade_date": dt,
                                "etf_code": code,
                                "etf_name": info.get("etf_name", code),
                                "theme": info.get("theme", ""),
                                "style": info.get("style", ""),
                                "side": "SELL",
                                "price": px,
                                "shares": shares[code],
                                "value": value,
                                "fee": fee,
                            })
                        shares.pop(code, None)
                for code, target in target_values.items():
                    px = exec_prices.get(code, np.nan)
                    if pd.isna(px) or px <= 0:
                        continue
                    current_value = shares.get(code, 0.0) * px
                    diff = target - current_value
                    if abs(diff) < min_trade_value or (equity and abs(diff) / equity < rebalance_tolerance):
                        continue
                    if diff > 0:
                        if cash < min_trade_value:
                            continue
                        buy_value = min(diff, cash) * (1 - commission)
                        qty = buy_value / (px * (1 + slippage))
                        fee = buy_value * commission
                        cash -= buy_value + fee
                        shares[code] = shares.get(code, 0.0) + qty
                        info = meta.get(code, {})
                        trade_rows.append({
                            "trade_date": dt,
                            "etf_code": code,
                            "etf_name": info.get("etf_name", code),
                            "theme": info.get("theme", ""),
                            "style": info.get("style", ""),
                            "side": "BUY",
                            "price": px,
                            "shares": qty,
                            "value": buy_value,
                            "fee": fee,
                        })
                    else:
                        qty = min(shares.get(code, 0.0), abs(diff) / px)
                        value = qty * px * (1 - slippage)
                        if value < min_trade_value:
                            continue
                        fee = value * commission
                        cash += value - fee
                        shares[code] = shares.get(code, 0.0) - qty
                        info = meta.get(code, {})
                        trade_rows.append({
                            "trade_date": dt,
                            "etf_code": code,
                            "etf_name": info.get("etf_name", code),
                            "theme": info.get("theme", ""),
                            "style": info.get("style", ""),
                            "side": "SELL",
                            "price": px,
                            "shares": qty,
                            "value": value,
                            "fee": fee,
                        })

        prices = valuation_pivot.loc[dt].dropna()
        holdings_value = sum(shares.get(c, 0.0) * prices.get(c, np.nan) for c in shares)
        holdings_value = 0.0 if pd.isna(holdings_value) else holdings_value
        equity = cash + holdings_value
        equity_rows.append({"trade_date": dt, "equity": equity, "cash": cash, "holding_value": holdings_value})
        total_weight = 0.0
        for code, qty in shares.items():
            px = prices.get(code, np.nan)
            if pd.notna(px):
                w = qty * px / equity if equity else 0.0
                total_weight += w
                info = meta.get(code, {})
                pos_rows.append({
                    "trade_date": dt,
                    "etf_code": code,
                    "etf_name": info.get("etf_name", code),
                    "theme": info.get("theme", ""),
                    "style": info.get("style", ""),
                    "shares": qty,
                    "close": px,
                    "weight": w,
                })
        if not shares:
            pos_rows.append({"trade_date": dt, "etf_code": "CASH", "etf_name": "现金", "theme": "现金", "style": "cash", "shares": 0, "close": 1, "weight": 1.0})

    weekly = pd.concat(rank_rows, ignore_index=True) if rank_rows else pd.DataFrame()
    return BacktestResult(
        equity_curve=pd.DataFrame(equity_rows),
        trades=pd.DataFrame(trade_rows),
        positions=pd.DataFrame(pos_rows),
        weekly_ranking=weekly,
        fundamental_scores=fundamental,
        combined_scores=weekly.copy(),
        benchmark=bench_feat,
    )
