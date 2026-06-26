"""Markdown newsletter renderer using Jinja2 templates."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.storage.models import Issue, ClusterGroup

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "policy": "🏛️ 政策法规",
    "science": "🔬 科学研究",
    "industry": "🏭 产业动态",
    "ngo": "🌊 NGO与环保",
    "data": "📈 数据统计",
    "other": "📋 其他",
    "uncategorized": "📋 未分类",
}


class MarkdownRenderer:
    """周刊 Markdown 渲染器。

    使用 Jinja2 模板将结构化数据渲染为 Markdown。
    """

    def __init__(self, config: dict):
        output_config = config.get("output", {})
        self.template_name = output_config.get("newsletter_template", "weekly.md.j2")

        # 模板路径
        template_dir = Path(__file__).resolve().parent.parent.parent / "templates"
        if not template_dir.exists():
            template_dir = Path("templates")
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(
        self,
        issue: Issue,
        articles: list,
        clusters: list[ClusterGroup] | None = None,
        insights: dict | None = None,
        weekly_editorial: str = "",
    ) -> str:
        """渲染周刊为 Markdown 字符串。

        Args:
            issue: 周刊信息
            articles: 文章列表（带 _cached_* 属性）
            clusters: 聚类列表
            insights: AI 洞察 dict
            weekly_editorial: 主编按语文本

        Returns:
            Markdown 格式的周刊内容
        """
        template = self.env.get_template(self.template_name)

        # 构建分类分布（兼容 RawArticle 的 _cached_* 和 DB Article 的直接属性）
        category_dist = {}
        for a in articles:
            cat = getattr(a, '_cached_category', None) or getattr(a, 'category', None) or 'other'
            category_dist[cat] = category_dist.get(cat, 0) + 1

        # 构建模板上下文
        ctx = {
            "issue": {
                "title": issue.title,
                "number": issue.number,
                "period_start": issue.period_start,
                "period_end": issue.period_end,
                "article_count": len(articles),
            },
            "articles": [self._article_to_dict(a) for a in articles],
            "clusters": self._clusters_to_dicts(clusters or []),
            "weekly_insight": insights or {},
            "weekly_editorial": weekly_editorial,
            "category_distribution": category_dist,
            "cat_labels": CATEGORY_LABELS,
            "cat_order": [
                ("industry", "🏭 产业动态"),
                ("policy", "🏛️ 政策法规"),
                ("science", "🔬 科学研究"),
                ("ngo", "🌊 NGO与环保"),
                ("data", "📈 数据统计"),
                ("other", "📋 其他"),
            ],
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        return template.render(**ctx)

    def _article_to_dict(self, article) -> dict:
        """将 RawArticle 或 DB Article 转为模板可用的 dict。"""
        # Handle both RawArticle (_cached_* attributes) and DB Article (direct attributes)
        category = getattr(article, '_cached_category', None) or getattr(article, 'category', '') or ''
        summary = getattr(article, '_cached_summary', None) or getattr(article, 'summary_cn', '') or ''
        tags = getattr(article, '_cached_tags', None) or getattr(article, 'tags', []) or []
        entities = getattr(article, '_cached_entities', None) or getattr(article, 'entities', {}) or {}

        return {
            "source_name": getattr(article, 'source_name', ''),
            "source_id": getattr(article, 'source_id', ''),
            "title": getattr(article, 'title', ''),
            "url": getattr(article, 'url', ''),
            "summary_cn": summary,
            "raw_summary": getattr(article, 'raw_summary', '') or '',
            "category": category,
            "tags": tags if isinstance(tags, list) else [],
            "entities": entities if isinstance(entities, dict) else {},
            "author": getattr(article, 'author', '') or '',
            "published_at": str(article.published_at) if getattr(article, 'published_at', None) else "",
            "language": getattr(article, 'language', 'en'),
        }

    def _clusters_to_dicts(self, clusters: list[ClusterGroup]) -> list[dict]:
        """将 ClusterGroup 列表转为模板可用的 dict。"""
        result = []
        for c in clusters:
            articles_dict = []
            if c.articles:
                articles_dict = [self._article_to_dict(a) for a in c.articles[:5]]
            result.append({
                "topic": c.topic,
                "combined_summary": c.combined_summary,
                "articles": articles_dict,
            })
        return result
