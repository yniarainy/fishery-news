"""AI insight generator — trend analysis and commentary for weekly newsletter."""

from __future__ import annotations

import json
import logging

from src.collectors.base import RawArticle
from src.storage.models import ClusterGroup

logger = logging.getLogger(__name__)


class InsightGenerator:
    """AI 洞察生成器——分析本周新闻，生成趋势洞察和深度评论。

    输出:
    - headline_trend: 本周最显著的行业趋势
    - hot_topics: 本周热门话题 Top 5
    - rising_concerns: 值得关注的新动向
    - key_data_points: 关键数据点
    - weekly_quote: 本周精选引语
    - deep_dive_suggestion: 建议下周深度报道的话题
    """

    def __init__(self, config: dict, prompts: dict):
        self.prompts = prompts.get("insights", {})
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
    ) -> dict:
        """生成 AI 洞察。

        Args:
            articles: 已处理的文章列表
            clusters: 聚类列表
            db: Database 实例

        Returns:
            洞察 dict
        """
        if not articles:
            return {
                "headline_trend": "本周无新数据",
                "hot_topics": [],
                "rising_concerns": [],
                "key_data_points": [],
                "weekly_quote": "",
                "deep_dive_suggestion": "",
            }

        total_count = len(articles)

        # 分类分布
        category_dist = {}
        for a in articles:
            cat = getattr(a, '_cached_category', 'other') or 'other'
            category_dist[cat] = category_dist.get(cat, 0) + 1

        # 热门话题（top clusters by size）
        top_clusters = sorted(clusters, key=lambda c: len(c.articles) if hasattr(c, 'articles') else 0, reverse=True)[:5]
        top_clusters_text = ""
        for i, c in enumerate(top_clusters):
            topic = c.topic
            count = len(c.articles) if hasattr(c, 'articles') else 0
            top_clusters_text += f"{i + 1}. {topic} ({count}篇)\n"

        system_prompt = self.prompts.get("system", "")
        user_prompt = self.prompts.get("user", "").format(
            total_count=total_count,
            category_distribution=json.dumps(category_dist, ensure_ascii=False),
            top_clusters=top_clusters_text or "（本周无聚类数据）",
        )

        try:
            result = self.llm_client.chat_json(system_prompt, user_prompt)
            if isinstance(result, dict):
                return {
                    "headline_trend": result.get("headline_trend", ""),
                    "hot_topics": result.get("hot_topics", []),
                    "rising_concerns": result.get("rising_concerns", []),
                    "key_data_points": result.get("key_data_points", []),
                    "weekly_quote": result.get("weekly_quote", ""),
                    "deep_dive_suggestion": result.get("deep_dive_suggestion", ""),
                }
        except Exception as e:
            logger.error(f"[Insights] Generation failed: {e}")

        # 回退：基于规则生成基础洞察
        return self._fallback_insights(articles, category_dist, clusters)

    def _fallback_insights(
        self,
        articles: list[RawArticle],
        category_dist: dict[str, int],
        clusters: list[ClusterGroup],
    ) -> dict:
        """规则回退：当 LLM 不可用时生成基础洞察。"""
        # 热门话题 Top 5
        hot_topics = []
        for c in sorted(clusters, key=lambda x: len(x.articles) if hasattr(x, 'articles') else 0, reverse=True)[:5]:
            hot_topics.append(c.topic)

        # 最受关注的分类
        top_cat = max(category_dist, key=category_dist.get) if category_dist else "industry"
        cat_names = {
            "policy": "政策法规",
            "science": "科学研究",
            "industry": "产业动态",
            "ngo": "NGO与环保",
            "data": "数据统计",
        }

        return {
            "headline_trend": f"本周{cat_names.get(top_cat, top_cat)}领域最为活跃，"
                             f"共收录{len(articles)}篇渔业新闻",
            "hot_topics": hot_topics[:5],
            "rising_concerns": [],
            "key_data_points": [],
            "weekly_quote": "",
            "deep_dive_suggestion": "",
        }
