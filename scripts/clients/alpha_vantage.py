"""Alpha Vantage NEWS_SENTIMENT client."""
from __future__ import annotations
import asyncio
import hashlib
from typing import Any
import aiohttp

BASE_URL = "https://www.alphavantage.co/query"

# Map AV ticker format to our symbol list
TICKER_MAP = {
    "FOREX:XAU": "XAUUSD",
    "FOREX:XAG": "XAGUSD",
    "FOREX:EUR": "EURUSD",
    "FOREX:JPY": "USDJPY",
    "FOREX:GBP": "GBPUSD",
    "CRYPTO:BTC": "BTC",
    "CRYPTO:ETH": "ETH",
}

WTI_KEYWORDS = ("wti", "crude oil", "opec")


def _map_tickers(av_ticker_sentiment: list[dict], title_lower: str) -> list[str]:
    out: set[str] = set()
    for t in av_ticker_sentiment or []:
        mapped = TICKER_MAP.get(t.get("ticker"))
        if mapped:
            out.add(mapped)
    if any(k in title_lower for k in WTI_KEYWORDS):
        out.add("WTI")
    return sorted(out)


def _parse_time(av_time: str) -> str:
    """'20260428T070000' -> '2026-04-28T07:00:00Z'"""
    return f"{av_time[:4]}-{av_time[4:6]}-{av_time[6:8]}T{av_time[9:11]}:{av_time[11:13]}:{av_time[13:15]}Z"


def _hash_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


async def fetch_alpha_vantage(
    *,
    api_key: str,
    since_iso: str,
    topics: list[str],
    timeout: int = 15,
    limit: int = 50,
) -> dict[str, Any]:
    """Call AV NEWS_SENTIMENT and normalize.

    Returns:
        {"ok": bool, "count": int, "rate_limit_hit": bool, "error": str|None, "articles": [...]}
    """
    params = {
        "function": "NEWS_SENTIMENT",
        "topics": ",".join(topics),
        "time_from": since_iso,
        "apikey": api_key,
        "limit": str(limit),
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.get(BASE_URL, params=params) as r:
                data = await r.json()
    except asyncio.TimeoutError:
        return {"ok": False, "count": 0, "rate_limit_hit": False, "error": "timeout", "articles": []}
    except Exception as e:
        return {"ok": False, "count": 0, "rate_limit_hit": False, "error": str(e), "articles": []}

    # AV signals rate limit via "Note" or "Information" field
    if "Note" in data or "Information" in data:
        msg = data.get("Note") or data.get("Information")
        return {
            "ok": False,
            "count": 0,
            "rate_limit_hit": "rate limit" in msg.lower() or "thank you" in msg.lower(),
            "error": msg,
            "articles": [],
        }

    articles = []
    for item in data.get("feed", []):
        url = item.get("url", "")
        if not url:
            continue
        title = item.get("title", "")
        articles.append({
            "id": _hash_id(url),
            "source_api": "alpha_vantage",
            "source_name": item.get("source", "unknown"),
            "title": title,
            "summary": item.get("summary", ""),
            "url": url,
            "published_at": _parse_time(item.get("time_published", "")),
            "tickers": _map_tickers(item.get("ticker_sentiment", []), title.lower()),
            "api_sentiment_score": float(item.get("overall_sentiment_score", 0.0)),
            "api_sentiment_label": item.get("overall_sentiment_label", "Neutral"),
            "relevance": max(
                (float(t.get("relevance_score", 0)) for t in item.get("ticker_sentiment", [])),
                default=0.5,
            ),
            "category": item.get("category_within_source", "news"),
        })
    return {"ok": True, "count": len(articles), "rate_limit_hit": False, "error": None, "articles": articles}
