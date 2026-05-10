from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import DataClient
from src.universe import load_universe
from src.utils import ensure_dir, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="逐只预取 ETF 日线数据，支持本地缓存和断点续跑。")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--refresh", action="store_true", help="忽略已有逐只缓存，重新请求。")
    parser.add_argument("--sleep", type=float, default=0.4, help="每只 ETF 请求后的等待秒数，降低触发频控概率。")
    args = parser.parse_args()

    config = load_config(args.config)
    universe = load_universe(config)
    data_cfg = config.get("data", {})
    start = data_cfg.get("start_date", "20210101")
    end = data_cfg.get("end_date")
    local_dir = ensure_dir(data_cfg.get("local_csv_dir", "data/local_csv"))
    client = DataClient(config, refresh=True)

    rows = []
    print("逐只 ETF 日线预取开始")
    print("=" * 72)
    for _, etf in universe.iterrows():
        code = etf["etf_code"]
        name = etf["etf_name"]
        path = local_dir / f"etf_daily_{code}.csv"
        if path.exists() and not args.refresh:
            cached = pd.read_csv(path)
            print(f"[CACHE] {code} {name}: 已存在 {len(cached)} 行，跳过。")
            rows.append({"etf_code": code, "etf_name": name, "status": "cache", "rows": len(cached), "path": str(path)})
            continue

        try:
            df = client.cached_call("fund_daily", {"ts_code": code, "start_date": start, "end_date": end})
            if df.empty:
                print(f"[EMPTY] {code} {name}: 返回空数据。")
                rows.append({"etf_code": code, "etf_name": name, "status": "empty", "rows": 0, "path": str(path)})
            else:
                df.to_csv(path, index=False, encoding="utf-8-sig")
                print(f"[OK] {code} {name}: {len(df)} 行 -> {path}")
                rows.append({"etf_code": code, "etf_name": name, "status": "ok", "rows": len(df), "path": str(path)})
        except Exception as exc:
            print(f"[FAIL] {code} {name}: {exc}")
            rows.append({"etf_code": code, "etf_name": name, "status": "failed", "rows": 0, "path": str(path), "error": str(exc)})
        time.sleep(max(args.sleep, 0.0))

    manifest = pd.DataFrame(rows)
    manifest_path = local_dir / "fetch_etf_daily_manifest.csv"
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    print("=" * 72)
    print(f"完成。清单已写入: {manifest_path}")
    print("下次不加 --refresh 会自动跳过已成功缓存的 ETF。")


if __name__ == "__main__":
    main()
