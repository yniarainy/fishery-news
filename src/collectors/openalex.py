"""OpenAlex API collector — 学术论文检索。

OpenAlex 是一个开放的学术知识图谱，覆盖 2.5 亿+ 学术作品。

Fisheries-related concept IDs:
    C2781112284 = Fisheries
    C11199685  = Marine Ecology
    C29086444  = Aquaculture
    C115961366 = Ocean
    C189032762 = Fish (biology)

API 文档: https://docs.openalex.org/
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

import httpx

from .base import BaseCollector, CollectorResult, RawArticle

logger = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org/works"


class OpenAlexCollector(BaseCollector):
    """OpenAlex API 采集器 — 获取最新渔业相关论文。

    Config keys:
        - concept_ids: OpenAlex concept IDs (逗号分隔或列表)
        - max_articles: 最多返回条数
        - days_back: 回溯天数（默认 7）
        - email: 你的邮箱（OpenAlex 礼貌要求）
    """

    def collect(self) -> CollectorResult:
        api_config = self.config.get("api_config", self.config)
        max_articles = self.config.get("max_articles", 50)
        timeout = self.config.get("timeout", 30)
        email = self.config.get("email", "bot@fishery-news.dev")

        # 获取 concept IDs
        concept_filter = api_config.get("params", {}).get("filter", "")
        if not concept_filter:
            # 默认：Fisheries | Marine Ecology | Aquaculture
            concept_filter = "concepts.id:C2781112284|C11199685|C29086444"

        # 添加日期过滤（默认最近 14 天）
        from datetime import timedelta
        days_back = api_config.get("days_back", 14)
        date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        concept_filter += f",from_publication_date:{date_from}"

        params = {
            "filter": concept_filter,
            "sort": "publication_date:desc",
            "per_page": min(max_articles, 200),
            "mailto": email,
        }

        try:
            resp = httpx.get(
                OPENALEX_BASE,
                params=params,
                timeout=timeout,
                headers={"User-Agent": f"FisheryNewsBot/0.1 (mailto:{email})"},
            )
            resp.raise_for_status()
            data = resp.json()

            articles = []
            for work in data.get("results", []):
                title = work.get("title", "Untitled")
                if not title:
                    continue

                doi = work.get("doi", "")
                url = doi if doi else work.get("id", "")

                # OpenAlex 摘要使用 inverted index 格式，需要重建
                abstract = self._decode_inverted_index(
                    work.get("abstract_inverted_index")
                )

                # 作者
                authors = []
                for authorship in work.get("authorships", []):
                    author_name = authorship.get("author", {}).get("display_name", "")
                    if author_name:
                        authors.append(author_name)

                # 期刊
                journal = work.get("primary_location", {}).get("source", {}).get("display_name", "")

                # 日期
                pub_date = work.get("publication_date")

                # 概念/关键词
                concepts = [
                    c.get("display_name", "")
                    for c in work.get("concepts", [])[:5]
                ]

                summary_parts = []
                if abstract:
                    summary_parts.append(abstract[:300])
                if journal:
                    summary_parts.append(f"[{journal}]")

                article = RawArticle(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    url=url,
                    title=title,
                    raw_summary=" | ".join(summary_parts) if summary_parts else None,
                    content=abstract,
                    author=", ".join(authors[:3]) if authors else None,
                    published_at=datetime.fromisoformat(pub_date) if pub_date else None,
                    language=self.language,
                )
                articles.append(article)

            logger.info(
                f"[{self.source_id}] OpenAlex: {len(articles)} papers (filter: {concept_filter[:60]}...)"
            )
            return CollectorResult(source_id=self.source_id, articles=articles)

        except httpx.HTTPError as e:
            logger.error(f"[{self.source_id}] OpenAlex HTTP error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))
        except Exception as e:
            logger.exception(f"[{self.source_id}] OpenAlex error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))

    @staticmethod
    def _decode_inverted_index(inverted: dict | None) -> str:
        """将 OpenAlex 的 inverted index 格式解码为纯文本摘要。

        Inverted index: {"word1": [pos1, pos3], "word2": [pos2], ...}
        重建: 按位置排序 → 拼接文本。
        """
        if not inverted:
            return ""

        # 展开: (position, word)
        word_positions = []
        for word, positions in inverted.items():
            for pos in positions:
                word_positions.append((pos, word))

        # 按位置排序
        word_positions.sort(key=lambda x: x[0])

        return " ".join(w for _, w in word_positions)
