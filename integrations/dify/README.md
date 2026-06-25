# Dify 集成

把 Forex Sentiment Monitor 的核心流程（抓取 → 解析 → 情绪分析）作为一个 Dify Workflow 运行。适合**自托管 Dify**——数据不出内网，契合金融场景。

## 文件

- [`forex-sentiment-workflow.yml`](forex-sentiment-workflow.yml) — 可导入的 Dify Workflow DSL（5 节点：开始 → GDELT 抓取 → 去重匹配 → LLM 情绪分析 → 结束）

## 导入步骤

1. **部署 Dify**（若尚未）：
   ```bash
   git clone https://github.com/langgenius/dify.git
   cd dify/docker && cp .env.example .env && docker compose up -d
   # 浏览器打开 http://localhost
   ```

2. **导入工作流**：Dify 控制台 → 「创建应用」→「导入 DSL 文件」→ 上传 `forex-sentiment-workflow.yml`。

3. **⚠️ 必改：LLM 节点的模型**
   DSL 里 `llm1` 节点默认写的是 `langgenius/openai/openai` + `gpt-4o`。导入后**必须**改成你 Dify 工作区里实际安装并配置好 key 的模型，否则会报「模型不存在」：
   - 点开 `行业视角情绪分析` 节点 → 模型下拉选你自己的（OpenAI / Anthropic Claude / 通义 / DeepSeek 等）
   - 这一步用的是**你自己的 LLM API key**（在 Dify「设置 → 模型供应商」里配）

4. **运行**：点右上角「运行」，输入：
   - `监控品种`：如 `BTC,ETH,XAUUSD`
   - `时间窗`：如 `24`

   输出 `report` 字段即为带情绪分 + 传导链的 JSON 研判。

## 与完整版 skill 的差异

这个 Dify workflow 是**精简移植**，覆盖核心链路；完整版 skill（GitHub 仓库）额外有：
- 6 个数据源（这里只用免费的 GDELT；可再加 http-request 节点接 RSS/Finnhub 等）
- VADER 算法兜底打分（与 LLM 融合的 0.6/0.4 综合分）
- 敏感词二级过滤、决策链路审计 audit.log
- Markdown + HTML 报告渲染

如需在 Dify 里补齐，可把对应逻辑写进新的 `code` 节点。

## 注意事项

1. **GDELT 抓取必须用 http-request 节点**，不要放进 code 节点——Dify 的 code 沙箱默认禁外网，`requests` 抓不到数据。本 DSL 已正确用 http-request 抓、code 只做解析。
2. **DSL 版本兼容**：文件标 `version: 0.6.0`。导入到更新版本的 Dify 只会提示警告、仍可用。若导入失败，最稳的办法是：在你的 Dify 里手动拖一个 `开始→HTTP→代码→LLM→结束` 的工作流，导出 DSL 作为模板，再把本文件的业务逻辑（params / code / prompt）填进去。
3. **合规**：本工作流默认带「不构成投资建议」的 system 提示与免责。请勿移除；金融舆情产出对外发布需符合所在辖区监管要求。
