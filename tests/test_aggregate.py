import json
import pytest
from scripts.aggregate import (
    dedup_articles,
    enrich_tickers,
    apply_vader_fallback,
    select_top_candidates,
    run_aggregate,
)


def test_dedup_by_url():
    articles = [
        {"id": "1", "url": "https://x.com/a", "title": "Fed hikes rates", "source_name": "Reuters"},
        {"id": "2", "url": "https://x.com/a", "title": "Fed hikes rates again", "source_name": "Bloomberg"},
        {"id": "3", "url": "https://y.com/b", "title": "BTC rally", "source_name": "CoinDesk"},
    ]
    out = dedup_articles(articles)
    assert len(out) == 2
    assert {a["url"] for a in out} == {"https://x.com/a", "https://y.com/b"}


def test_dedup_by_title_similarity():
    articles = [
        {"id": "1", "url": "https://a.com/1", "title": "Gold prices rise on Fed patience",
         "source_name": "Reuters", "source_api": "alpha_vantage"},
        {"id": "2", "url": "https://b.com/2", "title": "Gold prices rise as Fed signals patience",
         "source_name": "AP", "source_api": "newsapi"},
    ]
    out = dedup_articles(articles)
    assert len(out) == 1
    # prefers alpha_vantage (has sentiment)
    assert out[0]["source_api"] == "alpha_vantage"


def test_enrich_tickers_from_keywords(sample_config):
    articles = [
        {"id": "1", "title": "Bitcoin hits new high", "summary": "",
         "tickers": [], "url": "u1"},
        {"id": "2", "title": "欧元兑美元", "summary": "",
         "tickers": [], "url": "u2"},
        {"id": "3", "title": "Some unrelated news", "summary": "",
         "tickers": [], "url": "u3"},
    ]
    enriched = enrich_tickers(articles, sample_config["symbol_keywords"])
    assert "BTC" in enriched[0]["tickers"]
    assert "EURUSD" in enriched[1]["tickers"]
    assert enriched[2]["tickers"] == []


def test_vader_fallback_scores_english_news():
    articles = [
        {"id": "1", "title": "Bitcoin surges on massive ETF inflows",
         "summary": "Investors piled in.",
         "api_sentiment_score": None, "api_sentiment_label": None,
         "source_api": "finnhub", "tickers": ["BTC"]},
        {"id": "2", "title": "BOJ warns of yen intervention as volatility soars",
         "summary": "Officials alarmed.",
         "api_sentiment_score": None, "api_sentiment_label": None,
         "source_api": "finnhub", "tickers": ["USDJPY"]},
        {"id": "3", "title": "Neutral headline",
         "summary": "",
         "api_sentiment_score": 0.3, "api_sentiment_label": "Somewhat-Bullish",
         "source_api": "alpha_vantage", "tickers": []},
    ]
    scored = apply_vader_fallback(articles)
    assert scored[0]["api_sentiment_score"] is not None
    assert scored[0]["api_sentiment_score"] > 0
    assert scored[1]["api_sentiment_score"] is not None
    # AV item untouched
    assert scored[2]["api_sentiment_score"] == 0.3


def test_select_top_candidates_respects_limit(sample_config):
    articles = []
    for i in range(30):
        articles.append({
            "id": str(i),
            "title": f"news {i}",
            "tickers": ["BTC"] if i % 2 == 0 else ["ETH"],
            "api_sentiment_score": 0.5 if i < 10 else 0.1,
            "relevance": 0.9,
            "source_api": "alpha_vantage",
            "summary": "",
        })
    top = select_top_candidates(
        articles,
        max_total=20,
        per_symbol_top=3,
        symbols=sample_config["default_symbols"],
    )
    assert len(top) <= 20


def test_run_aggregate_writes_candidates(tmp_path, sample_config):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({
        "run_at": "2026-04-28T09:00:00+00:00",
        "articles": [
            {"id": "1", "url": "u1", "title": "Bitcoin rallies on ETF approval",
             "summary": "Big news.", "tickers": ["BTC"],
             "api_sentiment_score": 0.7, "api_sentiment_label": "Bullish",
             "relevance": 0.9, "source_api": "alpha_vantage", "source_name": "R",
             "published_at": "2026-04-28T08:00:00Z", "category": "news"},
            {"id": "2", "url": "u2", "title": "Gold slumps as Fed sounds hawkish",
             "summary": "", "tickers": [],
             "api_sentiment_score": None, "api_sentiment_label": None,
             "relevance": 0.5, "source_api": "finnhub", "source_name": "F",
             "published_at": "2026-04-28T08:30:00Z", "category": "news"},
        ],
    }))
    out = tmp_path / "cand.json"
    run_aggregate(input_path=raw, output_path=out, config=sample_config)
    data = json.loads(out.read_text())
    assert data["stats"]["total_raw"] == 2
    assert data["stats"]["after_dedup"] == 2
    assert data["stats"]["candidates_for_review"] <= 20
    # gold article should have been enriched with XAUUSD
    g = next(a for a in data["candidates"] if "Gold" in a["title"])
    assert "XAUUSD" in g["tickers"]
