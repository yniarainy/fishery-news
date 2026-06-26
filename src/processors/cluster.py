"""Event clustering: group articles about the same event/topic."""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

from src.collectors.base import RawArticle
from src.storage.models import ClusterGroup

logger = logging.getLogger(__name__)


class Clusterer:
    """事件聚类器——将关于同一事件的报道归为一组。

    策略:
    1. 为新文章生成 embedding
    2. 在 ChromaDB 中查找相似文章
    3. 用 DBSCAN 式相似度聚类
    4. 生成 cluster_id 并更新 DB
    """

    def __init__(self, config: dict, vector_store):
        cluster_config = config.get("cluster", {})
        self.threshold: float = cluster_config.get("similarity_threshold", 0.82)
        self.min_cluster_size: int = cluster_config.get("min_cluster_size", 1)
        self.vector_store = vector_store
        from src.processors.embedder import TextEmbedder
        self.embedder = TextEmbedder()

    def run(self, articles: list[RawArticle]) -> list[ClusterGroup]:
        """将文章聚类为事件组。

        Args:
            articles: 已去重的文章列表

        Returns:
            ClusterGroup 列表
        """
        if not articles:
            return []

        if len(articles) <= 1:
            # 单篇文章自成一组
            cluster_id = self._make_cluster_id([articles[0].compute_id()])
            return [ClusterGroup(
                cluster_id=cluster_id,
                articles=[],
                main_article=None,
                topic=articles[0].title,
            )]

        # 1. 生成 embeddings
        texts = []
        for a in articles:
            text = f"{a.title}\n{a.raw_summary or ''}"[:600]
            texts.append(text)

        try:
            embeddings = self.embedder.fit_transform(texts)
        except Exception as e:
            logger.error(f"[Cluster] Embedding failed: {e}")
            # 全部归入一个默认聚类
            cid = self._make_cluster_id([a.compute_id() for a in articles])
            return [ClusterGroup(cluster_id=cid, articles=[], topic="本周新闻")]

        # 2. 计算成对余弦相似度并构建邻接图
        ids = [a.compute_id() for a in articles]
        n = len(ids)
        graph: dict[int, list[int]] = defaultdict(list)

        for i in range(n):
            for j in range(i + 1, n):
                sim = self._cosine_sim(embeddings[i], embeddings[j])
                if sim >= self.threshold:
                    graph[i].append(j)
                    graph[j].append(i)

        # 3. 连通分量算法找聚类
        visited = set()
        clusters_indices: list[list[int]] = []

        for i in range(n):
            if i in visited:
                continue
            # BFS
            component = []
            queue = [i]
            while queue:
                node = queue.pop()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                for neighbor in graph[node]:
                    if neighbor not in visited:
                        queue.append(neighbor)
            clusters_indices.append(component)

        # 4. 构建 ClusterGroup
        clusters = []
        for component in clusters_indices:
            cluster_articles = [articles[i] for i in component]
            cluster_ids = [ids[i] for i in component]
            cluster_id = self._make_cluster_id(cluster_ids)

            # 选代表文章（标题最长的，含信息量通常最大）
            main = max(cluster_articles, key=lambda a: len(a.title))

            # 生成话题标签
            topic = self._generate_topic(cluster_articles)

            cluster = ClusterGroup(
                cluster_id=cluster_id,
                articles=[],
                main_article=None,
                topic=topic,
            )
            clusters.append(cluster)

        logger.info(
            f"[Cluster] {len(articles)} articles → {len(clusters)} clusters "
            f"(threshold={self.threshold})"
        )
        return clusters

    def _cosine_sim(self, a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x ** 2 for x in a) ** 0.5
        norm_b = sum(x ** 2 for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _make_cluster_id(self, article_ids: list[str]) -> str:
        """从文章 ID 列表生成聚类 ID。"""
        raw = "|".join(sorted(article_ids))
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _generate_topic(self, articles: list[RawArticle]) -> str:
        """为聚类生成简短的话题标签。使用规则而非 LLM（节省成本）。"""
        titles = [a.title for a in articles]

        # 简单策略：用最常出现的词作为话题
        from collections import Counter
        import re

        all_words = []
        for title in titles:
            # 提取大写字母开头的词（通常为实体名）
            words = re.findall(r"\b[A-Z][a-z]{3,}\b", title)
            all_words.extend(words)

        if all_words:
            counter = Counter(all_words)
            top_words = [w for w, c in counter.most_common(3) if c > 1]
            if top_words:
                return " / ".join(top_words)
            # 单个词不够，用最常见词
            return counter.most_common(1)[0][0]

        # 回退：用第一个标题的前几个词
        return titles[0][:60]
