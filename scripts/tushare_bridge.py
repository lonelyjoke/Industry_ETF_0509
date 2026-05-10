from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import sys
import time

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import DataClient
from src.universe import load_universe
from src.utils import ensure_dir, load_config


HOST = "127.0.0.1"
PORT = 8765


class BridgeState:
    config = load_config("config.yaml")
    universe = load_universe(config)
    local_dir = ensure_dir(config.get("data", {}).get("local_csv_dir", "data/local_csv"))
    last_result: dict = {"status": "idle"}


def _json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def fetch_etf_daily_all(refresh: bool = False, sleep_seconds: float = 0.4) -> dict:
    cfg = BridgeState.config
    data_cfg = cfg.get("data", {})
    start = data_cfg.get("start_date", "20210101")
    end = data_cfg.get("end_date")
    client = DataClient(cfg, refresh=True)

    rows = []
    for _, etf in BridgeState.universe.iterrows():
        code = etf["etf_code"]
        name = etf["etf_name"]
        path = BridgeState.local_dir / f"etf_daily_{code}.csv"
        if path.exists() and not refresh:
            cached = pd.read_csv(path)
            rows.append({"etf_code": code, "etf_name": name, "status": "cache", "rows": len(cached), "path": str(path)})
            continue
        try:
            df = client.cached_call("fund_daily", {"ts_code": code, "start_date": start, "end_date": end})
            if df.empty:
                rows.append({"etf_code": code, "etf_name": name, "status": "empty", "rows": 0, "path": str(path)})
            else:
                df.to_csv(path, index=False, encoding="utf-8-sig")
                rows.append({"etf_code": code, "etf_name": name, "status": "ok", "rows": len(df), "path": str(path)})
        except Exception as exc:
            rows.append({"etf_code": code, "etf_name": name, "status": "failed", "rows": 0, "path": str(path), "error": str(exc)})
        time.sleep(max(sleep_seconds, 0.0))

    manifest = pd.DataFrame(rows)
    manifest_path = BridgeState.local_dir / "fetch_etf_daily_manifest.csv"
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    summary = {
        "status": "done",
        "ok": int((manifest["status"] == "ok").sum()) if not manifest.empty else 0,
        "cache": int((manifest["status"] == "cache").sum()) if not manifest.empty else 0,
        "failed": int((manifest["status"] == "failed").sum()) if not manifest.empty else 0,
        "empty": int((manifest["status"] == "empty").sum()) if not manifest.empty else 0,
        "manifest": str(manifest_path),
        "rows": rows,
    }
    BridgeState.last_result = summary
    return summary


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/health":
            _json(self, {"status": "ok", "service": "tushare_bridge", "local_dir": str(BridgeState.local_dir)})
            return
        if parsed.path == "/status":
            _json(self, BridgeState.last_result)
            return
        if parsed.path == "/fetch_etf_daily":
            refresh = params.get("refresh", ["0"])[0] in {"1", "true", "yes"}
            sleep_seconds = float(params.get("sleep", ["0.4"])[0])
            result = fetch_etf_daily_all(refresh=refresh, sleep_seconds=sleep_seconds)
            _json(self, result)
            return
        _json(self, {"error": "not_found", "paths": ["/health", "/status", "/fetch_etf_daily"]}, status=404)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Tushare bridge listening on http://{HOST}:{PORT}")
    print("Keep this window open while Codex fetches data.")
    server.serve_forever()


if __name__ == "__main__":
    main()
