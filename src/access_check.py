from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .data import DataClient
from .utils import get_tushare_token


@dataclass
class AccessResult:
    name: str
    ok: bool
    degraded_to: str
    message: str


def _try_call(name: str, fn: Callable[[], pd.DataFrame], degraded_to: str = "", source_fn: Callable[[], str] | None = None) -> AccessResult:
    try:
        df = fn()
        source = source_fn() if source_fn else ""
        source_msg = f"来源 {source}，" if source else ""
        if df is None or df.empty:
            return AccessResult(name, False, degraded_to, f"{source_msg}接口可调用但返回空数据，可能是权限、参数或日期原因。")
        cache_note = "已写入本地缓存" if source.startswith("api:") else "读取本地缓存"
        return AccessResult(name, True, "", f"成功，{source_msg}样例 {len(df)} 行，{cache_note}。")
    except Exception as exc:
        return AccessResult(name, False, degraded_to, f"不可用: {exc}")


def check_tushare_access(config: dict, refresh: bool = False) -> list[AccessResult]:
    get_tushare_token(required=True)
    client = DataClient(config, refresh=refresh)
    start = "20240101"
    end = None
    sample_etf = config["etf_universe"][0]["etf_code"]
    sample_industry = next((x.get("sw_industry_code") for x in config["etf_universe"] if x.get("sw_industry_code")), "801780.SI")

    checks = [
        ("ETF 日线数据 fund_daily", lambda: client.cached_call("fund_daily", {"ts_code": sample_etf, "start_date": start, "end_date": end}), "使用 data/local_csv 本地 ETF 日线"),
        ("ETF 历史60分钟K线 fund_minute", lambda: client.cached_call("fund_minute", {"ts_code": sample_etf, "start_date": start, "end_date": end, "freq": "60min"}), "关闭60分钟模块，使用纯日线轮动"),
        ("ETF 实时或当日60分钟数据 stk_mins", lambda: client.cached_call("stk_mins", {"ts_code": sample_etf, "freq": "60min"}), "关闭实时/当日60分钟过滤"),
        ("指数日线 index_daily", lambda: client.cached_call("index_daily", {"ts_code": "000300.SH", "start_date": start, "end_date": end}), "使用ETF池市场宽度替代市场环境"),
        ("ETF列表或基金基础 fund_basic", lambda: client.cached_call("fund_basic", {"market": "E", "status": "L"}), "使用 config.yaml 手工ETF池"),
        ("daily_basic", lambda: client.cached_call("daily_basic", {"ts_code": "000001.SZ", "start_date": start, "end_date": end}), "关闭估值接口相关增强"),
        ("index_weight", lambda: client.cached_call("index_weight", {"index_code": "000300.SH", "start_date": start, "end_date": end}), "使用行业映射或手工基本面评分"),
        ("fina_indicator", lambda: client.cached_call("fina_indicator", {"ts_code": "000001.SZ", "start_date": "20230101", "end_date": end}), "关闭ROE、利润增速等财务因子"),
        ("express", lambda: client.cached_call("express", {"ts_code": "000001.SZ", "start_date": "20230101", "end_date": end}), "关闭业绩快报因子"),
        ("申万行业分类/成分 index_member", lambda: client.cached_call("index_member", {"index_code": sample_industry}), "使用 config.yaml 手工行业映射"),
    ]
    return [_try_call(name, fn, fallback, lambda client=client: client.last_source) for name, fn, fallback in checks]


def summarize_access(results: list[AccessResult]) -> dict:
    historical_intraday_ok = any(r.ok for r in results if "历史60分钟" in r.name)
    realtime_intraday_ok = any(r.ok for r in results if "实时或当日60分钟" in r.name)
    fundamental_ok = any(r.ok for r in results if r.name in {"index_weight", "fina_indicator", "express", "daily_basic"})
    etf_daily_ok = any(r.ok for r in results if r.name.startswith("ETF 日线"))
    return {
        "intraday_enabled": historical_intraday_ok,
        "realtime_intraday_available": realtime_intraday_ok,
        "fundamental_enabled": fundamental_ok,
        "etf_daily_available": etf_daily_ok,
    }
