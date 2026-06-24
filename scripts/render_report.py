"""Merge raw + candidates + reviewed → MD + HTML reports + alerts.json."""
from __future__ import annotations
import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from jinja2 import Environment, FileSystemLoader, select_autoescape
from scripts.audit import make_record, write_record
from scripts.config import load_config
from scripts.content_filter import HardBlockError, apply_filter
from scripts.notify import notify

log = logging.getLogger(__name__)

IMPACT_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}
LABEL_ICON = {
    "Bearish": "🔴", "Somewhat-Bearish": "🟠", "Neutral": "🟡",
    "Somewhat-Bullish": "🟢", "Bullish": "💚",
}


def score_to_label(score: float) -> str:
    if score <= -0.6:
        return "Bearish"
    if score <= -0.2:
        return "Somewhat-Bearish"
    if score < 0.2:
        return "Neutral"
    if score < 0.6:
        return "Somewhat-Bullish"
    return "Bullish"


def compute_final_score(
    symbol: str, raw_articles: list[dict], reviewed: list[dict], config: dict
) -> tuple[float, str, int]:
    related = [a for a in raw_articles if symbol in (a.get("tickers") or [])]
    if not related:
        return 0.0, "Neutral", 0

    reviewed_by_id = {r["id"]: r for r in reviewed}
    claude_weighted: list[float] = []
    api_only: list[float] = []

    for a in related:
        r = reviewed_by_id.get(a["id"])
        if r and symbol in r.get("affected_symbols", []):
            w = IMPACT_WEIGHT.get(r.get("impact_level", "medium"), 0.6)
            claude_weighted.append(r["claude_sentiment_score"] * w)
        elif a.get("api_sentiment_score") is not None:
            api_only.append(a["api_sentiment_score"] * (a.get("relevance") or 0.5))

    claude_avg = sum(claude_weighted) / len(claude_weighted) if claude_weighted else None
    api_avg = sum(api_only) / len(api_only) if api_only else None

    w = config["score_weights"]
    if claude_avg is not None and api_avg is not None:
        final = w["claude"] * claude_avg + w["api_only"] * api_avg
    elif claude_avg is not None:
        final = claude_avg
    elif api_avg is not None:
        final = api_avg
    else:
        final = 0.0

    return final, score_to_label(final), len(related)


def detect_alerts(
    final_scores: dict[str, float],
    divergences: list[dict],
    sources_status: dict[str, dict],
    config: dict,
) -> list[dict]:
    alerts: list[dict] = []
    th = config["alert_thresholds"]
    for sym, score in final_scores.items():
        if score < th["extreme_bearish"]:
            alerts.append({"rule": "extreme_bearish", "symbol": sym,
                           "final_score": score, "priority": "high",
                           "message": f"综合分 {score:.2f} < 阈值 {th['extreme_bearish']}"})
        elif score > th["extreme_bullish"]:
            alerts.append({"rule": "extreme_bullish", "symbol": sym,
                           "final_score": score, "priority": "high",
                           "message": f"综合分 {score:.2f} > 阈值 {th['extreme_bullish']}"})
    if any(d.get("impact_level") == "high" and d.get("divergence_with_api") for d in divergences):
        alerts.append({"rule": "high_impact_divergence", "symbol": None,
                       "priority": "medium",
                       "message": "存在 high-impact 的 API vs Claude 情感分歧"})
    if any(not s.get("ok") for s in sources_status.values()):
        failed = [k for k, v in sources_status.items() if not v.get("ok")]
        alerts.append({"rule": "data_source_failure", "symbol": None,
                       "priority": "low",
                       "message": f"数据源失败: {', '.join(failed)}"})
    return alerts


def _short_time(iso: str) -> str:
    if not iso:
        return "-"
    return iso.replace("T", " ")[:16]


def _build_symbol_view(
    sym: str, final: float, label: str, count: int,
    raw_articles: list[dict], reviewed_by_id: dict, alert_symbols: set[str],
) -> dict:
    related = [a for a in raw_articles if sym in (a.get("tickers") or [])]

    def _rank(a):
        s = a.get("api_sentiment_score") or 0
        return abs(s) * (a.get("relevance") or 0.5)
    top = sorted(related, key=_rank, reverse=True)[:5]
    top_view = []
    divergence_notes = []
    drivers_set: list[str] = []
    for a in top:
        r = reviewed_by_id.get(a["id"])
        top_view.append({
            **a,
            "published_at_short": _short_time(a.get("published_at", "")),
            "claude_sentiment_score": r["claude_sentiment_score"] if r else None,
            "divergence_with_api": r.get("divergence_with_api") if r else False,
        })
        if r:
            if r.get("industry_reason") and r["industry_reason"] not in drivers_set:
                drivers_set.append(r["industry_reason"])
            if r.get("divergence_with_api"):
                divergence_notes.append({
                    "title": a.get("title", ""),
                    "divergence_note": r.get("divergence_note", ""),
                    "analysis_detail": r.get("analysis_detail"),
                })
    return {
        "name": sym,
        "final_score": final,
        "label": label,
        "label_icon": LABEL_ICON.get(label, ""),
        "news_count": count,
        "alert": sym in alert_symbols,
        "key_drivers": drivers_set[:3],
        "top_news": top_view,
        "divergence_notes": divergence_notes,
    }


def run_render(
    *,
    raw_path: Path,
    candidates_path: Path,
    reviewed_path: Path,
    output_dir: Path,
    config: dict,
    mode: str = "full",
    strict_filter: bool = True,
) -> dict[str, Path]:
    raw = json.loads(raw_path.read_text())
    cand = json.loads(candidates_path.read_text())
    rev = json.loads(reviewed_path.read_text())

    filter_stats = apply_filter(rev, strict=strict_filter)

    all_articles = raw.get("articles", [])
    reviewed = rev.get("reviews", [])
    reviewed_by_id = {r["id"]: r for r in reviewed}
    sources_status = raw.get("sources_status", {})
    symbols = raw.get("symbols_queried") or config["default_symbols"]

    final_scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for sym in symbols:
        f, l, c = compute_final_score(sym, all_articles, reviewed, config)
        final_scores[sym] = f
        counts[sym] = c
        labels[sym] = l

    divergences = [r for r in reviewed if r.get("divergence_with_api")]
    alerts = detect_alerts(final_scores, divergences, sources_status, config)
    alert_symbols = {a["symbol"] for a in alerts if a.get("symbol")}

    symbols_summary = [
        {"name": s, "final_score": final_scores[s], "label": labels[s],
         "label_icon": LABEL_ICON.get(labels[s], ""),
         "news_count": counts[s], "alert": s in alert_symbols}
        for s in symbols
    ]
    symbols_detail = [
        _build_symbol_view(s, final_scores[s], labels[s], counts[s],
                           all_articles, reviewed_by_id, alert_symbols)
        for s in symbols if counts[s] > 0
    ]

    def _event_rank(r):
        return IMPACT_WEIGHT.get(r.get("impact_level", "low"), 0.3) * abs(r.get("claude_sentiment_score", 0))
    top_reviewed = sorted(reviewed, key=_event_rank, reverse=True)[:3]
    articles_by_id = {a["id"]: a for a in all_articles}
    top_events = []
    for r in top_reviewed:
        a = articles_by_id.get(r["id"], {})
        top_events.append({
            **a,
            "claude_sentiment_score": r.get("claude_sentiment_score"),
            "claude_sentiment_label": r.get("claude_sentiment_label"),
            "industry_reason": r.get("industry_reason"),
            "analysis_detail": r.get("analysis_detail"),
            "impact_level": r.get("impact_level"),
            "affected_symbols": r.get("affected_symbols", []),
            "published_at": _short_time(a.get("published_at", "")),
        })

    divergence_items = []
    for r in divergences:
        a = articles_by_id.get(r["id"], {})
        if a:
            divergence_items.append({
                **a,
                "claude_sentiment_score": r["claude_sentiment_score"],
                "claude_sentiment_label": r["claude_sentiment_label"],
                "divergence_note": r["divergence_note"],
                "analysis_detail": r.get("analysis_detail"),
                "affected_symbols": r["affected_symbols"],
                "published_at": _short_time(a.get("published_at", "")),
            })

    for a in all_articles:
        a["published_at_short"] = _short_time(a.get("published_at", ""))

    tpl_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(tpl_dir)),
                      autoescape=select_autoescape(["html"]))
    compliance_ctx = config.get("compliance", {}) or {}
    ctx = {
        "run_date": raw.get("run_at", "")[:10],
        "run_time": raw.get("run_at", "")[11:19],
        "window_hours": raw.get("window_hours", 24),
        "window_start": raw.get("window_start"),
        "window_end": raw.get("window_end"),
        "symbols": symbols,
        "summary_mode": mode == "summary",
        "symbols_summary": symbols_summary,
        "symbols_detail": symbols_detail if mode != "summary" else [],
        "top_events": top_events,
        "sources_status": sources_status,
        "category_dist": cand.get("stats", {}).get("by_category", {}),
        "source_dist": cand.get("stats", {}).get("by_source_api", {}),
        "total_raw": cand.get("stats", {}).get("total_raw", 0),
        "all_articles": all_articles if mode != "summary" else [],
        "alerts": alerts,
        "divergence_items": divergence_items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_label": compliance_ctx.get(
            "report_label", "仅供研究参考 — 不构成投资建议"
        ),
        "org_name": compliance_ctx.get("org_name", ""),
        "data_source_version": compliance_ctx.get("data_source_version", "v1"),
        "model_version": compliance_ctx.get("model_version", "claude-opus-4-7"),
        "review_status": compliance_ctx.get(
            "review_status", "AUTO（自动生成，未经人工复核）"
        ),
        "filter_rewrites_count": len(filter_stats.rewrites),
        "filter_blocks_count": len(filter_stats.blocked),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stem = now.strftime("%H%M") + "-sentiment-report"
    md_path = output_dir / f"{stem}.md"
    html_path = output_dir / f"{stem}.html"
    ctx["md_link"] = md_path.name

    md_path.write_text(env.get_template("report.md.j2").render(**ctx))
    html_path.write_text(env.get_template("report.html.j2").render(**ctx))

    alerts_path = output_dir / "alerts.json"
    alerts_path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2))

    notify(alerts, {"md": md_path, "html": html_path}, config)

    return {
        "md": md_path,
        "html": html_path,
        "alerts": alerts_path,
        "_filter_stats": filter_stats,
        "_alerts_data": alerts,
    }


def main() -> int:
    import time
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--reviewed", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--mode", choices=["full", "summary"], default="full")
    p.add_argument("--no-strict-filter", action="store_true",
                   help="敏感词硬禁用命中时不抛错（仅记录），调试用")
    p.add_argument("--no-audit", action="store_true",
                   help="不写 audit.log（默认会写到 ~/.forex-sentiment/audit.log）")
    args = p.parse_args()

    t0 = time.time()
    prompt_dir = Path(__file__).parent / "prompts"

    cfg = load_config()
    paths: dict = {}
    filter_stats = None
    alerts_data: list[dict] = []
    exit_code = 0
    notes = ""

    try:
        paths = run_render(
            raw_path=args.raw, candidates_path=args.candidates,
            reviewed_path=args.reviewed, output_dir=args.output_dir,
            config=cfg, mode=args.mode,
            strict_filter=not args.no_strict_filter,
        )
        filter_stats = paths.get("_filter_stats")
        alerts_data = paths.get("_alerts_data") or []
    except HardBlockError as e:
        print(f"[BLOCK] 敏感词过滤拦截: {e}", file=sys.stderr)
        filter_stats = e.stats
        exit_code = 3
        notes = "hard_block_intercepted"
    except ValueError as e:
        print(f"[BLOCK] 内容过滤拦截: {e}", file=sys.stderr)
        exit_code = 3
        notes = f"value_error: {e}"

    if not args.no_audit:
        rec = make_record(
            config=cfg,
            model_id=(cfg.get("compliance", {}) or {}).get("model_version", "claude-opus-4-7"),
            prompt_dir=prompt_dir,
            raw_path=args.raw, candidates_path=args.candidates,
            reviewed_path=args.reviewed,
            report_md_path=paths.get("md"),
            report_html_path=paths.get("html"),
            alerts_path=paths.get("alerts"),
            filter_stats=filter_stats,
            alerts=alerts_data,
            exit_code=exit_code,
            duration_ms=int((time.time() - t0) * 1000),
            notes=notes,
        )
        audit_path = write_record(rec)
        print(f"  Audit: {audit_path} (run_id={rec.run_id})")

    if exit_code != 0:
        return exit_code

    print(f"Report generated:\n  MD:    {paths['md']}\n  HTML:  {paths['html']}\n  Alerts:{paths['alerts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
