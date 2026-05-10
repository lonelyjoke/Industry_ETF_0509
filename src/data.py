from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import ensure_dir, get_tushare_token, normalize_trade_date


class DataClient:
    """Tushare wrapper with local CSV cache and graceful local-data fallback."""

    def __init__(self, config: dict, refresh: bool = False):
        self.config = config
        self.refresh = refresh
        self.cache_dir = ensure_dir(config.get("data", {}).get("cache_dir", "data"))
        self.local_csv_dir = ensure_dir(config.get("data", {}).get("local_csv_dir", "data/local_csv"))
        self._pro = None
        self.last_source = ""

    def pro(self):
        if self._pro is None:
            token = get_tushare_token(required=True)
            proxy_url = os.environ.get("TUSHARE_PROXY_URL") or self.config.get("data", {}).get("proxy_url")
            if proxy_url:
                os.environ.setdefault("HTTP_PROXY", proxy_url)
                os.environ.setdefault("HTTPS_PROXY", proxy_url)
            try:
                import tushare as ts
            except ImportError as exc:
                raise RuntimeError("未安装 tushare，请先 pip install -r requirements.txt") from exc
            timeout = int(self.config.get("data", {}).get("tushare_timeout", 30))
            self._pro = ts.pro_api(token, timeout=timeout)
            api_url = os.environ.get("TUSHARE_API_URL") or self.config.get("data", {}).get("tushare_api_url")
            if api_url and hasattr(self._pro, "_DataApi__http_url"):
                # Tushare 1.4.x keeps the endpoint as a private attribute. Making it
                # configurable helps in environments where plain HTTP port 80 is blocked.
                setattr(self._pro, "_DataApi__http_url", api_url.rstrip("/"))
        return self._pro

    def _cache_path(self, name: str, params: dict[str, Any]) -> Path:
        clean = {k: v for k, v in params.items() if v is not None}
        digest = hashlib.md5(repr(sorted(clean.items())).encode("utf-8")).hexdigest()[:10]
        return self.cache_dir / f"{name}_{digest}.csv"

    def cached_call(self, name: str, params: dict[str, Any]) -> pd.DataFrame:
        path = self._cache_path(name, params)
        if path.exists() and not self.refresh:
            self.last_source = f"cache:{path.name}"
            return pd.read_csv(path)
        func = getattr(self.pro(), name)
        df = func(**params)
        df.to_csv(path, index=False, encoding="utf-8-sig")
        self.last_source = f"api:{path.name}"
        return df

    def _local_csv(self, code: str, kind: str) -> pd.DataFrame:
        candidates = [
            self.local_csv_dir / f"{kind}_{code}.csv",
            self.local_csv_dir / f"{code}.csv",
            self.cache_dir / f"{kind}_{code}.csv",
        ]
        for path in candidates:
            if path.exists():
                return pd.read_csv(path)
        return pd.DataFrame()

    def get_etf_daily(self, ts_code: str, start_date: str, end_date: str | None = None) -> pd.DataFrame:
        local = self._local_csv(ts_code, "etf_daily")
        if not local.empty and not self.refresh:
            return self._apply_amount_unit(self.normalize_ohlcv(local))
        try:
            df = self.cached_call("fund_daily", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date})
        except Exception as exc:
            if not local.empty:
                return self._apply_amount_unit(self.normalize_ohlcv(local))
            print(f"[WARN] ETF 日线 {ts_code} 获取失败，已跳过: {exc}")
            return pd.DataFrame()
        return self._apply_amount_unit(self.normalize_ohlcv(df))

    def get_index_daily(self, ts_code: str, start_date: str, end_date: str | None = None) -> pd.DataFrame:
        try:
            df = self.cached_call("index_daily", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date})
        except Exception as exc:
            print(f"[WARN] 指数日线 {ts_code} 获取失败: {exc}")
            return pd.DataFrame()
        return self.normalize_ohlcv(df)

    def get_fund_minute(self, ts_code: str, start_date: str, end_date: str | None = None, freq: str = "60min") -> pd.DataFrame:
        local = self._local_csv(ts_code, f"fund_{freq}")
        if not local.empty and not self.refresh:
            return local
        try:
            df = self.cached_call("fund_minute", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date, "freq": freq})
        except Exception as exc:
            print(f"[WARN] 60分钟数据 {ts_code} 不可用，自动关闭对应过滤: {exc}")
            return pd.DataFrame()
        return df

    def get_daily_basic(self, ts_code: str = "", trade_date: str | None = None) -> pd.DataFrame:
        try:
            return self.cached_call("daily_basic", {"ts_code": ts_code, "trade_date": trade_date})
        except Exception as exc:
            print(f"[WARN] daily_basic 不可用: {exc}")
            return pd.DataFrame()

    def _apply_amount_unit(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "amount" not in df.columns:
            return df
        out = df.copy()
        unit = self.config.get("data", {}).get("amount_unit", "thousand_yuan")
        if unit == "thousand_yuan":
            out["amount"] = out["amount"] * 1000.0
        elif unit == "yuan":
            out["amount"] = out["amount"].astype(float)
        else:
            raise ValueError("data.amount_unit 只能是 'thousand_yuan' 或 'yuan'")
        return out

    @staticmethod
    def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        out = normalize_trade_date(df)
        rename = {"vol": "volume", "amount": "amount"}
        out = out.rename(columns=rename)
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out.dropna(subset=["trade_date", "close"]).sort_values("trade_date").reset_index(drop=True)
