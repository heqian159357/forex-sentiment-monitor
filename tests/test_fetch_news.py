import json
import re
import pytest
from aioresponses import aioresponses
from scripts.fetch_news import run_fetch


@pytest.mark.asyncio
async def test_run_fetch_all_sources_ok(tmp_path, sample_config, fixtures_dir):
    sample_config["sources"] = {
        "alpha_vantage": {"enabled": True, "timeout_seconds": 15, "retry": 0, "rate_limit_per_minute": 5, "daily_quota": 25},
        "finnhub": {"enabled": True, "timeout_seconds": 10, "retry": 0, "rate_limit_per_minute": 60},
        "newsapi": {"enabled": True, "timeout_seconds": 10, "retry": 0, "daily_quota": 100},
    }
    sample_config["api_keys"] = {"alpha_vantage": "A", "finnhub": "F", "newsapi": "N"}

    av = json.loads((fixtures_dir / "alpha_vantage_response.json").read_text())
    fh = json.loads((fixtures_dir / "finnhub_response.json").read_text())
    na = json.loads((fixtures_dir / "newsapi_response.json").read_text())

    out = tmp_path / "raw_news.json"
    with aioresponses() as m:
        m.get(re.compile(r"^https://www\.alphavantage\.co/query.*"), payload=av, repeat=True)
        m.get(re.compile(r"^https://finnhub\.io/api/v1/news.*"), payload=fh, repeat=True)
        m.get(re.compile(r"^https://newsapi\.org/v2/everything.*"), payload=na, repeat=True)
        exit_code = await run_fetch(
            config=sample_config,
            hours=24,
            symbols=["BTC", "ETH", "XAUUSD", "EURUSD"],
            output_path=out,
            enabled_sources=["alpha_vantage", "finnhub", "newsapi"],
        )
    assert exit_code == 0
    data = json.loads(out.read_text())
    assert data["sources_status"]["alpha_vantage"]["ok"] is True
    assert data["sources_status"]["finnhub"]["ok"] is True
    assert data["sources_status"]["newsapi"]["ok"] is True
    assert len(data["articles"]) >= 3


@pytest.mark.asyncio
async def test_run_fetch_all_fail_returns_2(tmp_path, sample_config):
    sample_config["sources"] = {
        "alpha_vantage": {"enabled": True, "timeout_seconds": 1, "retry": 0, "rate_limit_per_minute": 5, "daily_quota": 25},
        "finnhub": {"enabled": True, "timeout_seconds": 1, "retry": 0, "rate_limit_per_minute": 60},
        "newsapi": {"enabled": True, "timeout_seconds": 1, "retry": 0, "daily_quota": 100},
    }
    sample_config["api_keys"] = {"alpha_vantage": "A", "finnhub": "F", "newsapi": "N"}
    out = tmp_path / "raw_news.json"
    with aioresponses() as m:
        m.get(re.compile(r"^https://www\.alphavantage\.co/query.*"),
              payload={"Note": "rate limit"}, repeat=True)
        m.get(re.compile(r"^https://finnhub\.io/api/v1/news.*"), status=500, repeat=True)
        m.get(re.compile(r"^https://newsapi\.org/v2/everything.*"), status=429, repeat=True)
        code = await run_fetch(
            config=sample_config, hours=24,
            symbols=["BTC"], output_path=out,
            enabled_sources=["alpha_vantage", "finnhub", "newsapi"],
        )
    assert code == 2
