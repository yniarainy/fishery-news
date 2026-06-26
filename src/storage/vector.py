"""ChromaDB vector store for semantic dedup and clustering."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class VectorStore:
    """ChromaDB 向量存储封装。

    用于：
    - 文章语义去重（查重）
    - 同一事件聚类
    - 相似文章检索
    """

    def __init__(self, persist_path: str | Path = "data/chroma", collection_name: str = "fishery_articles"):
        self.persist_path = Path(persist_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self._client = None
        self._collection = None

    @property
    def client(self):
        if self._client is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self.persist_path))
        return self._client

    @property
    def collection(self):
        if self._collection is None:
            # 用 cosine 距离做语义相似度
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def add_articles(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None:
        """批量添加文章向量到 ChromaDB。

        Args:
            ids: 文章 ID 列表
            embeddings: 对应的向量列表
            metadatas: 元数据列表 (包含 title, url, published_at 等)
            documents: 用于检索的文本（title + summary）
        """
        if not ids:
            return
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    def find_duplicates(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        threshold: float = 0.92,
        n_results: int = 5,
    ) -> dict[str, list[tuple[str, float]]]:
        """查询每篇文章的潜在重复文章。

        Args:
            ids: 新文章 ID 列表
            embeddings: 新文章向量
            threshold: 相似度阈值 (0-1, 越接近 1 越严格)
            n_results: 每篇文章返回的候选数

        Returns:
            {article_id: [(duplicate_id, distance), ...]}
        """
        if not ids:
            return {}

        results = {}
        for i, (aid, emb) in enumerate(zip(ids, embeddings)):
            try:
                query_result = self.collection.query(
                    query_embeddings=[emb],
                    n_results=n_results,
                    include=["metadatas", "distances"],
                )
                dupes = []
                if query_result["ids"] and query_result["ids"][0]:
                    for dup_id, dist, meta in zip(
                        query_result["ids"][0],
                        query_result["distances"][0],
                        query_result["metadatas"][0],
                    ):
                        # cosine 距离 → 相似度 = 1 - 距离
                        similarity = 1.0 - dist
                        if dup_id != aid and similarity >= threshold:
                            dupes.append((dup_id, similarity))
                results[aid] = dupes
            except Exception:
                results[aid] = []
        return results

    def query_similar(
        self,
        embedding: list[float],
        n_results: int = 10,
    ) -> list[tuple[str, float, dict]]:
        """查找与给定向量相似的文章。

        Returns:
            [(article_id, distance, metadata), ...]
        """
        try:
            result = self.collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                include=["metadatas", "distances"],
            )
            items = []
            if result["ids"] and result["ids"][0]:
                for aid, dist, meta in zip(
                    result["ids"][0],
                    result["distances"][0],
                    result["metadatas"][0],
                ):
                    items.append((aid, dist, meta))
            return items
        except Exception:
            return []

    def query_by_ids(self, ids: list[str]) -> list[tuple[str, Any]]:
        """按 ID 查询已存储的向量和元数据。"""
        try:
            result = self.collection.get(ids=ids, include=["embeddings", "metadatas"])
            items = []
            if result["ids"]:
                for aid, emb, meta in zip(result["ids"], result["embeddings"] or [], result["metadatas"] or []):
                    items.append((aid, emb, meta))
            return items
        except Exception:
            return []

    def count(self) -> int:
        """返回当前存储的文章向量总数。"""
        try:
            return self.collection.count()
        except Exception:
            return 0

    def delete_older_than(self, days: int = 90) -> int:
        """删除超过 N 天的旧向量（限制向量库大小）。"""
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            # 查询过期文章 ID
            result = self.collection.get(include=["metadatas"])
            to_delete = []
            if result["ids"]:
                for aid, meta in zip(result["ids"], result["metadatas"]):
                    if meta and meta.get("published_at", ""):
                        if meta["published_at"] < cutoff:
                            to_delete.append(aid)
            if to_delete:
                self.collection.delete(ids=to_delete)
            return len(to_delete)
        except Exception:
            return 0
