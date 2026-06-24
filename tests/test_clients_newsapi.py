import json
import pytest
from aioresponses import aioresponses
from scripts.clients.newsapi import fetch_newsapi


@pytest.mark.asyncio
async def test_newsapi_parses(fixtures_dir):
    payload = json.loads((fixtures_dir / "newsapi_response.json").read_text())
    with aioresponses() as m:
        m.get(
            "https://newsapi.org/v2/everything?q=forex+OR+gold+OR+bitcoin+OR+ethereum+OR+crude+oil&from=2026-04-27T09:00:00Z&language=en&sortBy=publishedAt&pageSize=100&apiKey=K",
            payload=payload,
        )
        result = await fetch_newsapi(
            api_key="K",
            since_iso="2026-04-27T09:00:00Z",
            query="forex OR gold OR bitcoin OR ethereum OR crude oil",
            timeout=10,
        )
    assert result["ok"] is True
    assert len(result["articles"]) == 1
    a = result["articles"][0]
    assert a["source_api"] == "newsapi"
    assert a["source_name"] == "Reuters"
    assert a["api_sentiment_score"] is None


@pytest.mark.asyncio
async def test_newsapi_quota_exceeded():
    with aioresponses() as m:
        m.get(
            "https://newsapi.org/v2/everything?q=x&from=2026-01-01T00:00:00Z&language=en&sortBy=publishedAt&pageSize=100&apiKey=K",
            status=429,
            payload={"status": "error", "code": "rateLimited", "message": "quota exceeded"},
        )
        result = await fetch_newsapi(
            api_key="K", since_iso="2026-01-01T00:00:00Z", query="x", timeout=10,
        )
    assert result["ok"] is False
    assert result["rate_limit_hit"] is True
