from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.access_check import check_tushare_access, summarize_access
from src.utils import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="检测当前 Tushare token 的低权限可用接口，并缓存样例数据。")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存，重新请求 Tushare。")
    args = parser.parse_args()

    config = load_config(args.config)
    try:
        results = check_tushare_access(config, refresh=args.refresh)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)

    print("\nTushare 权限检测结果")
    print("=" * 72)
    for r in results:
        status = "OK" if r.ok else "降级"
        print(f"[{status}] {r.name}: {r.message}")
        if (not r.ok) and r.degraded_to:
            print(f"      -> {r.degraded_to}")

    summary = summarize_access(results)
    print("\n自动降级建议")
    print("=" * 72)
    print(f"历史60分钟模块: {'启用' if summary['intraday_enabled'] else '关闭，使用纯日线轮动'}")
    print(f"实时/当日60分钟数据: {'可用' if summary.get('realtime_intraday_available') else '不可用'}")
    print(f"基本面模块: {'尝试启用' if summary['fundamental_enabled'] else '关闭或仅使用手工评分'}")
    print(f"ETF日线: {'Tushare可用' if summary['etf_daily_available'] else '请使用 data/local_csv 本地CSV'}")


if __name__ == "__main__":
    main()
