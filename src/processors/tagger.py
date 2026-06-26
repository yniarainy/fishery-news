"""LLM-based entity extraction and tagging for fishery articles."""

from __future__ import annotations

import json
import logging

from src.collectors.base import RawArticle

logger = logging.getLogger(__name__)


class Tagger:
    """标签提取器——从文章中提取结构化实体和关键词。

    提取维度:
    - species: 物种名 (tuna, salmon, cod, shrimp...)
    - regions: 地理区域 (North Pacific, South China Sea...)
    - organizations: 组织机构 (FAO, NOAA, EU, WWF, MSC...)
    - keywords: 关键词 (overfishing, aquaculture, quota...)
    - topics: 话题 (climate change, IUU fishing, stock assessment...)
    """

    def __init__(self, config: dict, prompts: dict):
        llm_config = config.get("llm", {})
        self.batch_size: int = llm_config.get("batch_size", 5)  # 标签提取比较重，用小批次
        self.prompts = prompts.get("tagger", {})
        self._llm_client = None

    @property
    def llm_client(self):
        if self._llm_client is None:
            from src.llm_client import LLMClient
            from src.config import get_config
            self._llm_client = LLMClient(get_config())
        return self._llm_client

    def run(self, articles: list[RawArticle], db) -> list[RawArticle]:
        """为文章提取标签。

        Args:
            articles: RawArticle 列表
            db: Database 实例

        Returns:
            已设置 tags/entities 的文章列表
        """
        # 跳过已有标签的文章
        need_tag = []
        for a in articles:
            aid = a.compute_id()
            existing = db.get_article(aid)
            if existing and existing.tags:
                a._cached_tags = existing.tags
                a._cached_entities = existing.entities
            else:
                need_tag.append(a)

        if not need_tag:
            logger.info("[Tag] All articles already tagged")
            return articles

        logger.info(f"[Tag] Need to tag {len(need_tag)} articles")

        system_prompt = self.prompts.get("system", "")
        user_template = self.prompts.get("user", "")

        for i, article in enumerate(need_tag):
            try:
                user_prompt = user_template.format(
                    title=article.title,
                    summary=(article.raw_summary or "")[:400],
                )

                result = self.llm_client.chat_json(system_prompt, user_prompt)

                tags = result.get("keywords", []) if isinstance(result, dict) else []
                entities = {
                    "species": result.get("species", []) if isinstance(result, dict) else [],
                    "regions": result.get("regions", []) if isinstance(result, dict) else [],
                    "organizations": result.get("organizations", []) if isinstance(result, dict) else [],
                }

                article._cached_tags = tags
                article._cached_entities = entities

                aid = article.compute_id()
                db.update_article(aid, tags=tags, entities=entities)

                if (i + 1) % 5 == 0:
                    logger.debug(f"[Tag] {i + 1}/{len(need_tag)} done")

            except Exception as e:
                logger.error(f"[Tag] Failed for '{article.title[:40]}...': {e}")
                article._cached_tags = []
                article._cached_entities = {}

        logger.info(f"[Tag] Completed {len(need_tag)} articles")
        return articles
