"""Finnhub news client (no sentiment; fetched across categories)."""
from __future__ import annotations
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any
import aiohttp

BASE_URL = "https://finnhub.io/api/v1/news"

RELATED_MAP = {
    "BTC": "BTC", "BITCOIN": "BTC",
    "ETH": "ETH", "ETHEREUM": "ETH",
    "XAU": "XAUUSD", "GOLD": "XAUUSD",
    "XAG": "XAGUSD", "SILVER": "XAGUSD",
    "EUR": "EURUSD", "EURUSD": "EURUSD",
    "JPY": "USDJPY", "USDJPY": "USDJPY",
    "GBP": "GBPUSD", "GBPUSD": "GBPUSD",
    "WTI": "WTI", "OIL": "WTI", "CRUDE": "WTI",
}


def _hash_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def _map_related(related: str, title_lower: str) -> list[str]:
    out: set[str] = set()
    for token in (related or "").upper().split(","):
        token = token.strip()
        if token in RELATED_MAP:
            out.add(RELATED_MAP[token])
    # title-based fallback
    for kw, sym in (("bitcoin", "BTC"), ("ethereum", "ETH"),
                    ("gold", "XAUUSD"), ("silver", "XAGUSD"),
                    ("euro", "EURUSD"), ("yen", "USDJPY"),
                    ("pound", "GBPUSD"), ("sterling", "GBPUSD"),
                    ("wti", "WTI"), ("opec", "WTI"), ("crude oil", "WTI")):
        if kw in title_lower:
            out.add(sym)
    return sorted(out)


async def _get_one_category(session: aiohttp.ClientSession, category: str, api_key: str) -> list[dict]:
    params = {"category": category, "token": api_key}
    async with session.get(BASE_URL, params=params) as r:
        if r.status == 429:
            raise RuntimeError("rate_limit")
        if r.status == 401 or r.status == 403:
            raise RuntimeError(f"auth_error_{r.status}")
        if r.status >= 400:
            raise RuntimeError(f"http_error_{r.status}")
        return await r.json()


async def fetch_finnhub(
    *,
    api_key: str,
    since_epoch: int,
    categories: list[str],
    timeout: int = 10,
) -> dict[str, Any]:
    """Fetch Finnhub news across categories; dedupe by URL; filter by since_epoch."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            tasks = [_get_one_category(s, c, api_key) for c in categories]
            results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.TimeoutError:
        return {"ok": False, "count": 0, "rate_limit_hit": False, "error": "timeout", "articles": []}

    seen_urls: set[str] = set()
    articles: list[dict] = []
    rate_hit = False
    errors = []
    for res in results:
        if isinstance(res, Exception):
            msg = str(res)
            if "rate_limit" in msg:
                rate_hit = True
            errors.append(msg)
            continue
        for item in res or []:
            url = item.get("url", "")
            if not url or url in seen_urls:
                continue
            ts = item.get("datetime", 0)
            if ts < since_epoch:
                continue
            seen_urls.add(url)
            title = item.get("headline", "")
            articles.append({
                "id": _hash_id(url),
                "source_api": "finnhub",
                "source_name": item.get("source", "unknown"),
                "title": title,
                "summary": item.get("summary", ""),
                "url": url,
                "published_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "tickers": _map_related(item.get("related", ""), title.lower()),
                "api_sentiment_score": None,
                "api_sentiment_label": None,
                "relevance": 0.5,
                "category": item.get("category", "news"),
            })
    ok = len(articles) > 0 or not errors
    return {
        "ok": ok,
        "count": len(articles),
        "rate_limit_hit": rate_hit,
        "error": "; ".join(errors) if errors else None,
        "articles": articles,
    }
