# Forex Sentiment Monitor 平台移植文档

> 本文档说明如何把 Forex Sentiment Monitor 这套「多源新闻情绪监控流水线」从原生 Claude Code Skill 形态，移植到三类外部平台：**GitHub 开源分发**、**Coze / 扣子**、**Dify（开源可自托管）**。
>
> 适用读者：想在自己团队或外部平台复用这条流水线的产品经理 / 工程师。
> 文档目标：给出每个平台的适用场景、改造工作量评估、关键映射表、分步骤说明、坑点，以及一份金融合规提醒。

---

## 0. 原始流水线回顾（移植的基准）

在讨论移植之前，先把要搬运的「东西」定义清楚。本项目本质是一条 4 步流水线，外加报告渲染与审计：

| 步骤 | 脚本 / 文件 | 职责 | 是否依赖 LLM |
|---|---|---|---|
| ① fetch_news | `scripts/fetch_news.py` + `scripts/clients/*` | 并发抓取多源新闻。默认免费源 **GDELT 2.0 DOC API**（`clients/gdelt.py`，无需 key）+ **公共 RSS**（`clients/rss.py`）；可选 Alpha Vantage / Finnhub / NewsAPI / CryptoPanic（需 key）。输出 `raw_news.json`，并用退出码 0/1/2 表达全成功 / 部分失败 / 全失败 | 否 |
| ② aggregate | `scripts/aggregate.py` | URL + 标题 Jaccard 去重；关键词富集 ticker（把标题映射到 BTC/XAUUSD 等品种）；对没有 API 情绪分的英文条目用 **VADER + 金融词库兜底打分**；按相关度/影响选 TOP-N，输出 `candidates.json` | 否（VADER 是算法，非 LLM） |
| ③ LLM 行业视角复核 | `scripts/prompts/sentiment_review.md` | 把候选新闻送 LLM，按「外汇交易所行业视角」打分，输出每条的 `score / label / impact_level / 传导链 reason`，并跑 6 点自检（品种合法性、分数↔标签一致、跨品种连贯、影响↔分数强度、背离标记一致、reason 质量），输出 `reviewed.json` | **是** |
| ④ render_report | `scripts/render_report.py` + `scripts/content_filter.py` | 综合分 = **0.6 × LLM 分 + 0.4 × 算法分**（权重见 `config.yaml` 的 `score_weights`）；敏感词**硬禁用 + 软改写**过滤（词表 `prompts/sensitive_words.yaml`）；生成 Markdown + HTML 报告；向 `~/.forex-sentiment/audit.log` 追加一条 JSONL 审计记录 | 否 |

默认 8 个品种：BTC / ETH / XAUUSD / XAGUSD / EURUSD / USDJPY / GBPUSD / WTI。

**移植的核心难点**：原项目是「Claude Code 充当编排器（agent）+ Python 脚本充当工具」的混合形态——第 ③ 步的 LLM 推理其实是 Claude Code 主对话直接做的，不是脚本里调的 API。移植到工作流平台时，必须把这条「对话式编排」显式拆成**确定性工作流节点**。这是所有移植工作量的主要来源。

---

## 1. 平台选型对比表

| 维度 | Claude Code（原生 Skill） | GitHub 开源分发 | Coze / 扣子 | Dify（自托管） |
|---|---|---|---|---|
| **改造量** | 无（原生形态） | **小**（仅打包/clone） | **大**（重写为插件+工作流） | **中**（脚本搬进代码节点） |
| **是否需自部署** | 否（本地装 Claude Code 即可） | 否（用户各自 clone） | 否（云托管 SaaS） | **是**（Docker/K8s 自托管，亦有云版） |
| **编排者** | Claude Code 主对话 | 同左（分发后仍是 Claude Code） | Coze Workflow 引擎 | Dify Workflow 引擎 |
| **LLM 来源** | Claude（本机订阅） | 同左 | 豆包/扣子内置模型，国际版可接 OpenAI 等 | 自配（可接 Claude / GPT / 本地模型） |
| **适合受众** | 个人 / 已用 Claude Code 的团队 | 开源社区、内部团队复用 | 想做对话机器人 / Bot 商店分发 | 金融/企业内部、强数据隐私场景 |
| **数据隐私** | 本地，数据较可控 | 取决于使用者 | **数据过字节云**，公开市场有暴露风险 | **可全内网，数据不出企业**，最佳 |
| **典型产物** | 本地 MD/HTML 报告 | 同左 | Bot / API / 工作流 | Workflow API / 内嵌应用 |

**一句话选型建议**：
- 只想自己或小团队用 → 留在 **Claude Code**，最省事。
- 想让别人也能装、做版本管理 → **GitHub 分发 / Plugin**。
- 想做成对话 Bot、给非技术用户用 → **Coze**（但注意合规，见文末）。
- 金融场景、数据不能出内网、要审计 → **Dify 自托管**，最契合本项目的合规基因（本项目本来就带 audit.log）。

---

## 2. GitHub 开源仓库分发（改造量：小）

### 适用场景
- 你想把这套 Skill 分享给其他 Claude Code 用户，或在公司内部多台机器复用。
- 不改变流水线本身，只解决「怎么装、怎么更新、怎么版本化」。

### 关键映射表
| 本项目组件 | GitHub / Plugin 概念 |
|---|---|
| 整个 skill 目录 | git 仓库 |
| `SKILL.md` | Skill 入口（Claude Code 自动识别 frontmatter 的 `name`/`description`） |
| `.claude-plugin/plugin.json` | Plugin 清单（name/version/description/repository） |
| `.claude-plugin/marketplace.json` | Marketplace 清单（声明本仓库托管哪些 plugin） |
| `requirements.txt` / `.venv` | 安装期依赖 |
| `config.yaml` / `.env.example` | 运行期配置（用户各自填） |

本仓库**已经具备** `plugin.json` + `marketplace.json`，所以两条分发路径都走得通。

### 方式 A：直接 clone 到 skills 目录（最简单）
```bash
git clone https://github.com/<heqian159357>/forex-sentiment-monitor.git \
  ~/.claude/skills/forex-sentiment-monitor
cd ~/.claude/skills/forex-sentiment-monitor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -c "from scripts.config import bootstrap_runtime_dir; bootstrap_runtime_dir()"
```
之后在 Claude Code 里说「跑舆情监控」即可触发。更新就是 `git pull`。

### 方式 B：作为 Claude Code Plugin / Marketplace 分发
1. 把仓库推到 GitHub（公开或私有皆可，私有需配置 git 凭证）。
2. 让使用方在 Claude Code 内添加 marketplace：
   ```
   /plugin marketplace add <heqian159357>/forex-sentiment-monitor
   ```
   （也可用完整 git URL；本仓库根目录就是 marketplace，`source: "."`。）
3. 安装插件：
   ```
   /plugin install forex-sentiment-monitor@forex-sentiment-marketplace
   ```
   或交互式：`/plugin` 进入菜单 → 选 marketplace → 安装。
4. 安装后 Claude Code 会把 skill 注册进来，按 `SKILL.md` 的触发词工作。

### 坑点
- **`plugin.json` 里的 `heqian159357` 占位符要替换**成真实 GitHub owner，否则 homepage/repository 链接失效。
- **Python 依赖不随 plugin 自动安装**。Plugin 机制分发的是 skill 文件，`pip install -r requirements.txt` 和建 venv 仍需在 `SKILL.md` 的 Prerequisites 里引导用户手动跑（本项目已写好）。
- **API key 千万不要进仓库**。`.env` 放在 `~/.forex-sentiment/`（运行期目录），仓库只提供 `.env.example`。务必确认 `.gitignore` 覆盖了 `.env` 和 `cache/`、`audit.log`。
- **私有仓库分发**给同事时，对方机器要有 git 访问权限（SSH key / token）。
- 版本管理：升级 `plugin.json` 的 `version` 字段并打 tag，方便回滚。

---

## 3. Coze / 扣子（字节）（改造量：大）

### 适用场景
- 你想把舆情能力做成一个**对话机器人 / Bot**，给不会用命令行的同事或客户用。
- 想利用 Coze 的可视化工作流编排、内置模型、定时触发等能力。

### 形态总览
Coze 的核心抽象是 **Bot（智能体）+ Workflow（工作流）+ Plugin（插件）**。本项目的 4 步流水线最自然的映射是：把它整体做成一个 **Workflow**，工作流里挂若干**节点**，对外暴露的「抓新闻」能力做成一个**自定义 Plugin（HTTP 工具）**。

### 关键映射表
| 本项目组件 | Coze 概念 |
|---|---|
| `fetch_news.py` + `clients/gdelt.py` 等 | **自定义 Plugin**：用 HTTP 工具直接调 GDELT DOC API / RSS（或自建一个薄 HTTP 服务包装 Python） |
| `aggregate.py`（去重 + VADER 兜底） | **代码节点（Code Node）**，用 Coze 支持的语言（Python/JS）重写去重与打分 |
| `prompts/sentiment_review.md` | **LLM 节点（大模型节点）** 的 System Prompt / 提示词 |
| 6 点自检 | LLM 节点 prompt 内的自检指令，或追加一个校验**代码节点** |
| `content_filter.py` + `sensitive_words.yaml` | **代码节点**（敏感词硬禁用 + 软改写） |
| `render_report.py`（综合分 0.6/0.4 + 渲染） | **代码节点** 计算综合分 + 输出 Markdown 文本 |
| `audit.log` | 工作流的**数据库节点 / 变量**记录，或调用外部日志 API |
| 8 个默认品种、`config.yaml` | 工作流的**输入参数 / 全局变量** |

### 分步骤说明

**Step 1 — 把 fetch 做成 Plugin（HTTP 工具）**
GDELT 是公开 HTTP JSON API（`https://api.gdeltproject.org/api/v2/doc/doc`，参数 `query/mode=ArtList/format=json/timespan=24h/sort=datedesc`），可以**直接**在 Coze 里用「创建插件 → 基于已有 API / HTTP 请求」的方式登记，无需写代码：
- Method: GET
- URL + query 参数按 `clients/gdelt.py` 里的 `params` 照搬
- 出参 schema 按 GDELT 返回的 `articles[]`（含 `title/url/domain/seendate`）

RSS 源同理，但 RSS 返回 XML，Coze 的 HTTP 工具对 XML 解析较弱，建议**自建一个薄 HTTP 服务**（FastAPI/Flask 把 `fetch_news.py` 包成 `POST /fetch` 接口，返回统一的 `articles[]` JSON），再在 Coze 里把这个服务登记成一个 Plugin。这样并发抓取、退出码、ticker 兜底映射等逻辑可以原样保留，改造最少。

**Step 2 — aggregate 做成代码节点**
把去重（URL + 标题 Jaccard）与 VADER 兜底打分用代码节点重写。注意 Coze 代码节点的运行环境**可能没有 `vaderSentiment` 这个第三方包**——若不可装，两条路：(a) 把 VADER 也并入 Step 1 的自建服务里（推荐）；(b) 在代码节点里用简化的金融词库做规则打分。aggregate 本质是确定性逻辑，搬运直接。

**Step 3 — 情绪复核做成 LLM 节点**
新建一个「大模型节点」，把 `prompts/sentiment_review.md` 的内容贴进 System Prompt，输入是 Step 2 的 `candidates`，要求模型严格输出 JSON（`score/label/impact/reason`）。把 6 点自检写进同一个 prompt 的尾部，或单独再加一个代码节点做格式/一致性校验（对应原项目「JSON 不合法重试一次」的容错）。

**Step 4 — render 做成代码节点**
代码节点计算综合分 `0.6 × LLM + 0.4 × 算法`，跑敏感词过滤，拼出 Markdown 文本作为工作流输出。Coze 工作流可把该文本回传给 Bot 对话气泡，或写入数据库节点。

**Step 5 — 编排与触发**
在 Workflow 画布上把节点串成 `fetch(Plugin) → aggregate(Code) → review(LLM) → filter+render(Code) → 输出`，用「开始节点」接收 `hours/symbols/mode` 参数，发布为 Bot 或 Workflow API。Coze 支持定时触发，可实现原项目预留的「每日定时跑」（v1 是手动的）。

### 国内版 vs 国际版差异（重要）
- **模型可用性**：国内 Coze（coze.cn）默认用豆包等国产模型，**接 Claude/OpenAI 受限**；国际版 coze.com 可接 GPT 等海外模型。`sentiment_review.md` 的 prompt 是模型无关的，但不同模型的 JSON 遵从度不同，迁移后需重测自检通过率。
- **网络可达性**：GDELT、海外 RSS、Alpha Vantage 等源在**国内版的出网环境**可能不稳定/被限，建议把抓取放在你自建服务侧（部署在能访问这些源的网络）。
- **合规审核**：国内版上架公开 Bot 商店需过内容审核，金融舆情类**风险高**（见文末合规提醒）。
- **数据出境**：用户输入与新闻数据会过字节云。金融数据敏感时这是硬伤。

### 坑点
- Coze 代码节点对第三方 Python 包支持有限，VADER 等尽量放进自建服务。
- LLM 节点输出 JSON 不稳定，务必加校验 + 重试，否则后续代码节点会崩。
- 工作流单次执行有时长/Token 配额，新闻条数多时要在 aggregate 阶段就收敛 TOP-N。
- 审计链路（audit.log 的 sha256 溯源）在 Coze 里难原样复刻，需要靠外部数据库自己实现。

---

## 4. Dify（开源可自托管）（改造量：中）

### 适用场景
- **金融场景首选**：数据不出内网、需要审计、要接自己的模型或私有部署的模型。
- 想要可视化工作流，但又不愿把数据交给公有云 SaaS。

### 为什么 Dify 最契合本项目
本项目自带 append-only 的 `audit.log`、敏感词过滤、合规免责声明——这些都是**为合规设计**的特征。Dify 可以 Docker / K8s 自托管，**数据全程在企业内网**，与金融舆情工具的合规要求天然吻合。它的 Workflow 引擎还原生支持 **Python 代码执行节点（沙箱）**，能最大程度复用现有 Python 逻辑，所以改造量比 Coze 小。

### 关键映射表
| 本项目组件 | Dify 概念 |
|---|---|
| `fetch_news.py` 并发抓取 | **HTTP 请求节点**（调 GDELT/RSS），或 **代码执行节点**（沙箱内跑抓取逻辑） |
| `aggregate.py`（去重 + VADER） | **代码执行节点（Python 沙箱）**，逻辑几乎可原样搬 |
| `sentiment_review.md` | **LLM 节点**（模型可选 Claude / GPT / 本地 Ollama 等） |
| 6 点自检 | LLM 节点 prompt 尾部 + 一个**代码节点**校验 |
| `content_filter.py` + `sensitive_words.yaml` | **代码执行节点**（敏感词硬禁用 + 软改写） |
| 综合分 0.6/0.4 + 渲染 | **代码节点**（计算 + 拼 Markdown） |
| `config.yaml` 参数、品种列表 | Workflow 的**开始节点输入变量 / 环境变量** |
| 节点间数据 | Dify 的**变量传递**（上游节点 output 作为下游 input 引用） |
| `audit.log` | 代码节点写内网文件 / 调内部审计 API |

### 分步骤说明

**Step 1 — 起一个自托管 Dify**
用官方 docker-compose 起一套 Dify（含 API / Worker / 沙箱）。沙箱服务（dify-sandbox）是 Python/Node 代码节点的运行环境，要确认它能联通外网（抓 GDELT/RSS）或你的内网代理。

**Step 2 — fetch 节点**
两种选择：
- **HTTP 请求节点**：对 GDELT 直接发 GET，参数照搬 `clients/gdelt.py`。简单源用这个。
- **代码执行节点**：把 `fetch_news.py` 的核心逻辑（含并发、退出码、ticker 兜底）塞进 Python 沙箱节点。注意沙箱可能不预装 `aiohttp`——Dify 沙箱支持 `requirements` 配置，或退化为 `requests` 顺序抓取。RSS 解析（`feedparser`）同理需确认可用。

**Step 3 — aggregate 节点（代码执行）**
把 `aggregate.py` 的去重 + VADER 兜底逻辑放进 Python 代码节点。VADER 若沙箱无法安装，可（a）合入 fetch 服务，或（b）在节点 requirements 里声明 `vaderSentiment`。输出 `candidates`（JSON）通过变量传给下游。

**Step 4 — LLM 复核节点**
用 LLM 节点，模型选金融场景可接受的（自托管时常用本地模型或企业自有 Claude/GPT 通道）。System Prompt = `sentiment_review.md` 内容，输入引用 Step 3 的 `candidates` 变量，要求输出 JSON。后接一个代码节点做 6 点自检 + JSON 合法性校验（不合法可走 Dify 的条件分支重试一次，对齐原项目容错）。

**Step 5 — 过滤 + 渲染节点（代码执行）**
代码节点：综合分 `0.6×LLM + 0.4×算法` → 跑 `content_filter` 敏感词过滤（词表作为节点资源或环境变量传入）→ 拼 Markdown。同一节点或追加节点写 `audit.log` 到内网持久卷。结束节点把报告文本作为 Workflow 输出。

**Step 6 — 导入 / 导出 Workflow DSL**
Dify 工作流可导出为 **DSL（YAML）**文件，便于版本化、在多套环境间迁移、纳入 Git 管理。建议：在一套环境里搭好工作流后导出 DSL，作为这套移植方案的「制品」入库，新环境直接「导入 DSL」即可复现，无需手工连线。

### 变量传递要点
- 开始节点声明 `hours`(int)、`symbols`(string，逗号分隔)、`mode`(string)。
- 每个节点的输出在下游用 `{{#节点ID.字段#}}` 引用；JSON 大对象建议整体作为字符串传，在下游代码节点里 `json.loads`。
- 敏感词表、`score_weights` 等配置走**环境变量 / 会话变量**，避免硬编码进节点代码。

### 坑点
- **沙箱包白名单**：dify-sandbox 默认限制可导入的 Python 包与系统调用，`aiohttp`/`feedparser`/`vaderSentiment` 不一定开箱可用，需要配置沙箱依赖或改用 HTTP 节点 / 自建服务。
- **沙箱执行超时**：代码节点有超时限制，多源并发抓取若慢会被掐，建议收敛源数量或异步改同步并控数量。
- **出网策略**：自托管在内网时，抓取节点需要明确的出网代理白名单（GDELT、各 RSS 域名）。
- **模型选择影响 JSON 稳定性**：本地小模型遵从 JSON 格式能力弱，6 点自检失败率会上升，需加重试与降级（退化为纯算法分，对齐 `render_report.py` 的 fallback）。

---

## 5. 合规提醒（务必阅读）

本项目是**金融舆情 / 市场情绪分析工具**，移植到任何对外平台前，请认真评估合规风险：

1. **不要把金融舆情工具上架到面向 C 端的公开市场。** 包括 Coze Bot 商店、GPT Store、各类应用市场。金融信息服务在中国大陆受严格监管（涉及《互联网信息服务管理办法》、金融信息服务相关规定、可能触及荐股/投资建议红线）；面向不特定公众发布带方向性判断的市场情绪内容，存在被认定为「未经许可的金融信息服务 / 投资建议」的风险。

2. **保留并强化免责声明与敏感词过滤。** 原项目带有「仅供研究参考 — 不构成投资建议」的中性标签、完整免责声明块（`config.yaml` 的 `compliance.report_label` / `org_name`）和敏感词硬禁用/软改写（`content_filter.py` + `sensitive_words.yaml`）。移植到任何平台都必须**完整移植这两层**，不可为图省事砍掉。

3. **优先选择数据不出内网的形态。** 金融数据敏感，**Dify 自托管**或**内部 GitHub 私有仓库分发**是推荐路径；它们让数据与审计日志留在企业可控范围内。Coze / GPT 等公有云 SaaS 会把数据过第三方云，金融场景应慎用，公开发布更不可取。

4. **保留审计链路。** 原项目的 `audit.log`（run_id → 输入/输出文件 sha256 → prompt 版本 → 过滤命中明细）是合规可追溯的关键资产。移植到工作流平台后，务必用平台的数据库节点 / 内部审计 API **重建等价的审计记录**，不要让决策链路变成黑盒。

5. **定位为内部研究/PM 辅助工具，而非对客产品。** 输出应服务于内部研究、风控、产品判断，而不是直接推送给终端投资者作为交易依据。

**结论建议**：对内部团队复用，走 **GitHub 私有仓库 / Plugin**；需要可视化编排且强隐私，走 **Dify 自托管**；Coze 仅适合做**内部、非公开、去金融建议化**的演示型 Bot，切勿上公开市场面向 C 端。
