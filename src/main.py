#!/usr/bin/env python3
"""Fishery News Weekly — 主编排器

Usage:
    python src/main.py --mode weekly      # 完整周刊流程
    python src/main.py --mode collect     # 仅采集
    python src/main.py --mode process     # 仅处理（需要先采集）
    python src/main.py --mode output      # 仅生成输出

Environment:
    DEEPSEEK_API_KEY    DeepSeek API 密钥
    WECHAT_APP_ID       微信公众号 AppID (可选)
    WECHAT_APP_SECRET   微信公众号 AppSecret (可选)
    NOTION_API_KEY      Notion API Key (可选)
    NOTION_DATABASE_ID  Notion 数据库 ID (可选)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fishery-news")


from src.config import get_config, get_sources, get_prompts


# ---- Pipeline Steps (stubs — implemented in Phase 2-4) ----


def step_fetch(sources: list[dict], config: dict) -> list:
    """Step 1: 4层采集策略.

    L1 RSS  → RSSCollector
    L2 API  → OpenAlexCollector / APICollector
    L3 Crawl→ JinaReaderCollector / ScraperCollector
    L4 Search → 跳过（由 agent.py 在周刊生成后处理）
    """
    from src.collectors.rss import RSSCollector
    from src.collectors.scraper import ScraperCollector
    from src.collectors.api_client import APICollector
    from src.collectors.base import CollectorResult

    all_articles = []
    for src in sources:
        layer = src.get("layer", src.get("type", "rss"))

        # L4 Search 在周刊生成后由 agent 处理
        if layer == "search":
            logger.debug(f"[{src['id']}] L4 Search — deferred")
            continue

        # 构建统一配置
        src_config = {**src}
        src_config.setdefault("user_agent", config["collection"]["user_agent"])
        src_config.setdefault("timeout", config["collection"]["request_timeout"])
        src_config.setdefault("max_articles", config["collection"]["max_articles_per_source"])
        if layer == "api" and src.get("api_config"):
            api_cfg = src.pop("api_config", {})
            src_config.update(api_cfg)

        # 选择采集器
        result = None
        if layer == "api" and "openalex.org" in src.get("url", ""):
            try:
                from src.collectors.openalex import OpenAlexCollector
                result = OpenAlexCollector(src_config).collect()
            except ImportError:
                pass
        elif layer == "crawl" and src.get("crawl_method") == "jina":
            try:
                from src.collectors.jina import JinaReaderCollector
                result = JinaReaderCollector(src_config).collect()
            except ImportError:
                pass

        if result is None:
            collector_cls = {
                "rss": RSSCollector, "scraper": ScraperCollector,
                "crawl": ScraperCollector, "api": APICollector,
            }.get(layer)
            if not collector_cls:
                logger.warning(f"Unknown layer: {layer} for {src['id']}")
                continue
            result = collector_cls(src_config).collect()

        if result.success:
            all_articles.extend(result.articles)
            logger.info(f"  [{src['id']}] +{len(result.articles)} articles")
        else:
            logger.error(f"  [{src['id']}] {result.error}")

    logger.info(f"Step 1 [Fetch]: {len(all_articles)} total from {len(sources)} sources")
    return all_articles


def step_prefilter(articles: list, config: dict, db) -> list:
    """Step 2: 预过滤（关键词 + URL 去重）。"""
    from src.processors.prefilter import Prefilter

    prefilter = Prefilter(config)
    filtered = prefilter.run(articles, db)
    logger.info(f"Step 2 [Prefilter]: {len(articles)} → {len(filtered)} articles")
    return filtered


def step_dedup(articles: list, config: dict, db, vector_store) -> list:
    """Step 3: 向量去重。"""
    from src.processors.dedup import Deduplicator

    dedup = Deduplicator(config, db, vector_store)
    result = dedup.run(articles)
    logger.info(f"Step 3 [Dedup]: {len(articles)} → {len(result)} unique")
    return result


def step_classify(articles: list, config: dict, prompts: dict, db) -> list:
    """Step 4: LLM 分类。"""
    from src.processors.classifier import Classifier

    classifier = Classifier(config, prompts)
    result = classifier.run(articles, db)
    categorized = sum(1 for a in result if getattr(a, '_cached_category', None))
    logger.info(f"Step 4 [Classify]: {categorized}/{len(result)} classified")
    return result


def step_cluster(articles: list, config: dict, vector_store) -> list:
    """Step 5: 事件聚类。"""
    from src.processors.cluster import Clusterer

    clusterer = Clusterer(config, vector_store)
    clusters = clusterer.run(articles)
    logger.info(f"Step 5 [Cluster]: {len(clusters)} clusters from {len(articles)} articles")
    return clusters


def step_summarize(articles: list, clusters: list, config: dict, prompts: dict, db) -> list:
    """Step 6: LLM 摘要。"""
    from src.processors.summarizer import Summarizer

    summarizer = Summarizer(config, prompts)
    result = summarizer.run(articles, clusters, db)
    summarized = sum(1 for a in result if getattr(a, '_cached_summary', None))
    logger.info(f"Step 6 [Summarize]: {summarized}/{len(result)} summarized")
    return result


def step_tag(articles: list, config: dict, prompts: dict, db) -> list:
    """Step 7: 标签提取。"""
    from src.processors.tagger import Tagger

    tagger = Tagger(config, prompts)
    result = tagger.run(articles, db)
    tagged = sum(1 for a in result if getattr(a, '_cached_tags', None))
    logger.info(f"Step 7 [Tag]: {tagged}/{len(result)} tagged")
    return result


def step_insights(articles: list, clusters: list, config: dict, prompts: dict, db) -> dict:
    """Step 8: AI 洞察。"""
    from src.processors.insights import InsightGenerator

    generator = InsightGenerator(config, prompts)
    result = generator.run(articles, clusters, db)
    logger.info(f"Step 8 [Insights]: {len(result.get('hot_topics', []))} hot topics identified")
    return result


def step_render(issue, articles, clusters, insights, config) -> str:
    """Step 9: 渲染周刊 Markdown。"""
    from src.outputs.markdown import MarkdownRenderer

    renderer = MarkdownRenderer(config)
    result = renderer.render(issue, articles, clusters, insights)
    logger.info(f"Step 9 [Render]: Newsletter generated")
    return result


def step_output(markdown_content: str, issue, config, articles=None, insights=None, editorial="") -> dict:
    """Step 10: 发布到各渠道。"""
    results = {}

    # 1. Static Site
    try:
        from src.outputs.site import SiteGenerator
        site_gen = SiteGenerator(config)
        site_gen.generate(markdown_content, issue, articles=articles, insights=insights, weekly_editorial=editorial)
        results["site"] = "ok"
    except Exception as e:
        logger.error(f"Site output failed: {e}")
        results["site"] = str(e)

    # 2. WeChat
    if os.getenv("WECHAT_APP_ID"):
        try:
            from src.outputs.wechat import WeChatPublisher
            wechat = WeChatPublisher(config)
            wechat.publish_draft(markdown_content, issue)
            results["wechat"] = "ok"
        except Exception as e:
            logger.error(f"WeChat output failed: {e}")
            results["wechat"] = str(e)

    # 3. Notion
    if os.getenv("NOTION_API_KEY"):
        try:
            from src.outputs.notion import NotionPublisher
            notion = NotionPublisher(config)
            notion.publish(markdown_content, issue)
            results["notion"] = "ok"
        except Exception as e:
            logger.error(f"Notion output failed: {e}")
            results["notion"] = str(e)

    logger.info(f"Step 10 [Output]: {results}")
    return results


def step_source_discovery(config: dict, prompts: dict, db) -> None:
    """Optional: 信源自更新 Agent。"""
    try:
        from src.agent import SourceDiscoveryAgent
        agent = SourceDiscoveryAgent(config, prompts, db)
        candidates = agent.discover()
        if candidates:
            logger.info(f"Source Discovery: {len(candidates)} new candidates found")
        else:
            logger.info("Source Discovery: no new candidates")
    except Exception as e:
        logger.error(f"Source Discovery failed: {e}")


# ---- 主编排器 ----


def run_pipeline(mode: str = "weekly") -> None:
    """运行处理管线。"""
    logger.info("=" * 60)
    logger.info(f"Fishery News Weekly — {mode} mode")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # 加载配置
    config = get_config()
    sources = get_sources()
    prompts = get_prompts()

    logger.info(f"Loaded {len(sources)} enabled sources")

    # 初始化存储
    from src.storage.db import Database
    from src.storage.vector import VectorStore

    db = Database(config["storage"]["sqlite_path"])
    vector_store = VectorStore(config["storage"]["chroma_path"])

    # --- Collect ---
    if mode in ("collect", "weekly"):
        raw_articles = step_fetch(sources, config)

        # 保存原始数据
        raw_path = Path(config["storage"]["raw_data_path"]) / datetime.now().strftime("%Y%m%d")
        raw_path.mkdir(parents=True, exist_ok=True)
        import json
        raw_file = raw_path / "articles.json"
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "source_id": a.source_id,
                        "title": a.title,
                        "url": a.url,
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                    }
                    for a in raw_articles
                ],
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info(f"Raw data saved to {raw_file}")
    else:
        raw_articles = []
        logger.info("Skipping collect step")

    # --- Process ---
    if mode in ("process", "weekly") and raw_articles:
        # 保存到 DB
        for article in raw_articles:
            from src.storage.models import Article as DBArticle
            db_article = DBArticle(
                id=article.compute_id(),
                source_id=article.source_id,
                source_name=article.source_name,
                url=article.url,
                title=article.title,
                raw_summary=article.raw_summary,
                content=article.content,
                author=article.author,
                published_at=article.published_at,
                language=article.language,
                image_url=article.image_url,
            )
            db.insert_article(db_article)

        # 预过滤
        filtered = step_prefilter(raw_articles, config, db)
        # 去重
        unique = step_dedup(filtered, config, db, vector_store)
        # 分类
        classified = step_classify(unique, config, prompts, db)
        # 聚类
        clusters = step_cluster(classified, config, vector_store)
        # 摘要
        summarized = step_summarize(classified, clusters, config, prompts, db)
        # 标签
        tagged = step_tag(summarized, config, prompts, db)
        # 洞察
        insights = step_insights(tagged, clusters, config, prompts, db)

        processed_articles = tagged
    else:
        # 从 DB 读取最近的未处理文章
        processed_articles = db.get_articles_without_summary(limit=50)
        clusters = []
        insights = {}
        logger.info(f"Loaded {len(processed_articles)} unprocessed articles from DB")

    # --- Output ---
    if mode in ("output", "weekly"):
        # 创建新一期周刊，编号: 2026-W26 (ISO 周年+周数)
        now = datetime.now()
        iso_year, iso_week, _ = now.isocalendar()
        issue_number = f"{iso_year}-W{iso_week:02d}"
        week_start = now - timedelta(days=now.weekday())
        week_end = week_start + timedelta(days=6)

        from src.storage.models import Issue, NewsletterData

        issue = Issue(
            number=issue_number,
            title=f"渔业新闻周刊 {issue_number}",
            period_start=week_start.strftime("%Y-%m-%d"),
            period_end=week_end.strftime("%Y-%m-%d"),
            article_count=len(processed_articles),
        )

        # 标记文章归属
        for article in processed_articles:
            article_id = article.compute_id()
            db.update_article(article_id, issue_number=issue_number, included_in_issue=True)

        # 渲染
        markdown_content = step_render(issue, processed_articles, clusters, insights, config)

        # 保存
        output_dir = Path(config["storage"]["output_path"]) / f"issue-{issue_number}"
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "newsletter.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        issue.markdown_path = str(md_path)
        db.create_issue(issue)
        logger.info(f"Newsletter saved to {md_path}")

        # 发布（传入文章和洞察数据）
        step_output(markdown_content, issue, config, articles=processed_articles, insights=insights, editorial=markdown_content.split('📝 主编按语')[1].split('---')[0] if '📝 主编按语' in markdown_content else "")

        # 信源发现（可选）
        if mode == "weekly":
            step_source_discovery(config, prompts, db)

    # 清理
    db.close()
    logger.info("Pipeline complete! 🐟")


# ---- CLI ----


def main():
    parser = argparse.ArgumentParser(
        description="Fishery News Weekly — 渔业新闻周刊自动聚合系统",
    )
    parser.add_argument(
        "--mode",
        choices=["weekly", "collect", "process", "output"],
        default="weekly",
        help="运行模式 (默认: weekly)",
    )
    parser.add_argument(
        "--source",
        type=str,
        help="仅处理指定信源 ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式（不实际写入/发布）",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="输出调试日志",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        # 降低第三方库日志级别
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("chromadb").setLevel(logging.WARNING)

    run_pipeline(mode=args.mode)


if __name__ == "__main__":
    main()
