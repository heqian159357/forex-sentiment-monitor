import json
import pytest
from aioresponses import aioresponses
from scripts.clients.alpha_vantage import fetch_alpha_vantage


@pytest.mark.asyncio
async def test_alpha_vantage_parses_response(fixtures_dir):
    payload = json.loads((fixtures_dir / "alpha_vantage_response.json").read_text())
    with aioresponses() as m:
        m.get(
            "https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=forex,economy_forex&time_from=20260427T090000&apikey=KEY&limit=50",
            payload=payload,
        )
        result = await fetch_alpha_vantage(
            api_key="KEY",
            since_iso="20260427T090000",
            topics=["forex", "economy_forex"],
            timeout=15,
        )
    assert result["ok"] is True
    assert len(result["articles"]) == 2
    a = result["articles"][0]
    assert a["source_api"] == "alpha_vantage"
    assert a["source_name"] == "Reuters"
    assert a["title"].startswith("Gold prices")
    assert a["url"] == "https://reuters.com/gold-1"
    assert a["api_sentiment_score"] == 0.35
    assert "XAUUSD" in a["tickers"]
    assert a["category"] == "news"


@pytest.mark.asyncio
async def test_alpha_vantage_handles_rate_limit():
    with aioresponses() as m:
        m.get(
            "https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=forex&time_from=20260101T000000&apikey=K&limit=50",
            payload={"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."},
        )
        result = await fetch_alpha_vantage(
            api_key="K",
            since_iso="20260101T000000",
            topics=["forex"],
            timeout=15,
        )
    assert result["ok"] is False
    assert result["rate_limit_hit"] is True
