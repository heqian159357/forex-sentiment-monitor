"""RSS 直采 client（无需 API key）。

直接订阅金融/加密媒体的公开 RSS，绕过聚合中间商。
解析用 feedparser；并发抓取多个 feed。
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

import aiohttp

try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None

# 默认 feed 列表（均为公开 RSS，合理引用）。可在 config 覆盖。
DEFAULT_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://www.investing.com/rss/news_301.rss",        # forex
    "https://www.investing.com/rss/news_11.rss",          # commodities
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",      # WSJ markets
]

_KW_MAP = [
    ("bitcoin", "BTC"), ("btc", "BTC"),
    ("ethereum", "ETH"), ("eth", "ETH"),
    ("gold", "XAUUSD"), ("xau", "XAUUSD"),
    ("silver", "XAGUSD"), ("xag", "XAGUSD"),
    ("euro", "EURUSD"),
    ("yen", "USDJPY"),
    ("pound", "GBPUSD"), ("sterling", "GBPUSD"),
    ("crude", "WTI"), ("opec", "WTI"), ("wti", "WTI"), ("oil", "WTI"),
]


def _hash_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def _map_tickers(text: str) -> list[str]:
    t = (text or "").lower()
    out: set[str] = set()
    for kw, sym in _KW_MAP:
        if kw in t:
            out.add(sym)
    return sorted(out)


def _entry_epoch(entry) -> int | None:
    for attr in ("published_parsed", "updated_parsed"):
        tm = getattr(entry, attr, None) or (entry.get(attr) if hasattr(entry, "get") else None)
        if tm:
            try:
                import calendar
                return calendar.timegm(tm)
            except (TypeError, ValueError):
                continue
    return None


async def _fetch_one(session: aiohttp.ClientSession, feed_url: str) -> tuple[str, str | None]:
    try:
        async with session.get(feed_url) as r:
            if r.status >= 400:
                return feed_url, None
            return feed_url, await r.text()
    except (asyncio.TimeoutError, aiohttp.ClientError):
        return feed_url, None


async def fetch_rss(
    *,
    feeds: list[str] | None = None,
    since_epoch: int = 0,
    timeout: int = 12,
) -> dict[str, Any]:
    """并发抓取多个 RSS feed，按时间窗过滤。无需 api_key。"""
    if feedparser is None:
        return {"ok": False, "count": 0, "rate_limit_hit": False,
                "error": "feedparser_not_installed", "articles": []}

    feed_list = feeds or DEFAULT_FEEDS
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"User-Agent": "forex-sentiment-monitor/1.0 (+rss)"},
        ) as s:
            raw = await asyncio.gather(*[_fetch_one(s, f) for f in feed_list])
    except asyncio.TimeoutError:
        return {"ok": False, "count": 0, "rate_limit_hit": False,
                "error": "timeout", "articles": []}

    seen: set[str] = set()
    articles: list[dict] = []
    errors: list[str] = []
    ok_feeds = 0

    for feed_url, text in raw:
        if not text:
            errors.append(f"fetch_fail:{feed_url.split('/')[2]}")
            continue
        parsed = feedparser.parse(text)
        if parsed.bozo and not parsed.entries:
            errors.append(f"parse_fail:{feed_url.split('/')[2]}")
            continue
        ok_feeds += 1
        source_name = parsed.feed.get("title", feed_url.split("/")[2])
        for e in parsed.entries:
            url = e.get("link", "")
            if not url or url in seen:
                continue
            epoch = _entry_epoch(e)
            if epoch is not None and epoch < since_epoch:
                continue
            seen.add(url)
            title = e.get("title", "")
            summary = e.get("summary", "")[:500]
            published = (
                datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
                if epoch else datetime.now(timezone.utc).isoformat()
            )
            articles.append({
                "id": _hash_id(url),
                "source_api": "rss",
                "source_name": source_name,
                "title": title,
                "summary": summary,
                "url": url,
                "published_at": published,
                "tickers": _map_tickers(f"{title} {summary}"),
                "api_sentiment_score": None,
                "api_sentiment_label": None,
                "relevance": 0.5,
                "category": "news",
            })

    # 只要至少一个 feed 成功即视为 ok
    ok = ok_feeds > 0
    return {
        "ok": ok,
        "count": len(articles),
        "rate_limit_hit": False,
        "error": "; ".join(errors) if errors else None,
        "articles": articles,
    }
