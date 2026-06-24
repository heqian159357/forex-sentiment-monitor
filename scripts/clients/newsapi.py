"""NewsAPI /v2/everything client (no sentiment provided)."""
from __future__ import annotations
import hashlib
from typing import Any
import aiohttp
import asyncio

BASE_URL = "https://newsapi.org/v2/everything"


def _hash_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


async def fetch_newsapi(
    *,
    api_key: str,
    since_iso: str,
    query: str,
    timeout: int = 10,
    page_size: int = 100,
) -> dict[str, Any]:
    """Fetch NewsAPI /everything filtered by since_iso and query."""
    params = {
        "q": query,
        "from": since_iso,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": str(page_size),
        "apiKey": api_key,
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.get(BASE_URL, params=params) as r:
                if r.status == 429:
                    return {"ok": False, "count": 0, "rate_limit_hit": True,
                            "error": "quota exceeded", "articles": []}
                if r.status in (401, 403):
                    return {"ok": False, "count": 0, "rate_limit_hit": False,
                            "error": f"auth_error_{r.status}", "articles": []}
                data = await r.json()
    except asyncio.TimeoutError:
        return {"ok": False, "count": 0, "rate_limit_hit": False, "error": "timeout", "articles": []}
    except Exception as e:
        return {"ok": False, "count": 0, "rate_limit_hit": False, "error": str(e), "articles": []}

    if data.get("status") != "ok":
        return {"ok": False, "count": 0, "rate_limit_hit": False,
                "error": data.get("message", "unknown"), "articles": []}

    articles = []
    for item in data.get("articles", []):
        url = item.get("url", "")
        if not url:
            continue
        articles.append({
            "id": _hash_id(url),
            "source_api": "newsapi",
            "source_name": (item.get("source") or {}).get("name") or "unknown",
            "title": item.get("title") or "",
            "summary": item.get("description") or "",
            "url": url,
            "published_at": item.get("publishedAt", ""),
            "tickers": [],
            "api_sentiment_score": None,
            "api_sentiment_label": None,
            "relevance": 0.5,
            "category": "news",
        })
    return {"ok": True, "count": len(articles), "rate_limit_hit": False,
            "error": None, "articles": articles}
