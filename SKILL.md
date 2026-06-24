---
name: forex-sentiment-monitor
description: Use when user explicitly requests sentiment monitoring, news scanning, or market mood analysis for forex, precious metals, or cryptocurrency. Triggers include "跑舆情监控", "sentiment report", "扫一下新闻", "看看今天的舆情", "analyze market news for BTC/gold/EURUSD". Generates a Markdown + HTML report covering news sources, sentiment direction, and affected symbols.
---

# Forex Sentiment Monitor

## Overview

Multi-source sentiment monitoring for forex, precious metals, and cryptocurrency. Works out of the box with **two key-less free sources** — GDELT 2.0 and public RSS — and can optionally blend in Alpha Vantage / Finnhub / NewsAPI / CryptoPanic when you provide API keys. Blends API sentiment with Claude's industry-view review; outputs Markdown + HTML reports plus an append-only audit log.

## When to Use

- User explicitly asks for "舆情监控 / sentiment report / 扫新闻 / market mood"
- User requests analysis of specific symbols for the day/week
- **Do NOT** trigger on casual questions like "BTC 今天怎么样" unless the user specifies a report

## Prerequisites (run once)

1. **No API key required for the default setup** — GDELT + RSS work out of the box. To enable the optional paid sources, copy `.env.example` to `~/.forex-sentiment/.env`, fill in the keys you have, and set the matching source to `enabled: true` in `config.yaml`.
2. Ensure `~/.forex-sentiment/config.yaml` exists. Run this to auto-copy the template:

```bash
cd ~/.claude/skills/forex-sentiment-monitor
source .venv/bin/activate
python -c "from scripts.config import bootstrap_runtime_dir; bootstrap_runtime_dir()"
```

3. Ensure Python deps are installed:

```bash
cd ~/.claude/skills/forex-sentiment-monitor
source .venv/bin/activate
pip install -r requirements.txt
```

## Execution Flow

### Step 1 — Parse user intent

From the user message, extract:
- `hours` (default 24, from config.yaml's `default_window_hours`)
- `symbols` (default from config.yaml; user may specify "only BTC and XAUUSD")
- `mode` ("full" by default; "summary" if user wants the short version)

### Step 2 — Fetch

```bash
cd ~/.claude/skills/forex-sentiment-monitor
source .venv/bin/activate
TODAY=$(date +%Y-%m-%d)
mkdir -p ~/.forex-sentiment/cache/$TODAY
python -m scripts.fetch_news \
  --hours {hours} \
  --symbols {symbols_csv} \
  --output ~/.forex-sentiment/cache/$TODAY/raw_news.json
```

Check the exit code:
- `0` → all sources OK
- `1` → partial failure; continue but note in final report
- `2` → all sources failed; STOP and tell the user which source failed and why

### Step 3 — Aggregate

```bash
python -m scripts.aggregate \
  --input ~/.forex-sentiment/cache/$TODAY/raw_news.json \
  --output ~/.forex-sentiment/cache/$TODAY/candidates.json
```

Read `candidates.json` stats and brief the user:
"抓到 N 条新闻，去重后 M 条，挑出 K 条送复核"

### Step 4 — Claude sentiment review

1. Read `~/.forex-sentiment/cache/$TODAY/candidates.json`
2. Read `~/.claude/skills/forex-sentiment-monitor/scripts/prompts/sentiment_review.md`
3. Apply the industry-view rules in the prompt to score each candidate
4. **Run the 6-point self-check** described in the prompt (symbol legality, score↔label consistency, cross-symbol coherence, impact↔score strength, divergence flag consistency, industry_reason quality)
5. Output the self-check log to the user
6. Use the Write tool to save `~/.forex-sentiment/cache/$TODAY/reviewed.json`

If Claude's JSON output is malformed, retry once. If still malformed, continue to Step 5 — `render_report.py` will fall back to API-only scoring and flag the issue in the report.

### Step 5 — Render

```bash
python -m scripts.render_report \
  --raw ~/.forex-sentiment/cache/$TODAY/raw_news.json \
  --candidates ~/.forex-sentiment/cache/$TODAY/candidates.json \
  --reviewed ~/.forex-sentiment/cache/$TODAY/reviewed.json \
  --output-dir ~/forex-sentiment-reports/$TODAY/ \
  --mode {mode}
```

The report carries a neutral "仅供研究参考 — 不构成投资建议" label and a full disclaimer block. Customize `compliance.report_label` / `org_name` in `config.yaml`.

### Step 6 — Report to user (brief)

Print a short confirmation with:
- Paths to MD and HTML
- Data source status (✅/⚠️/❌ per source)
- Any alerts triggered this run (read from alerts.json)

Keep this step to under 8 lines. The real deliverable is Step 7.

### Step 7 — Per-symbol deep dive (REQUIRED, final output)

This is the most valuable part of the run — do not skip it.

1. Read `~/.claude/skills/forex-sentiment-monitor/scripts/prompts/symbol_deep_dive.md`
2. Read `~/.forex-sentiment/cache/$TODAY/reviewed.json` and `~/forex-sentiment-reports/$TODAY/alerts.json`
3. Produce a per-symbol narrative interpretation directly in the chat (do NOT write a new file)
4. Group by symbol (not by article), computing each symbol's aggregate score as an impact-weighted average of its hits (high=3, medium=2, low=1)
5. Follow the output structure and rules in `symbol_deep_dive.md` exactly — especially:
   - Explain *structural* meaning (e.g. "偏暖含义不是放水而是合规路径收敛"), not just direction
   - Every 关键信号 must include an X→Y→Z transmission chain
   - 对业务的直接启发 must be concrete and PM-relevant; no trading advice
   - Skip symbols with no review hits entirely

## Audit Log（决策链路追溯）

每次 `render_report.py` 运行都会向 `~/.forex-sentiment/audit.log` 追加一条 JSONL 记录（除非传 `--no-audit`）。文件权限 600，append-only，用于合规审计。

**单条记录字段：**

| 字段 | 含义 |
|---|---|
| `ts / run_id / actor / host` | 谁、何时、在哪台机器触发的 |
| `skill_version / model_id` | 代码版本 + LLM 模型版本 |
| `config_hash` | config.yaml 的 sha256（排除 api_keys） |
| `prompt_versions` | 每个 prompt/词库文件的 sha256（prompt 改了一定能溯源） |
| `inputs.{raw_news, candidates, reviewed}` | 输入文件 sha256（防事后篡改） |
| `outputs.{report_md, report_html, alerts}` | 输出文件 sha256（拦截路径下为 null） |
| `filter_summary.{hard_blocks_count, soft_rewrites_count}` | 命中计数 |
| `filter_details.hard_blocks[]` | 每条命中的 review_id / field / word / snippet |
| `filter_details.soft_rewrites[]` | 每条改写的 review_id / field / from / to |
| `alerts[]` | 本次告警明细 |
| `exit_code / duration_ms / notes` | 结束态、耗时、备注（如 hard_block_intercepted） |

**审计回放路径**：从最终报告 → run_id → audit.log 一行 → 输入文件 sha256 → 复盘。

## Error Handling

- All sources fail (exit 2) → stop, no report; tell user which sources failed (network? GDELT rate-limit?)
- Single source fails (exit 1) → continue; report marks source status ❌
- Claude review JSON malformed → retry once; if still fails, render_report falls back and flags
- Default free sources (GDELT + RSS) need no key; if you enabled a paid source but its key is missing, that source is skipped with a status note

## Red Flags — STOP and ask the user

- User says "every day / 定时 / cron" → phase-2 agent feature, tell them v1 is manual only
- User asks for WeChat / email push → phase-2 agent feature
- User asks for analysis of symbols not in default list (AUDUSD, SOL, etc.) → ask whether to extend default list or just run one-off

## Phase-2 Agent Hooks (not implemented in v1, reserved)

- `alerts.json` is always written (even empty) — future agent reads this to decide push
- `notify.py` has a hook — future agent fills in push channels (WeChat webhook, SMTP)
- All scripts accept CLI args — future agent invokes them via cron
- Exit codes (0/1/2) are consistent — future agent checks them for error handling
