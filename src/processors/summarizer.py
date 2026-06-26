"""LLM-based multi-level summarizer (single article → cluster → weekly)."""

from __future__ import annotations

import json
import logging

from src.collectors.base import RawArticle
from src.storage.models import ClusterGroup

logger = logging.getLogger(__name__)


class Summarizer:
    """三级摘要生成器。

    Level 1: 单篇文章中文摘要 (50-100 字)
    Level 2: 事件聚类综合摘要 (150-200 字)
    Level 3: 周刊主编按语 (200-300 字)
    """

    def __init__(self, config: dict, prompts: dict):
        llm_config = config.get("llm", {})
        self.batch_size: int = llm_config.get("batch_size", 10)
        self.prompts = prompts.get("summarizer", {})
        self._llm_client = None

    @property
    def llm_client(self):
        if self._llm_client is None:
            from src.llm_client import LLMClient
            from src.config import get_config
            self._llm_client = LLMClient(get_config())
        return self._llm_client

    def run(
        self,
        articles: list[RawArticle],
        clusters: list[ClusterGroup],
        db,
    ) -> list[RawArticle]:
        """执行所有三级摘要。

        Returns:
            已设置 summary_cn 的文章列表
        """
        # L1: 单篇摘要
        self._summarize_single(articles, db)

        # L2: 聚类摘要
        if clusters:
            self._summarize_clusters(clusters)

        # L3: 周刊总摘要（在 render 阶段调用，此处先跳过）
        return articles

    def _summarize_single(self, articles: list[RawArticle], db) -> None:
        """L1: 为每篇文章生成中文摘要。"""
        # 跳过已有摘要的
        need_summary = []
        for a in articles:
            aid = a.compute_id()
            existing = db.get_article(aid)
            if existing and existing.summary_cn:
                a._cached_summary = existing.summary_cn
            else:
                need_summary.append(a)

        if not need_summary:
            logger.info("[Summarize L1] All articles already summarized")
            return

        logger.info(f"[Summarize L1] Need to summarize {len(need_summary)} articles")

        # 逐篇处理（摘要需要更多上下文，不适合大批量）
        single_prompts = self.prompts.get("single", {})
        system_prompt = single_prompts.get("system", "")

        for i, article in enumerate(need_summary):
            try:
                content_section = ""
                if article.content:
                    content_section = f"全文摘要：{article.content[:300]}"

                user_prompt = single_prompts.get("user", "{title}").format(
                    title=article.title,
                    raw_summary=article.raw_summary or "（无原文摘要）",
                    content_section=content_section,
                )

                summary = self.llm_client.chat(system_prompt, user_prompt)
                summary = summary.strip()

                article._cached_summary = summary
                aid = article.compute_id()
                db.update_article(aid, summary_cn=summary)

                if (i + 1) % 5 == 0:
                    logger.debug(f"[Summarize L1] {i + 1}/{len(need_summary)} done")

            except Exception as e:
                logger.error(f"[Summarize L1] Failed for '{article.title[:40]}...': {e}")
                article._cached_summary = article.raw_summary or ""

        logger.info(f"[Summarize L1] Completed {len(need_summary)} summaries")

    def _summarize_clusters(self, clusters: list[ClusterGroup]) -> None:
        """L2: 为每个事件聚类生成综合摘要。"""
        cluster_prompts = self.prompts.get("cluster", {})
        system_prompt = cluster_prompts.get("system", "")

        for cluster in clusters:
            # 回退到 topic 标题
            if not hasattr(cluster, 'articles') or not cluster.articles:
                cluster.combined_summary = cluster.topic
                continue
            try:
                # 取每个聚类的文章标题
                articles_text = ""
                for j, article in enumerate(cluster.articles[:5]):  # 最多 5 篇
                    summary_text = getattr(article, '_cached_summary', '') or article.raw_summary or ''
                    articles_text += f"{j + 1}. 【{article.source_name}】{article.title}\n"
                    if summary_text:
                        articles_text += f"   摘要：{summary_text[:150]}\n\n"

                user_prompt = cluster_prompts.get("user", "").format(
                    count=min(len(cluster.articles), 5),
                    articles_text=articles_text,
                )

                combined = self.llm_client.chat(system_prompt, user_prompt)
                cluster.combined_summary = combined.strip()

            except Exception as e:
                logger.error(f"[Summarize L2] Failed for cluster {cluster.cluster_id}: {e}")
                cluster.combined_summary = cluster.topic

    def generate_weekly_editorial(
        self,
        articles: list[RawArticle],
        clusters: list[ClusterGroup],
        category_dist: dict[str, int],
    ) -> str:
        """L3: 生成周刊主编按语。"""
        weekly_prompts = self.prompts.get("weekly", {})
        system_prompt = weekly_prompts.get("system", "")

        # 取更多文章让编辑有足够素材
        top_n = min(len(articles), 20)

        articles_text = ""
        for i, a in enumerate(articles[:top_n]):
            cat = getattr(a, '_cached_category', None) or getattr(a, 'category', 'other')
            articles_text += f"{i + 1}. [{cat}] {a.title}\n"
            summary = getattr(a, '_cached_summary', None) or getattr(a, 'summary_cn', '') or getattr(a, 'raw_summary', '') or ''
            articles_text += f"   摘要：{summary[:150]}\n\n"

        cat_text = ", ".join(f"{k}: {v}篇" for k, v in sorted(category_dist.items()))

        user_prompt = (
            f"本周共收录 {len(articles)} 篇新闻，分类分布：{cat_text}\n\n"
            f"以下是本周文章列表，请仔细阅读后撰写主编按语：\n\n{articles_text[:4000]}"
        )

        try:
            return self.llm_client.chat(
                system_prompt, user_prompt, max_tokens=2000, temperature=0.5
            )
        except Exception as e:
            logger.error(f"[Summarize L3] Weekly editorial failed: {e}")
            return "本周渔业新闻摘要（主编按语生成中...）"
