"""Pre-filter: keyword filtering + URL dedup + language detection."""

from __future__ import annotations

import logging
import re

from src.collectors.base import RawArticle

logger = logging.getLogger(__name__)


class Prefilter:
    """预过滤器——在 LLM 处理前过滤掉明显无关的内容。

    过滤规则:
    1. 关键词黑名单（标题+摘要匹配）
    2. URL 已存在于数据库
    3. 语言不是中英文
    4. 标题为空或过短
    """

    def __init__(self, config: dict):
        prefilter_config = config.get("prefilter", {})
        self.keyword_blacklist: list[str] = prefilter_config.get("keyword_blacklist", [])
        self.allowed_languages: list[str] = prefilter_config.get("allowed_languages", ["en", "zh", "zh-cn"])

        # 编译关键词正则（不区分大小写）
        if self.keyword_blacklist:
            self._blacklist_pattern = re.compile(
                "|".join(re.escape(kw) for kw in self.keyword_blacklist),
                re.IGNORECASE,
            )
        else:
            self._blacklist_pattern = None

    def run(self, articles: list[RawArticle], db=None) -> list[RawArticle]:
        """执行预过滤。

        Args:
            articles: 原始文章列表
            db: Database 实例（用于 URL 去重查询）

        Returns:
            过滤后的文章列表
        """
        result = []
        stats = {
            "total": len(articles),
            "blacklist_filtered": 0,
            "url_duplicate": 0,
            "language_filtered": 0,
            "empty_title": 0,
        }

        # 获取最近 N 天已抓取的文章 URL（防止同一周内重复处理）
        # 注意：不做跨期去重，每期独立。同一篇文章可能在不同期出现是正常的。
        recent_urls: set[str] = set()
        if db:
            try:
                recent_urls = db.get_recent_urls(days=7)
            except Exception as e:
                logger.warning(f"Failed to get recent URLs from DB: {e}")

        for article in articles:
            # Rule 1: 标题有效性
            if not article.title or len(article.title.strip()) < 3:
                stats["empty_title"] += 1
                continue

            # Rule 2: 关键词黑名单
            text_to_check = f"{article.title} {article.raw_summary or ''}"
            if self._blacklist_pattern and self._blacklist_pattern.search(text_to_check):
                logger.debug(f"[Prefilter] Blacklisted: {article.title[:60]}...")
                stats["blacklist_filtered"] += 1
                continue

            # Rule 3: URL 去重（仅针对最近 7 天内已抓取的文章，防止同一次运行重复处理）
            if article.url and article.url in recent_urls:
                logger.debug(f"[Prefilter] URL duplicate (recent): {article.url}")
                stats["url_duplicate"] += 1
                continue

            # Rule 4: 语言检测
            if article.language and article.language.lower() not in self.allowed_languages:
                # 仅跳过明确标记为非中英文的
                if article.language.lower() not in ("en", "zh", "zh-cn", "", None):
                    stats["language_filtered"] += 1
                    continue

            result.append(article)

        logger.info(
            f"[Prefilter] {stats['total']} → {len(result)} "
            f"(blacklist: {stats['blacklist_filtered']}, "
            f"dup_url: {stats['url_duplicate']}, "
            f"lang: {stats['language_filtered']}, "
            f"empty: {stats['empty_title']})"
        )
        return result
