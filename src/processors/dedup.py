"""Deduplication using local TF-IDF embeddings + ChromaDB (fast, no API cost)."""

from __future__ import annotations

import logging

from src.collectors.base import RawArticle
from src.processors.embedder import TextEmbedder

logger = logging.getLogger(__name__)


class Deduplicator:
    """去重器 — 本地 TF-IDF 向量 + ChromaDB 语义比对。

    流程:
    1. 用 TF-IDF 为每篇文章生成本地向量（毫秒级）
    2. 在 ChromaDB 中查找最近 N 天的相似文章
    3. 余弦相似度 > threshold → 标记为重复
    4. 将新文章向量写入 ChromaDB
    5. 更新 SQLite 中的 is_duplicate 标记
    """

    def __init__(self, config: dict, db, vector_store):
        dedup_config = config.get("dedup", {})
        self.threshold: float = dedup_config.get("similarity_threshold", 0.92)
        self.lookback_days: int = dedup_config.get("lookback_days", 30)
        self.db = db
        self.vector_store = vector_store
        self.embedder = TextEmbedder()

    def run(self, articles: list[RawArticle]) -> list[RawArticle]:
        """执行去重，返回去重后的文章列表。"""
        if not articles:
            return []

        if len(articles) < 2:
            return articles

        # 1. 准备文本
        texts = []
        for a in articles:
            text = a.title or ""
            if a.raw_summary:
                text += "\n" + a.raw_summary[:300]
            texts.append(text[:600])

        # 2. 本地 TF-IDF 向量化（毫秒级）
        logger.info(f"[Dedup] Generating TF-IDF vectors for {len(texts)} articles...")
        try:
            embeddings = self.embedder.fit_transform(texts)
        except Exception as e:
            logger.error(f"[Dedup] TF-IDF failed: {e}")
            return articles

        # 3. 在 ChromaDB 中查找重复
        ids = [a.compute_id() for a in articles]
        dup_results = self.vector_store.find_duplicates(
            ids=ids, embeddings=embeddings, threshold=self.threshold, n_results=3,
        )

        # 4. 标记重复 + 写入向量库
        unique_articles = []
        duplicate_count = 0
        for article, aid, emb, text in zip(articles, ids, embeddings, texts):
            dupes = dup_results.get(aid, [])
            if dupes:
                dup_id, similarity = dupes[0]
                logger.debug(
                    f"[Dedup] Duplicate: {article.title[:50]}... sim={similarity:.3f}"
                )
                try:
                    self.db.update_article(aid, is_duplicate=True, duplicate_of=dup_id, embedding_id=aid)
                except Exception:
                    pass
                duplicate_count += 1
            else:
                unique_articles.append(article)

            # 写入向量库
            try:
                self.vector_store.add_articles(
                    ids=[aid], embeddings=[emb],
                    metadatas=[{
                        "title": article.title[:200], "url": article.url,
                        "source_id": article.source_id,
                        "published_at": article.published_at.isoformat() if article.published_at else "",
                    }],
                    documents=[text],
                )
            except Exception as e:
                logger.debug(f"[Dedup] Vector add failed for {aid}: {e}")

        logger.info(
            f"[Dedup] {len(articles)} → {len(unique_articles)} unique "
            f"({duplicate_count} duplicates at threshold={self.threshold})"
        )
        return unique_articles
