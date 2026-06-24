import json
import pytest
from scripts.render_report import (
    compute_final_score,
    score_to_label,
    detect_alerts,
    run_render,
)


def test_score_to_label_bands():
    assert score_to_label(-0.8) == "Bearish"
    assert score_to_label(-0.4) == "Somewhat-Bearish"
    assert score_to_label(0.0) == "Neutral"
    assert score_to_label(0.4) == "Somewhat-Bullish"
    assert score_to_label(0.8) == "Bullish"


def test_compute_final_score_claude_only(sample_config):
    raw = [{"id": "1", "tickers": ["BTC"], "api_sentiment_score": 0.3, "relevance": 0.8}]
    reviewed = [{
        "id": "1", "claude_sentiment_score": -0.6, "claude_sentiment_label": "Bearish",
        "affected_symbols": ["BTC"], "impact_level": "high",
    }]
    final, label, count = compute_final_score("BTC", raw, reviewed, sample_config)
    # only claude, impact high weight 1.0 → final = -0.6
    assert abs(final - (-0.6)) < 0.01
    assert count == 1


def test_compute_final_score_blended(sample_config):
    raw = [
        {"id": "1", "tickers": ["BTC"], "api_sentiment_score": 0.5, "relevance": 0.8},
        {"id": "2", "tickers": ["BTC"], "api_sentiment_score": 0.2, "relevance": 1.0},
    ]
    reviewed = [{
        "id": "1", "claude_sentiment_score": -0.4, "claude_sentiment_label": "Somewhat-Bearish",
        "affected_symbols": ["BTC"], "impact_level": "medium",
    }]
    final, _, count = compute_final_score("BTC", raw, reviewed, sample_config)
    # claude: -0.4 * 0.6 = -0.24
    # api_only: 0.2 * 1.0 = 0.2
    # final: 0.6 * -0.24 + 0.4 * 0.2 = -0.144 + 0.08 = -0.064
    assert abs(final - (-0.064)) < 0.01
    assert count == 2


def test_detect_alerts_extreme(sample_config):
    scores = {"BTC": -0.7, "ETH": 0.1, "XAUUSD": 0.6}
    divergences = []
    sources = {"alpha_vantage": {"ok": True}}
    alerts = detect_alerts(scores, divergences, sources, sample_config)
    rules = {a["rule"] for a in alerts}
    assert "extreme_bearish" in rules
    assert "extreme_bullish" in rules


def test_detect_alerts_high_impact_divergence(sample_config):
    scores = {"BTC": 0.1}
    divergences = [{"impact_level": "high", "divergence_with_api": True}]
    sources = {"alpha_vantage": {"ok": True}}
    alerts = detect_alerts(scores, divergences, sources, sample_config)
    assert any(a["rule"] == "high_impact_divergence" for a in alerts)


def test_detect_alerts_source_failure(sample_config):
    scores = {"BTC": 0.0}
    divergences = []
    sources = {"alpha_vantage": {"ok": False}, "finnhub": {"ok": True}}
    alerts = detect_alerts(scores, divergences, sources, sample_config)
    assert any(a["rule"] == "data_source_failure" for a in alerts)


def test_run_render_generates_md_and_html(tmp_path, sample_config):
    raw_path = tmp_path / "raw.json"
    cand_path = tmp_path / "cand.json"
    rev_path = tmp_path / "rev.json"

    raw_path.write_text(json.dumps({
        "run_at": "2026-04-28T09:00:00+00:00",
        "window_hours": 12,
        "window_start": "2026-04-27T21:00:00+00:00",
        "window_end": "2026-04-28T09:00:00+00:00",
        "symbols_queried": ["BTC", "XAUUSD"],
        "sources_status": {
            "alpha_vantage": {"ok": True, "count": 2, "error": None},
            "finnhub": {"ok": True, "count": 1, "error": None},
            "newsapi": {"ok": False, "count": 0, "error": "quota"},
        },
        "articles": [
            {"id": "1", "url": "https://a.com/1", "title": "BTC ETF approved",
             "summary": "", "tickers": ["BTC"], "api_sentiment_score": 0.7,
             "api_sentiment_label": "Bullish", "relevance": 0.9,
             "source_api": "alpha_vantage", "source_name": "Reuters",
             "published_at": "2026-04-28T08:00:00Z", "category": "news"},
            {"id": "2", "url": "https://a.com/2", "title": "Gold falls on hawkish Fed",
             "summary": "", "tickers": ["XAUUSD"], "api_sentiment_score": 0.1,
             "api_sentiment_label": "Neutral", "relevance": 0.8,
             "source_api": "alpha_vantage", "source_name": "Bloomberg",
             "published_at": "2026-04-28T07:00:00Z", "category": "news"},
        ],
    }))
    cand_path.write_text(json.dumps({
        "run_at": "2026-04-28T09:00:00+00:00",
        "stats": {"total_raw": 2, "after_dedup": 2, "candidates_for_review": 2,
                  "by_symbol": {"BTC": 1, "XAUUSD": 1},
                  "by_source_api": {"alpha_vantage": 2},
                  "by_category": {"news": 2}},
        "candidates": [],
        "all_articles_ref": "raw.json",
    }))
    rev_path.write_text(json.dumps({
        "reviewed_at": "2026-04-28T09:01:00+00:00",
        "self_check_log": "[Self-check] 2 items reviewed. All passed.",
        "reviews": [
            {"id": "1", "claude_sentiment_score": 0.7, "claude_sentiment_label": "Bullish",
             "industry_reason": "ETF 批准 → 资金流入 → BTC 利多",
             "affected_symbols": ["BTC"], "impact_level": "high",
             "divergence_with_api": False, "divergence_note": None},
            {"id": "2", "claude_sentiment_score": -0.6, "claude_sentiment_label": "Bearish",
             "industry_reason": "美联储鹰派 → DXY 走强 → 黄金承压",
             "affected_symbols": ["XAUUSD"], "impact_level": "high",
             "divergence_with_api": True, "divergence_note": "API 中性但行业视角明确利空"},
        ],
    }))

    outdir = tmp_path / "reports"
    paths = run_render(
        raw_path=raw_path, candidates_path=cand_path, reviewed_path=rev_path,
        output_dir=outdir, config=sample_config, mode="full",
    )
    assert paths["md"].exists()
    assert paths["html"].exists()
    md = paths["md"].read_text()
    assert "BTC" in md
    assert "XAUUSD" in md
    assert "⚠️" in md  # divergence marker
    alerts_path = outdir / "alerts.json"
    assert alerts_path.exists()
    alerts = json.loads(alerts_path.read_text())
    # XAUUSD score -0.6*1.0 = -0.6 triggers extreme_bearish
    assert any(a["rule"] == "extreme_bearish" for a in alerts)
