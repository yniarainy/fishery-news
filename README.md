# 🐟 Fishery News Weekly — 全球渔业新闻周刊自动聚合系统

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

自动从 **30+ 全球渔业信源** 采集新闻，通过 **DeepSeek V4** 大模型智能处理，每周生成一份中英文双语渔业新闻周刊，自动部署到 **GitHub Pages** 静态网站。

---

## 功能特性

- **4 层采集策略**: RSS → API → 网页爬虫 → LLM 搜索，覆盖全球渔业信息
- **LLM 智能处理**: 分类、去重、聚类、中文摘要、标签提取、趋势洞察
- **杂志风格周刊**: 40 篇文章卡片 + 渐变色分类 + 主编按语 + AI 洞察
- **分类筛选**: 产业动态 / 政策法规 / 科学研究 / NGO环保 / 数据统计
- **自动部署**: GitHub Actions 每周一定时运行，GitHub Pages 自动发布
- **增量更新**: 旧期永久保留，archive 页面自动追加往期列表
- **API Key 安全**: 仅存储在 GitHub Secrets，代码和页面中永不暴露

---

## 信息来源（Source Ecosystem）

系统覆盖 **7 大类、30+ 信源**，按 4 层策略组织：

### 🏭 产业媒体（Industry）

| 信源 | 采集方式 | 说明 |
|------|----------|------|
| **Undercurrent News** | RSS ✅ | 全球海产品贸易新闻领导者 |
| IntraFish | Crawl | 全球渔业与水产新闻 |
| SeafoodSource | Crawl | 海产品行业新闻与分析 |
| The Fish Site | Crawl | 水产养殖与渔业知识平台 |
| World Fishing | RSS | 全球商业渔业新闻 |
| FisheryIntel | Crawl | 渔业情报分析 |
| 中国水产频道 | RSS | 中国水产行业门户 |

### 🔬 科学研究（Research）

| 信源 | 采集方式 | 说明 |
|------|----------|------|
| **Nature - Fisheries** | RSS ✅ | Nature 渔业相关研究 |
| Science News | RSS | Science 期刊新闻（含海洋/生态） |
| Fish and Fisheries | RSS | 顶级渔业期刊 (Wiley) |
| **OpenAlex** | API | 开放学术图谱，覆盖渔业/海洋/水产论文 |
| **Crossref** | API | 学术论文检索 |
| ICES | Crawl | 国际海洋考察理事会 |

### 🏛️ 政策法规（Policy）

| 信源 | 采集方式 | 说明 |
|------|----------|------|
| **FAO Fisheries** | Crawl | 联合国粮农组织渔业新闻 |
| **NOAA Fisheries** | RSS | 美国国家海洋渔业局 |
| EU Fisheries & Oceans | RSS | 欧盟海洋与渔业政策 |
| CCAMLR / IOTC / WCPFC 等 RFMO | LLM Search | 各区域渔业管理组织 |
| 中国渔业政务网 | Crawl | 农业农村部渔业渔政管理局 |

### 🌊 NGO 与环保（NGO）

| 信源 | 采集方式 | 说明 |
|------|----------|------|
| **Global Fishing Watch** | RSS | 全球渔业监测组织 |
| MSC | Crawl | 海洋管理委员会可持续认证 |
| WWF Oceans | RSS | 世界自然基金会海洋项目 |
| Ocean Conservancy | LLM Search | 海洋保护组织 |

### 📈 数据与市场（Data & Market）

| 信源 | 采集方式 | 说明 |
|------|----------|------|
| Our World in Data | RSS | 数据看世界（含渔业/海洋） |
| Global Fishing Watch API | API | AIS 船舶活动开放数据 |
| FAOSTAT | API | 联合国粮农统计数据库 |

### 4 层采集策略说明

| 层级 | 方式 | 维护成本 | 适用场景 |
|------|------|----------|----------|
| **L1 RSS** | RSS/Atom Feed | ★☆☆☆☆ | 有标准 Feed 的网站，解析即用 |
| **L2 API** | REST API | ★★☆☆☆ | OpenAlex、Crossref 等结构化数据 |
| **L3 Crawl** | Jina Reader / BS4 | ★★★☆☆ | 无 RSS/API 的网站，网页→Markdown |
| **L4 Search** | LLM Agent 定向搜索 | ★★★★☆ | 政府公告、RFMO 等无固定结构的信源 |

---

## 架构总览

```
┌─────────────────────────────────────────────────┐
│           4 层采集 (Source Ecosystem)             │
│   RSS → API → Crawl → LLM Search                │
│   30+ 信源 / 7 大类 / 中英文                      │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│         DeepSeek V4 LLM 处理流水线                │
│                                                  │
│  Fetch → Pre-filter → Dedup(TF-IDF) → Classify  │
│  → Cluster → Summarize(中/英) → Tag → AI Insight │
│                                                  │
│  分类: 产业/政策/科研/NGO/数据                      │
│  去重: TF-IDF + ChromaDB 向量比对                 │
│  摘要: 三级(单篇→聚类→主编按语)                     │
│  标签: 物种/区域/组织/关键词                        │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│              多渠道输出                           │
│                                                  │
│  🌐 静态网站 (GitHub Pages)  ← 自动化部署          │
│  📄 Markdown 文件          ← 本地/归档             │
│  📱 微信公众号 (草稿箱)     ← 人工确认后群发         │
│  📝 Notion 数据库          ← 知识库存档            │
└─────────────────────────────────────────────────┘
```

## 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install httpx feedparser beautifulsoup4 lxml openai chromadb \
            pydantic pyyaml jinja2 python-dateutil rich scikit-learn \
            langdetect tenacity

# 2. 设置 API Key
# 在项目根目录创建 .env 文件:
echo "DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx" > .env

# 3. 启用信源（编辑 config/sources.yaml）
# 4. 运行
python src/main.py --mode weekly

# 5. 查看结果
# 浏览器打开 site/index.html
```

### 输出文件

```
newsletter.md              ← 最新周刊 Markdown
site/
├── index.html             ← 最新周刊网页
├── archive.html           ← 往期归档（自动生成）
├── issue-2026-W26/        ← 2026年第26周
│   ├── index.html
│   └── newsletter.md
└── issue-2026-W27/        ← 2026年第27周（下周自动生成）
```

---

## GitHub Pages 部署（免费自动）

### 第一步：创建 GitHub 仓库

1. 打开 [github.com/new](https://github.com/new)
2. Repository name: `fishery-news`（或你喜欢的名字）
3. 选择 **Public**
4. **不要** 勾选 "Add a README file"（我们已有）
5. 点击 Create repository

### 第二步：推送代码

```bash
cd H:\agents\news

# 初始化 git
git init
git add .
git commit -m "🎉 Initial commit: Fishery News Weekly"

# 关联你的仓库（替换为你的用户名）
git remote add origin https://github.com/你的用户名/fishery-news.git

# 推送
git branch -M main
git push -u origin main
```

### 第三步：配置 Secrets 和 Pages

**添加 API Key:**

1. 打开仓库 → Settings → Secrets and variables → Actions
2. 点击 **New repository secret**
3. Name: `DEEPSEEK_API_KEY`
4. Value: `sk-你的DeepSeek密钥`
5. 点击 Add secret

**启用 GitHub Pages:**

1. Settings → Pages
2. Source: 选择 **GitHub Actions**
3. 保存

### 第四步：首次运行

1. 打开仓库 → **Actions** 标签页
2. 点击左侧 **Weekly Fishery Newsletter**
3. 点击 **Run workflow** → 选择 `weekly` → **Run workflow**
4. 等待约 15-20 分钟（40 篇文章的 LLM 处理时间）
5. 部署完成后访问:

```
https://你的用户名.github.io/fishery-news/
```

### 从此全自动

- ⏰ **每周一北京时间 08:00** 自动运行
- 🆕 生成新一期（如 `issue-2026-W27/`）
- 📋 `archive.html` 自动追加条目
- 📦 旧期永久保留，不会覆盖
- 🔑 API Key 全程在 GitHub Secrets 中，代码和页面绝不暴露

---

## 项目结构

```
fishery-news/
├── .github/workflows/
│   └── weekly.yml              # GitHub Actions: 定时采集+部署
├── config/
│   ├── sources.yaml             # 信源注册表 (30+ 预设信源)
│   ├── prompts.yaml             # LLM Prompt 模板 (可独立迭代)
│   └── settings.yaml            # 全局配置 (API Key 用 ${VAR} 占位)
├── templates/
│   ├── weekly.md.j2             # Markdown 周刊模板
│   └── index.html.j2            # HTML 站点模板 (响应式/分类筛选/渐变卡片)
├── src/
│   ├── collectors/              # 采集器 (4层策略)
│   │   ├── rss.py               #   RSS/Atom Feed
│   │   ├── scraper.py           #   HTML 爬虫 (BeautifulSoup)
│   │   ├── api_client.py        #   REST API 客户端
│   │   ├── openalex.py          #   OpenAlex 论文检索
│   │   ├── jina.py              #   Jina Reader (网页→Markdown)
│   │   └── og_image.py          #   OpenGraph 图片提取
│   ├── processors/              # LLM 处理流水线
│   │   ├── prefilter.py         #   关键词+URL预过滤
│   │   ├── dedup.py             #   TF-IDF 向量去重
│   │   ├── embedder.py          #   本地文本向量化
│   │   ├── classifier.py        #   DeepSeek V4 五分类
│   │   ├── cluster.py           #   事件聚类
│   │   ├── summarizer.py        #   三级摘要
│   │   ├── tagger.py            #   实体标签提取
│   │   └── insights.py          #   AI 趋势洞察
│   ├── storage/
│   │   ├── models.py            #   Pydantic 数据模型
│   │   ├── db.py                #   SQLite CRUD
│   │   └── vector.py            #   ChromaDB 向量存储
│   ├── outputs/
│   │   ├── markdown.py          #   Markdown 周刊渲染
│   │   ├── site.py              #   静态 HTML 站点生成
│   │   ├── wechat.py            #   微信公众号发布
│   │   └── notion.py            #   Notion 发布
│   ├── llm_client.py            # DeepSeek API 客户端 (v4-pro/v4-flash)
│   ├── config.py                # 统一配置加载 (.env + ${VAR} 替换)
│   ├── agent.py                 # 信源自更新 Agent
│   └── main.py                  # 主编排器 CLI
├── site/                        # 静态网站输出
├── data/                        # 运行时数据 (gitignore 排除 raw/chroma/output)
├── .env                         # API Key (gitignore 排除)
└── pyproject.toml
```

## LLM 流水线详情

| 步骤 | 技术 | API 调用 | 说明 |
|------|------|----------|------|
| **Fetch** | RSS/API/Scraper | ❌ | 遍历已启用信源 |
| **Pre-filter** | 规则引擎 | ❌ | 关键词黑名单 + 已发刊 URL 去重 |
| **Dedup** | TF-IDF + ChromaDB | ❌ | 本地向量化，秒级完成 |
| **Classify** | DeepSeek V4 Pro | ✅ 4次/40篇 | 10篇/批，五分类 |
| **Cluster** | BFS 连通分量 | ❌ | 同一事件归组 |
| **Summarize** | DeepSeek V4 Pro | ✅ 40次 | 逐篇中文摘要 + 主编按语 |
| **Tag** | DeepSeek V4 Pro | ✅ 40次 | 物种/区域/组织/关键词 |
| **Insights** | DeepSeek V4 Pro | ✅ 1次 | 趋势+热点+建议 |

**月均成本**: ~120 篇文章/月，DeepSeek V4 约 **<$1/月**。

## 扩展开发

### 添加新信源

编辑 `config/sources.yaml`，加一条即可：

```yaml
- id: my-new-source
  name: "My Fishery Source"
  layer: rss               # rss | api | crawl | search
  url: "https://example.com/feed"
  category: industry       # industry | policy | science | ngo | data
  language: en
  enabled: true
```

### 自定义 LLM Prompt

编辑 `config/prompts.yaml`，修改后无需改代码直接生效。

### 信源自更新

每周周刊生成后，Agent 基于本周热点搜索新信源 → LLM 评估 → 输出候选到 `config/sources_candidates.yaml`。

## License

MIT
