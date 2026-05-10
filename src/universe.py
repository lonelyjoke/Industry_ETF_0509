from __future__ import annotations

import pandas as pd


def load_universe(config: dict) -> pd.DataFrame:
    rows = config.get("etf_universe", [])
    if not rows:
        raise ValueError("config.yaml 中 etf_universe 为空。")
    df = pd.DataFrame(rows)
    required = {"etf_code", "etf_name", "theme"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"ETF 池缺少字段: {sorted(missing)}")
    return df
