# Per-Symbol Deep Dive (final step)

After `render_report.py` finishes, produce a **per-symbol narrative interpretation** as the final user-facing output. This is the highest-value deliverable — the MD/HTML report lists scores, this step explains *why they matter and what to do*.

## Input

- `~/.forex-sentiment/cache/$TODAY/reviewed.json` — the per-article reviews you just wrote
- `~/.forex-sentiment/cache/$TODAY/candidates.json` — source context
- `~/forex-sentiment-reports/$TODAY/alerts.json` — triggered alerts

## Audience

The user is a forex/crypto exchange PM (see auto-memory). Frame insights around **product / risk / deposit-intent / user behavior** — not around "should I buy XYZ".

## Output structure (Markdown, printed directly in chat — do NOT write a new file)

Lead with the run metadata and an overall conclusion, then one section per symbol that appears in `affected_symbols` across the reviews. Only include symbols that got at least one review hit — do not pad with "no news" entries.

```
## 今日舆情深度解读（窗口：过去 {hours} 小时）

### 报告文件
- MD: <path>
- HTML: <path>
- 数据源状态：<per-source ✅/⚠️/❌>

### 综合结论（1-3 句）
<一句定调：今天政策面/事件面整体偏暖/偏冷/中性，以及这个"偏X"的真正含义——不是价格方向而是结构含义>

---

### 🟢/🟡/🔴 {SYMBOL} — 综合分 {score} ({label})

**主导逻辑（一句话）**：<X → Y → Z 的传导链>

**关键信号**（2-5 条，按重要性排序）：
1. **<事件标题/主语>** — <50-120字：事件 + 政策/业务含义 + 传导路径>
2. **<事件标题/主语>** — <...>
3. ...

**交叉传导**（可选，仅在该 symbol 与其他 symbol 存在明显联动时出现）：
- <一句话说明：例如 "与 XAUUSD 呈现反向相关，原因是 ..."

**对业务的直接启发**（1-3 条，写给 PM/风控/运营）：
1. <具体可落地的观察，不写"应该买"这种交易建议>
2. ...

---

（重复每个 symbol）

### 告警
- <从 alerts.json 读取；若无则写"无"; data_source_failure 类告警也列出>
```

## Rules

1. **按 symbol 分组**，不要按文章分组。同一篇文章若影响多个 symbol，在每个相关 symbol 下都引用，但措辞要针对该 symbol 的传导角度。
2. **综合分计算**：对每个 symbol，取所有 `affected_symbols` 命中该 symbol 的 reviews 的 `claude_sentiment_score` 加权平均（impact_level 权重：high=3, medium=2, low=1）。四舍五入到小数点后两位。标签按 sentiment_review.md 的区间判定。
3. **🟢/🟡/🔴 emoji 规则**：score ≥ 0.2 用 🟢；-0.2 < score < 0.2 用 🟡；score ≤ -0.2 用 🔴。
4. **关键信号必须带传导逻辑**，不能只复述新闻。模仿 industry_reason 的"X → Y → Z"结构，但展开为自然语言。
5. **对业务的启发要具体**，避免空话。好的例子：
   - ❌ "要关注监管动向" （废话）
   - ✅ "州级银行协会集体接入稳定币是 SEC 行动前 2-4 季度的领先信号，可以把'州级银行公告'作为入金画像的新特征"
6. **整体结论要讲结构不讲方向**。"今天整体偏暖" 要紧跟一句 "偏暖含义不是放水，而是合规路径收敛"——这种二阶信息才是真正的价值。
7. **禁止交易建议**。不出现"建议做多/空"、"目标价 X"、"止损 Y" 等语言。这是业务解读不是交易信号。
8. **无事件的 symbol 直接省略**。不要写"BTC 今日无重大事件"这种填充段落。
9. **告警里的 `data_source_failure` 必须出现在"告警"区块**，让用户知道数据覆盖度的局限。

## Style

- 中文输出（与用户的对话语言一致）
- 每个 symbol 一屏左右，不要过长
- 用 **粗体** 标出关键主语和政策动作
- emoji 仅用于 symbol 标题和告警严重度，正文不用
