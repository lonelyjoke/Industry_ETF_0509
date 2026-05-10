from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_tushare_token(required: bool = True) -> str | None:
    token = os.environ.get("TUSHARE_TOKEN")
    if required and not token:
        raise RuntimeError("未读取到 TUSHARE_TOKEN。请先设置环境变量，例如 PowerShell: $env:TUSHARE_TOKEN='你的token'")
    return token


def normalize_trade_date(df: pd.DataFrame, column: str = "trade_date") -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return df
    out = df.copy()
    out[column] = pd.to_datetime(out[column].astype(str))
    return out.sort_values(column).reset_index(drop=True)


def safe_zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def winsorize(s: pd.Series, lower: float = 0.05, upper: float = 0.95) -> pd.Series:
    if s.dropna().empty:
        return s
    return s.clip(s.quantile(lower), s.quantile(upper))


def annualize_return(total_return: float, periods: int, periods_per_year: int = 252) -> float:
    if periods <= 0:
        return 0.0
    return (1 + total_return) ** (periods_per_year / periods) - 1
