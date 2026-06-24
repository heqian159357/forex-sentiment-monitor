"""GDELT 2.0 DOC API client（无需 API key，免费且含商用授权）。

GDELT 实时监控全球新闻，支持关键词检索，返回 JSON。
文档：https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
端点：https://api.gdeltproject.org/api/v2/doc/doc
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

import aiohttp

BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# 默认检索词：覆盖默认 8 个品种的核心关键词（GDELT 用 OR 语法需括号）
DEFAULT_QUERY = (
    '(bitcoin OR ethereum OR "crypto regulation" OR stablecoin '
    'OR forex OR "gold price" OR "crude oil" OR OPEC OR '
    '"federal reserve" OR "interest rate")'
)

# title/url 关键词 → symbol 兜底映射（aggregate 还会再用 config 关键词补一次）
_KW_MAP = [
    ("bitcoin", "BTC"), ("btc", "BTC"),
    ("ethereum", "ETH"), ("eth", "ETH"),
    ("gold", "XAUUSD"), ("xau", "XAUUSD"),
    ("silver", "XAGUSD"), ("xag", "XAGUSD"),
    ("euro", "EURUSD"),
    ("yen", "USDJPY"),
    ("pound", "GBPUSD"), ("sterling", "GBPUSD"),
    ("crude", "WTI"), ("opec", "WTI"), ("wti", "WTI"),
]


def _hash_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def _map_tickers(title: str) -> list[str]:
    t = (title or "").lower()
    out: set[str] = set()
    for kw, sym in _KW_MAP:
        if kw in t:
            out.add(sym)
    return sorted(out)


def _parse_seendate(seendate: str) -> str:
    """GDELT seendate 形如 20260506T021200Z → ISO8601。"""
    try:
        dt = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


async def fetch_gdelt(
    *,
    query: str = DEFAULT_QUERY,
    hours: int = 24,
    max_records: int = 75,
    timeout: int = 15,
) -> dict[str, Any]:
    """抓 GDELT 新闻。无需 api_key。

    timespan 用 GDELT 的相对时间窗（如 24h）。
    """
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(max_records),
        "timespan": f"{hours}h",
        "sort": "datedesc",
    }
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"User-Agent": "forex-sentiment-monitor/1.0"},
        ) as s:
            async with s.get(BASE_URL, params=params) as r:
                if r.status == 429:
                    return {"ok": False, "count": 0, "rate_limit_hit": True,
                            "error": "rate_limit", "articles": []}
                if r.status >= 400:
                    return {"ok": False, "count": 0, "rate_limit_hit": False,
                            "error": f"http_error_{r.status}", "articles": []}
                # GDELT 偶尔返回非 JSON 的纯文本错误，需容错
                text = await r.text()
                try:
                    import json as _json
                    data = _json.loads(text)
                except ValueError:
                    return {"ok": False, "count": 0, "rate_limit_hit": False,
                            "error": "non_json_response", "articles": []}
    except asyncio.TimeoutError:
        return {"ok": False, "count": 0, "rate_limit_hit": False,
                "error": "timeout", "articles": []}
    except aiohttp.ClientError as e:
        return {"ok": False, "count": 0, "rate_limit_hit": False,
                "error": f"client_error: {e}", "articles": []}

    seen: set[str] = set()
    articles: list[dict] = []
    for item in data.get("articles", []):
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        title = item.get("title", "")
        articles.append({
            "id": _hash_id(url),
            "source_api": "gdelt",
            "source_name": item.get("domain", "unknown"),
            "title": title,
            "summary": "",  # GDELT DOC API 不返回正文摘要
            "url": url,
            "published_at": _parse_seendate(item.get("seendate", "")),
            "tickers": _map_tickers(title),
            "api_sentiment_score": None,   # 交给 VADER fallback + Claude 复核
            "api_sentiment_label": None,
            "relevance": 0.5,
            "category": "news",
        })

    return {
        "ok": True,
        "count": len(articles),
        "rate_limit_hit": False,
        "error": None,
        "articles": articles,
    }
