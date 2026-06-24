# 贡献指南

感谢参与 Forex Sentiment Monitor！

## 开发环境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -q
```

## 加一个新数据源

数据源 client 的契约非常简单——写一个 `async def fetch_X(...)`，返回统一结构：

```python
{
  "ok": bool,                # 本源是否成功（部分成功也算 ok）
  "count": int,              # 文章数
  "rate_limit_hit": bool,    # 是否触发限流（用于重试退避）
  "error": str | None,       # 错误说明
  "articles": [ { ...统一字段... } ],
}
```

每篇 article 的统一字段：

```python
{
  "id": "<sha1(url)>",
  "source_api": "yoursource",
  "source_name": "...",
  "title": "...",
  "summary": "...",
  "url": "...",
  "published_at": "ISO8601",
  "tickers": ["BTC", ...],          # 可留空，aggregate 会用关键词补
  "api_sentiment_score": float|None, # 没有就 None，VADER 会兜底
  "api_sentiment_label": str|None,
  "relevance": 0.5,
  "category": "news",
}
```

然后：
1. 在 `scripts/clients/yoursource.py` 实现
2. 在 `scripts/fetch_news.py` 的 `run_fetch` 里接一段（参考 gdelt/rss 的写法）
3. 在 `templates/default_config.yaml` 的 `sources` 加一节
4. 加测试到 `tests/`

**优先考虑无需 key 的免费源**——它们能让用户开箱即用。

## 代码风格

- 跟随现有代码风格（无额外 formatter 强制）
- 新功能配测试；`pytest tests/ -q` 必须全绿
- 不要提交任何真实 API key / `.env` / 缓存数据

## 合规红线

本项目是研究工具，**不得**加入任何会输出"买入/卖出/必涨/保证收益"等投资建议性质的功能。敏感词过滤（`scripts/prompts/sensitive_words.yaml`）就是为此存在的，PR 不要削弱它。
