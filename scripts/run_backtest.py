from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest import run_backtest
from src.data import DataClient
from src.report import save_outputs
from src.universe import load_universe
from src.utils import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 A 股行业 ETF 轮动 v0.1 回测。")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存，重新请求 Tushare。")
    args = parser.parse_args()

    config = load_config(args.config)
    universe = load_universe(config)
    data_cfg = config.get("data", {})
    start = data_cfg.get("start_date", "20210101")
    end = data_cfg.get("end_date")
    client = DataClient(config, refresh=args.refresh)

    price_data = {}
    for _, row in universe.iterrows():
        df = client.get_etf_daily(row["etf_code"], start, end)
        if df.empty:
            print(f"[WARN] {row['etf_code']} {row['etf_name']} 无可用日线，自动跳过。")
            continue
        price_data[row["etf_code"]] = df

    benchmark = client.get_index_daily(data_cfg.get("market_index_code", "000300.SH"), start, end)
    result = run_backtest(price_data, universe, benchmark, config)
    save_outputs(result, config)
    print("回测完成，结果已输出到 outputs/。")


if __name__ == "__main__":
    main()
