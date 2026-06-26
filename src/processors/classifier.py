"""LLM-based article classification into fishery news categories."""

from __future__ import annotations

import json
import logging

from src.collectors.base import RawArticle

logger = logging.getLogger(__name__)

CATEGORIES = ["policy", "science", "industry", "ngo", "data"]


class Classifier:
    """LLM 分类器——将文章分类到渔业新闻类别。

    分类标准:
    - policy: 政策法规、国际谈判、配额分配、IUU打击
    - science: 学术研究、种群评估、气候变化影响
    - industry: 市场行情、企业动态、水产养殖技术
    - ngo: 环保组织报告、可持续认证、海洋保护
    - data: 统计数据发布、数据集更新、趋势报告

    批次处理以减少 API 调用次数。
    """

    def __init__(self, config: dict, prompts: dict):
        llm_config = config.get("llm", {})
        self.batch_size: int = llm_config.get("batch_size", 10)
        self.prompts = prompts.get("classifier", {})
        self.system_prompt: str = self.prompts.get("system", "")
        self.user_template: str = self.prompts.get("user", "")

        self._llm_client = None

    @property
    def llm_client(self):
        if self._llm_client is None:
            from src.llm_client import LLMClient
            from src.config import get_config
            self._llm_client = LLMClient(get_config())
        return self._llm_client

    def run(self, articles: list[RawArticle], db) -> list[RawArticle]:
        """批量分类文章。

        Args:
            articles: RawArticle 列表
            db: Database 实例

        Returns:
            已设置 category 的 RawArticle 列表（原地修改）
        """
        # 过滤掉已有分类的（从 DB 中）
        need_classify = []
        classified = []
        for a in articles:
            aid = a.compute_id()
            existing = db.get_article(aid)
            if existing and existing.category:
                # 已有分类，复用
                a._cached_category = existing.category
                classified.append(a)
            else:
                need_classify.append(a)

        if not need_classify:
            logger.info(f"[Classify] All {len(articles)} already classified")
            return articles

        logger.info(f"[Classify] Need to classify {len(need_classify)} articles")

        # 分批处理
        for i in range(0, len(need_classify), self.batch_size):
            batch = need_classify[i : i + self.batch_size]
            self._classify_batch(batch, db)

        return articles

    def _classify_batch(self, articles: list[RawArticle], db) -> None:
        """分类一批文章。"""
        # 构造输入
        article_dicts = []
        for a in articles:
            article_dicts.append({
                "id": a.compute_id(),
                "title": a.title,
                "summary": (a.raw_summary or "")[:200],
                "source": a.source_name,
            })

        articles_json = json.dumps(article_dicts, ensure_ascii=False, indent=2)

        user_prompt = self.user_template.format(
            count=len(articles),
            articles_json=articles_json,
        )

        try:
            result = self.llm_client.chat_json(self.system_prompt, user_prompt)

            # 解析结果 [{"id": "...", "category": "..."}]
            if isinstance(result, dict):
                result = [result]  # 单个结果包在列表中

            category_map = {}
            for item in result:
                if isinstance(item, dict):
                    cat_id = item.get("id", "")
                    cat = item.get("category", "").lower().strip()
                    if cat in CATEGORIES:
                        category_map[cat_id] = cat

            for a in articles:
                aid = a.compute_id()
                category = category_map.get(aid, "industry")  # 默认归为 industry
                a._cached_category = category

                # 写入数据库
                try:
                    db.update_article(aid, category=category)
                except Exception as e:
                    logger.debug(f"[Classify] DB update failed for {aid}: {e}")

            logger.debug(
                f"[Classify] Batch: {len(articles)} articles → "
                f"{len(category_map)} classified"
            )

        except Exception as e:
            logger.error(f"[Classify] Batch classification failed: {e}")
            # 失败时全部标记为 industry
            for a in articles:
                a._cached_category = "industry"
