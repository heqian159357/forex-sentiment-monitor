"""Deduplicate, enrich tickers, VADER-fallback score, select TOP candidates."""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from collections import defaultdict
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from scripts.config import load_config

SOURCE_PRIORITY = {"alpha_vantage": 3, "finnhub": 2, "newsapi": 1}

# Title similarity dedup threshold (Jaccard). Two near-paraphrase headlines from
# different outlets typically share 50-70% of tokens.
TITLE_DEDUP_THRESHOLD = 0.5

# Boost VADER with a small finance-specific lexicon so words like "surges",
# "inflows", "hawkish" register a non-zero compound score.
_FINANCE_LEXICON = {
    "surges": 2.5, "surge": 2.0, "surged": 2.0, "surging": 2.0,
    "rally": 2.0, "rallies": 2.0, "rallied": 2.0, "rallying": 2.0,
    "soars": 2.5, "soar": 2.0, "soared": 2.0, "soaring": 2.0,
    "jumps": 1.8, "jumped": 1.8, "climbs": 1.5, "climbed": 1.5,
    "slumps": -2.5, "slump": -2.0, "slumped": -2.0,
    "plunges": -3.0, "plunge": -2.5, "plunged": -2.5,
    "crashes": -3.0, "crash": -2.5, "crashed": -2.5,
    "tumbles": -2.5, "tumble": -2.0, "tumbled": -2.0,
    "hawkish": -1.5, "dovish": 1.5,
    "inflows": 1.5, "outflows": -1.5,
    "intervention": -1.5, "volatility": -1.0,
    "bullish": 2.0, "bearish": -2.0,
    "hike": -0.8, "hikes": -0.8, "cut": 0.5, "cuts": 0.5,
}

_vader = SentimentIntensityAnalyzer()
_vader.lexicon.update(_FINANCE_LEXICON)


def _tokens(title: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9一-鿿]+", title.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_articles(articles: list[dict]) -> list[dict]:
    """Dedup by URL first, then by title Jaccard >0.8 (prefer higher SOURCE_PRIORITY)."""
    # URL dedup
    by_url: dict[str, dict] = {}
    for a in articles:
        url = a.get("url")
        if not url:
            continue
        if url not in by_url:
            by_url[url] = a
        else:
            if SOURCE_PRIORITY.get(a.get("source_api", ""), 0) > SOURCE_PRIORITY.get(by_url[url].get("source_api", ""), 0):
                by_url[url] = a
    unique = list(by_url.values())

    # Title similarity dedup
    kept: list[dict] = []
    for a in unique:
        ta = _tokens(a.get("title", ""))
        dup_idx = None
        for i, k in enumerate(kept):
            if _jaccard(ta, _tokens(k.get("title", ""))) > TITLE_DEDUP_THRESHOLD:
                dup_idx = i
                break
        if dup_idx is None:
            kept.append(a)
        else:
            if SOURCE_PRIORITY.get(a.get("source_api", ""), 0) > SOURCE_PRIORITY.get(kept[dup_idx].get("source_api", ""), 0):
                kept[dup_idx] = a
    return kept


def enrich_tickers(articles: list[dict], symbol_keywords: dict[str, list[str]]) -> list[dict]:
    """Fill in `tickers` based on keyword matching in title+summary."""
    out = []
    for a in articles:
        if a.get("tickers"):
            out.append(a)
            continue
        text = (a.get("title", "") + " " + a.get("summary", "")).lower()
        matched = []
        for sym, kws in symbol_keywords.items():
            if any(kw.lower() in text for kw in kws):
                matched.append(sym)
        a = {**a, "tickers": sorted(matched)}
        out.append(a)
    return out


def apply_vader_fallback(articles: list[dict]) -> list[dict]:
    """For articles without api_sentiment_score and English content, score via VADER."""
    out = []
    for a in articles:
        if a.get("api_sentiment_score") is not None:
            out.append(a)
            continue
        text = f"{a.get('title', '')}. {a.get('summary', '')}".strip()
        if not text or not any(c.isascii() and c.isalpha() for c in text):
            out.append(a)
            continue
        scores = _vader.polarity_scores(text)
        out.append({
            **a,
            "api_sentiment_score": scores["compound"],
            "api_sentiment_label": _vader_label(scores["compound"]),
            "_vader_scored": True,
        })
    return out


def _vader_label(compound: float) -> str:
    if compound <= -0.6:
        return "Bearish"
    if compound <= -0.2:
        return "Somewhat-Bearish"
    if compound < 0.2:
        return "Neutral"
    if compound < 0.6:
        return "Somewhat-Bullish"
    return "Bullish"


HIGH_IMPACT_KW = (
    "rate hike", "rate cut", "intervention", "etf approval", "war",
    "invasion", "opec", "emergency meeting", "flash crash", "ban",
)


def select_top_candidates(
    articles: list[dict],
    *,
    max_total: int,
    per_symbol_top: int,
    symbols: list[str],
) -> list[dict]:
    """Rank: per-symbol top-N by |sentiment|*relevance + global high-impact top-5, capped at max_total."""
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for a in articles:
        for sym in a.get("tickers", []):
            if sym in symbols:
                by_sym[sym].append(a)

    selected_ids: set[str] = set()
    chosen: list[dict] = []

    def rank_key(a: dict) -> float:
        sent = abs(a.get("api_sentiment_score") or 0)
        rel = a.get("relevance") or 0.5
        return sent * rel

    for sym in symbols:
        candidates = sorted(by_sym.get(sym, []), key=rank_key, reverse=True)
        for a in candidates[:per_symbol_top]:
            if a["id"] not in selected_ids:
                chosen.append(a)
                selected_ids.add(a["id"])

    impact = [
        a for a in articles
        if a["id"] not in selected_ids
        and any(kw in a.get("title", "").lower() for kw in HIGH_IMPACT_KW)
    ]
    for a in sorted(impact, key=rank_key, reverse=True)[:5]:
        if a["id"] not in selected_ids:
            chosen.append(a)
            selected_ids.add(a["id"])

    return chosen[:max_total]


def run_aggregate(*, input_path: Path, output_path: Path, config: dict) -> None:
    raw = json.loads(Path(input_path).read_text())
    articles = raw.get("articles", [])
    total_raw = len(articles)

    by_source_raw: dict[str, int] = defaultdict(int)
    for a in articles:
        by_source_raw[a.get("source_api", "unknown")] += 1

    deduped = dedup_articles(articles)
    enriched = enrich_tickers(deduped, config["symbol_keywords"])
    scored = apply_vader_fallback(enriched)

    by_symbol: dict[str, int] = defaultdict(int)
    by_cat: dict[str, int] = defaultdict(int)
    for a in scored:
        by_cat[a.get("category", "news")] += 1
        for s in a.get("tickers", []):
            by_symbol[s] += 1

    candidates = select_top_candidates(
        scored,
        max_total=config["max_candidates_for_review"],
        per_symbol_top=3,
        symbols=config["default_symbols"],
    )

    payload = {
        "run_at": raw.get("run_at"),
        "stats": {
            "total_raw": total_raw,
            "after_dedup": len(deduped),
            "candidates_for_review": len(candidates),
            "by_symbol": dict(by_symbol),
            "by_source_api": dict(by_source_raw),
            "by_category": dict(by_cat),
        },
        "candidates": candidates,
        "all_articles_ref": str(input_path.name),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    cfg = load_config()
    run_aggregate(input_path=args.input, output_path=args.output, config=cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
