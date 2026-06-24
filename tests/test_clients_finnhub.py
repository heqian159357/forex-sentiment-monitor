import json
import pytest
from aioresponses import aioresponses
from scripts.clients.finnhub import fetch_finnhub


@pytest.mark.asyncio
async def test_finnhub_parses_news(fixtures_dir):
    payload = json.loads((fixtures_dir / "finnhub_response.json").read_text())
    with aioresponses() as m:
        m.get(
            "https://finnhub.io/api/v1/news?category=general&token=K",
            payload=payload,
        )
        m.get(
            "https://finnhub.io/api/v1/news?category=crypto&token=K",
            payload=payload,
        )
        m.get(
            "https://finnhub.io/api/v1/news?category=forex&token=K",
            payload=payload,
        )
        result = await fetch_finnhub(
            api_key="K",
            since_epoch=1745800000,
            categories=["general", "crypto", "forex"],
            timeout=10,
        )
    assert result["ok"] is True
    # Deduped by url across categories
    assert len(result["articles"]) == 2
    titles = {a["title"] for a in result["articles"]}
    assert "Ethereum upgrade boosts staking yields" in titles
    eth_article = next(a for a in result["articles"] if "Ethereum" in a["title"])
    assert "ETH" in eth_article["tickers"]
    assert eth_article["source_api"] == "finnhub"
    # Finnhub has no sentiment score
    assert eth_article["api_sentiment_score"] is None


@pytest.mark.asyncio
async def test_finnhub_skips_items_older_than_since():
    old_payload = [{
        "datetime": 1700000000,
        "headline": "old news",
        "id": 1,
        "related": "",
        "source": "X",
        "summary": "",
        "url": "https://x.com/old",
        "category": "general",
    }]
    with aioresponses() as m:
        m.get("https://finnhub.io/api/v1/news?category=general&token=K", payload=old_payload)
        result = await fetch_finnhub(
            api_key="K", since_epoch=1745000000, categories=["general"], timeout=10
        )
    assert result["ok"] is True
    assert len(result["articles"]) == 0
