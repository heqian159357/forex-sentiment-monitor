"""Concurrent multi-source news fetcher.

Exit codes:
  0 = all sources OK
  1 = partial failure (at least one source OK)
  2 = all sources failed
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from scripts.config import load_config
from scripts.clients.alpha_vantage import fetch_alpha_vantage
from scripts.clients.finnhub import fetch_finnhub
from scripts.clients.newsapi import fetch_newsapi
from scripts.clients.gdelt import fetch_gdelt, DEFAULT_QUERY as GDELT_QUERY
from scripts.clients.rss import fetch_rss
from scripts.clients.cryptopanic import fetch_cryptopanic


NEWSAPI_QUERY = "forex OR gold OR silver OR bitcoin OR ethereum OR \"crude oil\" OR OPEC"
ALPHA_VANTAGE_TOPICS = ["financial_markets", "economy_monetary", "economy_macro", "blockchain"]
FINNHUB_CATEGORIES = ["general", "crypto", "forex"]

# 默认启用的全部源（含无需 key 的免费源）
ALL_SOURCES = ["alpha_vantage", "finnhub", "newsapi", "gdelt", "rss", "cryptopanic"]
# 无需 API key 的免费源（即使 .env 是占位也能用）
KEYLESS_SOURCES = ["gdelt", "rss"]


async def _run_with_retry(fn, retry: int) -> dict:
    last = None
    for _ in range(retry + 1):
        r = await fn()
        if r.get("ok"):
            return r
        last = r
        if r.get("rate_limit_hit"):
            await asyncio.sleep(2)
    return last or {"ok": False, "count": 0, "error": "retry exhausted", "articles": []}


async def run_fetch(
    *,
    config: dict,
    hours: int,
    symbols: list[str],
    output_path: Path,
    enabled_sources: list[str],
) -> int:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    av_since = since.strftime("%Y%m%dT%H%M")  # AV requires YYYYMMDDTHHMM (12 digits, no seconds)
    iso_since = since.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    epoch_since = int(since.timestamp())

    tasks = []
    order = []
    srcs = config["sources"]
    keys = config["api_keys"]

    if "alpha_vantage" in enabled_sources and srcs["alpha_vantage"]["enabled"]:
        tasks.append(_run_with_retry(
            lambda: fetch_alpha_vantage(
                api_key=keys["alpha_vantage"],
                since_iso=av_since,
                topics=ALPHA_VANTAGE_TOPICS,
                timeout=srcs["alpha_vantage"]["timeout_seconds"],
            ),
            srcs["alpha_vantage"]["retry"],
        ))
        order.append("alpha_vantage")

    if "finnhub" in enabled_sources and srcs["finnhub"]["enabled"]:
        tasks.append(_run_with_retry(
            lambda: fetch_finnhub(
                api_key=keys["finnhub"],
                since_epoch=epoch_since,
                categories=FINNHUB_CATEGORIES,
                timeout=srcs["finnhub"]["timeout_seconds"],
            ),
            srcs["finnhub"]["retry"],
        ))
        order.append("finnhub")

    if "newsapi" in enabled_sources and srcs["newsapi"]["enabled"]:
        tasks.append(_run_with_retry(
            lambda: fetch_newsapi(
                api_key=keys["newsapi"],
                since_iso=iso_since,
                query=NEWSAPI_QUERY,
                timeout=srcs["newsapi"]["timeout_seconds"],
            ),
            srcs["newsapi"]["retry"],
        ))
        order.append("newsapi")

    # ---- 免费源（无需 API key）----
    gdelt_cfg = srcs.get("gdelt", {"enabled": True, "timeout_seconds": 15, "retry": 1})
    if "gdelt" in enabled_sources and gdelt_cfg.get("enabled", True):
        tasks.append(_run_with_retry(
            lambda: fetch_gdelt(
                query=GDELT_QUERY,
                hours=hours,
                timeout=gdelt_cfg.get("timeout_seconds", 15),
            ),
            gdelt_cfg.get("retry", 1),
        ))
        order.append("gdelt")

    rss_cfg = srcs.get("rss", {"enabled": True, "timeout_seconds": 12, "retry": 1})
    if "rss" in enabled_sources and rss_cfg.get("enabled", True):
        tasks.append(_run_with_retry(
            lambda: fetch_rss(
                feeds=rss_cfg.get("feeds"),
                since_epoch=epoch_since,
                timeout=rss_cfg.get("timeout_seconds", 12),
            ),
            rss_cfg.get("retry", 1),
        ))
        order.append("rss")

    # CryptoPanic：可选源，无 token 时 client 自动返回 ok=False 并跳过
    cp_cfg = srcs.get("cryptopanic", {"enabled": True, "timeout_seconds": 10, "retry": 1})
    if "cryptopanic" in enabled_sources and cp_cfg.get("enabled", True) and keys.get("cryptopanic"):
        tasks.append(_run_with_retry(
            lambda: fetch_cryptopanic(
                api_key=keys["cryptopanic"],
                since_epoch=epoch_since,
                timeout=cp_cfg.get("timeout_seconds", 10),
            ),
            cp_cfg.get("retry", 1),
        ))
        order.append("cryptopanic")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    sources_status: dict[str, Any] = {}
    articles: list[dict] = []
    all_failed = True
    for name, res in zip(order, results):
        if isinstance(res, Exception):
            sources_status[name] = {"ok": False, "count": 0, "error": str(res)}
            continue
        sources_status[name] = {
            "ok": res["ok"],
            "count": res["count"],
            "rate_limit_hit": res.get("rate_limit_hit", False),
            "error": res.get("error"),
        }
        if res["ok"]:
            all_failed = False
            articles.extend(res["articles"])

    if symbols:
        sym_set = set(symbols)
        filtered = []
        for a in articles:
            if not a.get("tickers") or sym_set.intersection(a["tickers"]):
                filtered.append(a)
        articles = filtered

    payload = {
        "run_at": now.isoformat(),
        "window_hours": hours,
        "window_start": since.isoformat(),
        "window_end": now.isoformat(),
        "symbols_queried": symbols,
        "sources_status": sources_status,
        "articles": articles,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    if all_failed:
        return 2
    if any(not s["ok"] for s in sources_status.values()):
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=None)
    p.add_argument("--symbols", type=str, default=None, help="comma-separated")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sources", type=str, default=None, help="comma-separated subset")
    args = p.parse_args()

    cfg = load_config()
    hours = args.hours or cfg["default_window_hours"]
    symbols = (args.symbols.split(",") if args.symbols else cfg["default_symbols"])
    enabled = (args.sources.split(",") if args.sources else ALL_SOURCES)
    code = asyncio.run(run_fetch(
        config=cfg, hours=hours, symbols=symbols,
        output_path=args.output, enabled_sources=enabled,
    ))
    return code


if __name__ == "__main__":
    sys.exit(main())
