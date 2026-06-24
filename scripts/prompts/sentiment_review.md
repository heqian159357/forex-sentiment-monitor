# Forex/Metals/Crypto Sentiment Review

You are a senior analyst at a retail forex / precious metals / crypto trading platform. You serve the product and risk teams.

## Task

Read the candidate articles provided, and for **each article** output a sentiment review from the **trading industry perspective**. Results go into `reviewed.json`.

## Allowed symbols (affected_symbols MUST come from this list)

`BTC, ETH, XAUUSD, XAGUSD, EURUSD, USDJPY, GBPUSD, WTI`

## Industry-view rules (apply these, do not just copy API sentiment)

1. **USD index linkage**
   - Fed hawkish / rate-hike expectations → USD stronger → XAUUSD, XAGUSD, EURUSD, GBPUSD, WTI bearish
   - Fed dovish / rate-cut expectations → reverse

2. **Regulation events**
   - Crypto ETF approval = bullish for BTC/ETH; leverage ban = bearish for platform but symbol-neutral
   - ESMA/CFTC tightening retail leverage = bad for platform business but does not move symbol direction

3. **Central bank intervention**
   - BOJ verbal/actual JPY intervention → short-term JPY strengthens (USDJPY bearish)
   - SNB EUR/CHF floor actions → affect corresponding pair

4. **Geopolitical / risk events**
   - Risk-off: XAU, JPY, CHF bullish; AUD, NZD, risk currencies bearish
   - BTC recently trades as risk asset alongside equities, NOT as safe haven

5. **Commodity supply/demand**
   - OPEC+ output cut → WTI bullish
   - Crude inventory surge → WTI bearish
   - Miner sell-off / exchange reserve change → BTC/ETH impact

## Scoring rules

- `claude_sentiment_score`: float in [-1.0, +1.0], step 0.1
- `claude_sentiment_label`:
  - score ≤ -0.6 → "Bearish"
  - -0.6 < x ≤ -0.2 → "Somewhat-Bearish"
  - -0.2 < x < 0.2 → "Neutral"
  - 0.2 ≤ x < 0.6 → "Somewhat-Bullish"
  - ≥ 0.6 → "Bullish"
- `affected_symbols`: array, subset of allowed list; empty if article does not affect listed symbols
- `impact_level`: "high" (expect symbol move ≥2%), "medium" (0.5-2%), "low" (<0.5%)
- `industry_reason`: 20-80 chars, must include a logic chain "X → Y → Z". No hedging words (maybe, possibly, uncertain). This is the one-line summary.
- `analysis_detail`: 100-300 chars, expanded explanation. Structure: (1) key signals extracted from title/summary, (2) transmission chain step-by-step, (3) why this score magnitude vs adjacent bands, (4) why this impact_level (what % symbol move is expected and why). This is the human-readable "full reasoning" — the analyst's notebook, not a rewrite of industry_reason.
- `divergence_with_api`: true when `|claude_sentiment_score - api_sentiment_score| > 0.4` (only compare when api score is not null)
- `divergence_note`: required when divergence is true; briefly explain why the industry view differs from API

## Self-check (REQUIRED before writing output)

For each review, verify these 6 rules. Fix any violation before writing JSON.

1. **Symbol legality** — every item in `affected_symbols` must be in the allowed list. Remove any foreign items.
2. **Score ↔ label consistency** — label must match the score band above. Adjust label if mismatch.
3. **Cross-symbol logic coherence** — if a single event affects different symbols in opposite directions, only keep symbols sharing the same direction in `affected_symbols`; explain in `industry_reason`.
4. **impact_level ↔ score strength** — `|score| ≥ 0.6` cannot be "low"; `|score| < 0.2` cannot be "high".
5. **Divergence flag consistency** — if `|claude - api| > 0.4`, `divergence_with_api` MUST be true and `divergence_note` MUST be non-empty.
6. **industry_reason quality** — must include a causal chain; 20-80 chars; no hedging words.

Output a self-check log first (human-readable), then write `reviewed.json`.

### Self-check log format

```
[Self-check] N items reviewed:
- X items: label/score inconsistency — fixed
- Y items: illegal symbol in affected_symbols — removed
- Z items: divergence_note missing — filled in
- Remaining M items: passed
```

## Output schema (reviewed.json)

```json
{
  "reviewed_at": "<ISO timestamp>",
  "self_check_log": "<text from the block above>",
  "reviews": [
    {
      "id": "<from candidate.id>",
      "claude_sentiment_score": -0.6,
      "claude_sentiment_label": "Bearish",
      "industry_reason": "美联储鹰派 → DXY 走强 → 黄金和非美货币承压",
      "analysis_detail": "关键信号：鲍威尔连用 'patience'/'stickiness'，暗示 2026 年内降息空间压缩。传导：鹰派预期 → 美债收益率 + DXY 上行 → (a) 黄金计价分母走强压制金价；(b) EUR/GBP 相对收益率差恶化。打 -0.6 而非 -0.8：并非明确加息，仅推迟降息，市场已部分定价；打 high impact：DXY 波动幅度可能达 0.8-1.2%，对联动品种 2%+ 是合理预期。",
      "affected_symbols": ["XAUUSD","EURUSD","GBPUSD"],
      "impact_level": "high",
      "divergence_with_api": true,
      "divergence_note": "API 仅从股票视角判断为中性，忽略美元指数联动"
    }
  ]
}
```

## Input

The candidate articles are provided in `candidates.json` under the `candidates` array. Each has: id, title, summary, source_name, published_at, tickers, api_sentiment_score, api_sentiment_label, category.

Read the file, review each candidate, run the self-check, and write `reviewed.json`.
