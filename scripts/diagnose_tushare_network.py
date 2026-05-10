from __future__ import annotations

import os
import socket
from urllib.parse import urlparse


def socket_check(host: str, port: int, timeout: float = 8.0) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "OK"
    except Exception as exc:
        return f"FAILED: {type(exc).__name__}: {exc}"


def main() -> None:
    api_url = os.environ.get("TUSHARE_API_URL", "https://api.waditu.com/dataapi")
    parsed = urlparse(api_url)
    host = parsed.hostname or "api.waditu.com"
    token_set = bool(os.environ.get("TUSHARE_TOKEN"))

    print("Network diagnostics")
    print("=" * 60)
    print(f"TUSHARE_TOKEN set: {token_set}")
    print(f"TUSHARE_API_URL: {api_url}")
    print(f"Host: {host}")
    print(f"DNS lookup: ", end="")
    try:
        print(socket.gethostbyname(host))
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
    print(f"Socket {host}:80  -> {socket_check(host, 80)}")
    print(f"Socket {host}:443 -> {socket_check(host, 443)}")
    print("=" * 60)
    if not token_set:
        print("TUSHARE_TOKEN is missing. Set it before running the permission check.")


if __name__ == "__main__":
    main()
