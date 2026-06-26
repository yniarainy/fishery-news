"""
Fast local text embedding using TF-IDF — no API calls needed.

For news deduplication and clustering, TF-IDF is often better than
semantic embeddings because it catches exact phrase overlap (quotes,
entity names) that signal duplicate reporting of the same event.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


class TextEmbedder:
    """TF-IDF based local embedder — fast, offline, no API cost.

    Usage:
        emb = TextEmbedder()
        vectors = emb.fit_transform(texts)        # fit + transform
        vectors = emb.transform(new_texts)        # transform only (no re-fit)
    """

    def __init__(self, max_features: int = 5000):
        self.max_features = max_features
        self._vectorizer = None
        self._fitted = False

    def _get_vectorizer(self):
        if self._vectorizer is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._vectorizer = TfidfVectorizer(
                max_features=self.max_features,
                ngram_range=(1, 2),       # unigrams + bigrams
                stop_words="english",
                sublinear_tf=True,         # 1 + log(tf)
                max_df=0.8,                # ignore terms in >80% of docs
                min_df=2,                  # ignore terms in <2 docs
            )
        return self._vectorizer

    def fit_transform(self, texts: List[str]) -> List[List[float]]:
        """Fit TF-IDF on the corpus and return vectors."""
        if len(texts) < 2:
            # Single document: return uniform vector
            return [[1.0 / self.max_features] * self.max_features for _ in texts]

        vec = self._get_vectorizer()
        try:
            matrix = vec.fit_transform(texts)
            self._fitted = True
            # Convert sparse matrix to dense list
            return matrix.toarray().tolist()
        except Exception as e:
            logger.warning(f"TF-IDF fit failed: {e}, using fallback")
            return self._fallback(texts)

    def transform(self, texts: List[str]) -> List[List[float]]:
        """Transform new texts using fitted vocabulary."""
        if not self._fitted or self._vectorizer is None:
            return self.fit_transform(texts)

        try:
            matrix = self._vectorizer.transform(texts)
            return matrix.toarray().tolist()
        except Exception:
            return self._fallback(texts)

    def _fallback(self, texts: List[str]) -> List[List[float]]:
        """Simple character n-gram fallback when TF-IDF fails."""
        import hashlib
        vectors = []
        for text in texts:
            # Character trigram hashing → 256-dim vector
            vec = [0.0] * 256
            text_lower = text.lower()
            for i in range(len(text_lower) - 2):
                trigram = text_lower[i:i+3]
                h = int(hashlib.md5(trigram.encode()).hexdigest()[:2], 16)
                vec[h] += 1.0
            # Normalize
            total = sum(vec) or 1.0
            vectors.append([v / total for v in vec])
        return vectors


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x ** 2 for x in a) ** 0.5
    norm_b = sum(x ** 2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
