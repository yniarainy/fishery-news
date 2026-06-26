"""Jina Reader collector — 将任意网页转为干净 Markdown，无需写 CSS selector。

Usage:
    https://r.jina.ai/http://{url} → 返回 Markdown 格式的网页正文

Config keys:
    - url: 目标网页 URL
    - jina_prefix: Jina Reader 前缀（默认 https://r.jina.ai/http://）
    - crawl_url: 如指定，用此 URL 替代 url 字段（用于信源主页 vs 具体列表页）
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

import httpx

from .base import BaseCollector, CollectorResult, RawArticle

logger = logging.getLogger(__name__)

JINA_DEFAULT_PREFIX = "https://r.jina.ai/http://"


class JinaReaderCollector(BaseCollector):
    """Jina Reader 网页采集器。

    将目标网页通过 Jina Reader 转换为干净 Markdown，
    然后从 Markdown 中提取文章列表。

    这比 BeautifulSoup + CSS selector 的方式稳定得多：
    - 不需要为每个网站写 selector
    - 自动去除广告和导航
    - 返回干净的正文 Markdown
    """

    def collect(self) -> CollectorResult:
        target_url = self.config.get("crawl_url", self.url)
        jina_prefix = self.config.get("jina_prefix", JINA_DEFAULT_PREFIX)
        max_articles = self.config.get("max_articles", 30)
        timeout = self.config.get("timeout", 30)

        jina_url = f"{jina_prefix}{target_url}"

        try:
            # Step 1: 通过 Jina Reader 获取页面 Markdown
            logger.info(f"[{self.source_id}] Jina Reader: {target_url}")
            resp = httpx.get(
                jina_url,
                headers={
                    "Accept": "text/markdown",
                    "User-Agent": "FisheryNewsBot/0.1",
                },
                timeout=timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            markdown = resp.text

            # Step 2: 从 Markdown 中提取文章链接
            articles = self._extract_articles_from_markdown(
                markdown, target_url, max_articles
            )

            logger.info(
                f"[{self.source_id}] Jina collected {len(articles)} articles from {target_url}"
            )
            return CollectorResult(source_id=self.source_id, articles=articles)

        except httpx.HTTPError as e:
            logger.error(f"[{self.source_id}] Jina HTTP error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))
        except Exception as e:
            logger.exception(f"[{self.source_id}] Jina unexpected error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))

    def _extract_articles_from_markdown(
        self, markdown: str, base_url: str, max_articles: int
    ) -> List[RawArticle]:
        """从 Jina Reader 返回的 Markdown 中提取文章列表。

        Markdown 中的链接格式: [标题](URL)
        文章通常以标题+链接的模式出现。
        """
        articles = []
        seen_urls = set()

        # 匹配 Markdown 链接: [title](url)
        link_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")

        for match in link_pattern.finditer(markdown):
            title = match.group(1).strip()
            url = match.group(2).strip()

            # 过滤导航链接、锚点、非文章链接
            if not title or len(title) < 5:
                continue
            if url in seen_urls:
                continue
            if any(skip in url.lower() for skip in [
                "javascript:", "#", "mailto:", "login", "signup",
                "twitter.com", "facebook.com", "linkedin.com",
                "rss", "/feed", "wp-content", "wp-json",
            ]):
                continue

            # 生成相对 URL
            if url.startswith("/"):
                url = urljoin(base_url, url)

            seen_urls.add(url)

            article = RawArticle(
                source_id=self.source_id,
                source_name=self.source_name,
                url=url,
                title=title,
                raw_summary=None,  # Jina 给的是全文列表，需要 LLM 摘要
                content=None,
                published_at=None,  # 列表页通常没有日期
                language=self.language,
            )
            articles.append(article)

            if len(articles) >= max_articles:
                break

        return articles


class JinaReaderFullCollector(BaseCollector):
    """Jina Reader 全文采集器 — 对单篇文章页面提取完整正文。

    用于从列表页获取到的文章 URL 逐个提取正文。
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.target_url = config.get("url", "")

    def collect(self) -> CollectorResult:
        jina_url = f"{JINA_DEFAULT_PREFIX}{self.target_url}"
        timeout = self.config.get("timeout", 30)

        try:
            resp = httpx.get(
                jina_url,
                headers={"Accept": "text/markdown"},
                timeout=timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            markdown = resp.text

            # 提取标题（第一个 # 开头的行）
            title = ""
            lines = markdown.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("# ") and not stripped.startswith("## "):
                    title = stripped[2:].strip()
                    break
            if not title and lines:
                title = lines[0].strip()[:100]

            # 正文 = 整个 Markdown
            article = RawArticle(
                source_id=self.source_id,
                source_name=self.source_name,
                url=self.target_url,
                title=title or self.target_url[:80],
                raw_summary=markdown[:500],
                content=markdown[:5000],  # 限制 5000 字符
                language=self.language,
            )

            return CollectorResult(source_id=self.source_id, articles=[article])

        except Exception as e:
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))
