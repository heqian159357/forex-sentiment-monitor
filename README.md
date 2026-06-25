# Forex Sentiment Monitor

> 多源新闻情绪监控，面向外汇 / 贵金属 / 加密货币。一句话触发，自动产出带「行业视角传导链」的舆情研判报告（Markdown + HTML），并写入可审计的决策日志。

**开箱即用，无需任何 API key** —— 默认数据源 GDELT 2.0 + 公开 RSS 完全免费。需要更多覆盖时，可选接入 Alpha Vantage / Finnhub / NewsAPI / CryptoPanic。

> ⚠️ **免责**：本工具仅供研究与教育用途，**不构成投资建议**。详见 [LICENSE](LICENSE) 末尾的金融免责声明。

---

## ✨ 特性

- **6 个数据源**，其中 2 个（GDELT + RSS）无需 key、默认启用
- **行业视角情绪复核**：用 LLM 把算法情绪分纠偏，输出 `X → Y → Z` 因果传导链，而非简单复述新闻
- **分歧检测**：标记「算法情绪分」与「行业视角」的背离，并强制解释——分歧本身是高价值信号
- **按品种深度解读**：聚合到 symbol 级别，给出主导逻辑 + 关键信号
- **内容过滤**：可配置敏感词二级过滤（硬禁用拦截 / 软改写）
- **决策链路审计**：每次运行写 append-only 的 `audit.log`（含输入输出文件 sha256、prompt 哈希，防事后篡改）
- **Markdown + HTML 报告**，自带中性免责声明与数据源 attribution

## 📄 样例报告

看看完整产出长什么样（真实数据，含行业视角传导链 + 分歧检测 + 分品种深度解读）：

- [docs/sample-report/sample-report.md](docs/sample-report/sample-report.md)（Markdown）
- [docs/sample-report/sample-report.html](docs/sample-report/sample-report.html)（下载后用浏览器打开，带样式与水印）

## 🤖 LLM 分析用谁的算力？（重要）

本工具的 LLM 复核（行业视角传导链、分品种深度解读）**借助你自己的 Claude Code 完成，无需单独配置任何 LLM API key**：

| 你的用法 | 完整分析（传导链 + 深度解读） |
|---|---|
| 在 **Claude Code** 里用本 skill / plugin | ✅ Claude 自己执行复核，用的是**你自己的 Claude 订阅** |
| **纯命令行**（不经 Claude Code） | ⚠️ 仅 VADER 算法兜底打分；要补 LLM 复核需自行接入任意 LLM 生成 `reviewed.json` |

新闻数据源的 API key（Alpha Vantage / Finnhub / NewsAPI / CryptoPanic）也都是**填你自己的**、且全部可选——默认免费源 GDELT + RSS 无需任何 key。

## 🚀 快速开始

### 方式 1：作为 Claude Code Skill（推荐）

```bash
git clone https://github.com/heqian159357/forex-sentiment-monitor.git ~/.claude/skills/forex-sentiment-monitor
cd ~/.claude/skills/forex-sentiment-monitor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -c "from scripts.config import bootstrap_runtime_dir; bootstrap_runtime_dir()"
```

然后在 Claude Code 里说：「跑一下舆情监控」/「sentiment report for BTC and gold」。

### 方式 2：作为 Claude Code Plugin

本仓库自带 `.claude-plugin/marketplace.json`，可作为单插件 marketplace 安装：

```
/plugin marketplace add heqian159357/forex-sentiment-monitor
/plugin install forex-sentiment-monitor
```

### 方式 3：纯命令行（不依赖 Claude Code）

```bash
source .venv/bin/activate
TODAY=$(date +%Y-%m-%d)
mkdir -p ~/.forex-sentiment/cache/$TODAY

# 1. 抓取（默认仅免费源 GDELT + RSS）
python -m scripts.fetch_news --hours 24 --output ~/.forex-sentiment/cache/$TODAY/raw_news.json

# 2. 聚合去重 + VADER 兜底打分
python -m scripts.aggregate \
  --input ~/.forex-sentiment/cache/$TODAY/raw_news.json \
  --output ~/.forex-sentiment/cache/$TODAY/candidates.json

# 3. （可选）LLM 复核 → reviewed.json；纯 CLI 可跳过，render 会回退到 API-only 打分
echo '{"reviewed_at":"","self_check_log":"","reviews":[]}' > ~/.forex-sentiment/cache/$TODAY/reviewed.json

# 4. 渲染报告
python -m scripts.render_report \
  --raw ~/.forex-sentiment/cache/$TODAY/raw_news.json \
  --candidates ~/.forex-sentiment/cache/$TODAY/candidates.json \
  --reviewed ~/.forex-sentiment/cache/$TODAY/reviewed.json \
  --output-dir ~/forex-sentiment-reports/$TODAY/
```

## 📊 数据源

| 源 | 是否需要 key | 默认 | 说明 |
|---|---|---|---|
| **GDELT 2.0** | ❌ 无需 | ✅ 启用 | 全球新闻，免费且含商用授权 |
| **RSS 直采** | ❌ 无需 | ✅ 启用 | CoinDesk / Cointelegraph / Investing / WSJ 等公开 RSS |
| Alpha Vantage | ✅ free tier | ⬜ 关闭 | 自带新闻情绪分 |
| Finnhub | ✅ free tier | ⬜ 关闭 | 多类目新闻 |
| NewsAPI | ✅ free tier | ⬜ 关闭 | 通用新闻检索 |
| CryptoPanic | ✅ free token | ⬜ 关闭 | 加密专属，自带多空投票 |

启用付费源：在 `~/.forex-sentiment/.env` 填 key，并在 `~/.forex-sentiment/config.yaml` 把对应 `sources.<name>.enabled` 改为 `true`。

## ⚙️ 配置

默认配置见 [templates/default_config.yaml](templates/default_config.yaml)。常用项：

```yaml
default_symbols: [BTC, ETH, XAUUSD, XAGUSD, EURUSD, USDJPY, GBPUSD, WTI]
default_window_hours: 24
score_weights: { claude: 0.6, api_only: 0.4 }   # 综合分 = 0.6 LLM + 0.4 算法
compliance:
  org_name: ""                                    # 留空则报告不显示组织名
  report_label: "仅供研究参考 — 不构成投资建议"
  filter:
    enabled: true                                 # 敏感词过滤开关
    strict: true                                  # 命中硬禁用即拦截（退出码 3）
```

## 🏗️ 架构

```
fetch_news.py        并发抓取 6 源（含重试 / 退出码）
  └─ clients/{gdelt,rss,cryptopanic,alpha_vantage,finnhub,newsapi}.py
aggregate.py         去重 + 关键词富集 + VADER 兜底打分 + TOP-N 选取
prompts/sentiment_review.md    LLM 行业视角复核（6 点自检）
prompts/symbol_deep_dive.md    按品种深度解读
content_filter.py    敏感词二级过滤（硬禁用 / 软改写）
render_report.py     综合分 + 告警 + Jinja2 渲染 MD/HTML
audit.py             append-only 决策链路审计日志
```

## 🌐 部署到其他平台

除 Claude Code 外，本工具的流水线也可移植到 Coze / Dify 等平台：

- **Dify（自托管）**：仓库自带可导入的工作流 DSL → [integrations/dify/](integrations/dify/)
- **Coze / 其他**：移植映射与分步骤见 [docs/PLATFORMS.md](docs/PLATFORMS.md)

> 进 Claude 社区插件市场（可选）：`claude plugin validate .` 通过后，到 https://platform.claude.com/plugins/submit 提交。详见 PLATFORMS.md §2。

## 🧪 测试

```bash
source .venv/bin/activate
pytest tests/ -q          # 25 个测试
```

## 🤝 贡献

欢迎 PR！加新数据源只需在 `scripts/clients/` 写一个返回统一结构 `{ok, count, rate_limit_hit, error, articles}` 的 `fetch_X()`，再在 `fetch_news.py` 接一行。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 📄 许可

[MIT](LICENSE) · 含金融免责声明。
