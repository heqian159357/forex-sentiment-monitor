"""CryptoPanic client（加密专属舆情，自带多空投票）。

免费档需一个免费 auth_token（https://cryptopanic.com/developers/api/）。
若未配置 token，调用方应跳过本源（fetch_news 已处理）。
端点：https://cryptopanic.com/api/v1/posts/
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

import aiohttp

BASE_URL = "https://cryptopanic.com/api/v1/posts/"

# CryptoPanic currency code → 本系统 symbol
_CURRENCY_MAP = {"BTC": "BTC", "ETH": "ETH"}


def _hash_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def _votes_to_sentiment(votes: dict) -> tuple[float | None, str | None]:
    """把 CryptoPanic 的多空投票折算成 [-1,1] 情绪分。

    votes 含 positive / negative / important 等计数。
    """
    if not votes:
        return None, None
    pos = votes.get("positive", 0) + votes.get("liked", 0)
    neg = votes.get("negative", 0) + votes.get("disliked", 0)
    total = pos + neg
    if total == 0:
        return None, None
    score = round((pos - neg) / total, 4)
    if score <= -0.6:
        label = "Bearish"
    elif score <= -0.2:
        label = "Somewhat-Bearish"
    elif score < 0.2:
        label = "Neutral"
    elif score < 0.6:
        label = "Somewhat-Bullish"
    else:
        label = "Bullish"
    return score, label


def _map_tickers(currencies: list) -> list[str]:
    out: set[str] = set()
    for c in currencies or []:
        code = (c.get("code") or "").upper()
        if code in _CURRENCY_MAP:
            out.add(_CURRENCY_MAP[code])
    return sorted(out)


async def fetch_cryptopanic(
    *,
    api_key: str,
    since_epoch: int = 0,
    timeout: int = 10,
) -> dict[str, Any]:
    """抓 CryptoPanic 加密舆情。需 free auth_token。"""
    if not api_key or api_key.startswith("demo") or api_key.endswith("placeholder"):
        return {"ok": False, "count": 0, "rate_limit_hit": False,
                "error": "no_token (源已跳过)", "articles": []}

    params = {
        "auth_token": api_key,
        "currencies": "BTC,ETH",
        "public": "true",
        "kind": "news",
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
                if r.status in (401, 403):
                    return {"ok": False, "count": 0, "rate_limit_hit": False,
                            "error": f"auth_error_{r.status}", "articles": []}
                if r.status >= 400:
                    return {"ok": False, "count": 0, "rate_limit_hit": False,
                            "error": f"http_error_{r.status}", "articles": []}
                data = await r.json()
    except asyncio.TimeoutError:
        return {"ok": False, "count": 0, "rate_limit_hit": False,
                "error": "timeout", "articles": []}
    except aiohttp.ClientError as e:
        return {"ok": False, "count": 0, "rate_limit_hit": False,
                "error": f"client_error: {e}", "articles": []}

    seen: set[str] = set()
    articles: list[dict] = []
    for post in data.get("results", []):
        url = post.get("url") or post.get("original_url") or ""
        if not url or url in seen:
            continue
        # 时间过滤
        published_iso = post.get("published_at") or post.get("created_at") or ""
        epoch = None
        if published_iso:
            try:
                epoch = int(datetime.fromisoformat(
                    published_iso.replace("Z", "+00:00")
                ).timestamp())
            except ValueError:
                epoch = None
        if epoch is not None and epoch < since_epoch:
            continue
        seen.add(url)
        score, label = _votes_to_sentiment(post.get("votes", {}))
        title = post.get("title", "")
        articles.append({
            "id": _hash_id(url),
            "source_api": "cryptopanic",
            "source_name": (post.get("source") or {}).get("title", "CryptoPanic"),
            "title": title,
            "summary": "",
            "url": url,
            "published_at": published_iso or datetime.now(timezone.utc).isoformat(),
            "tickers": _map_tickers(post.get("currencies", [])),
            "api_sentiment_score": score,
            "api_sentiment_label": label,
            "relevance": 0.6,   # 加密专属源，相关性略高
            "category": "crypto",
        })

    return {
        "ok": True,
        "count": len(articles),
        "rate_limit_hit": False,
        "error": None,
        "articles": articles,
    }
