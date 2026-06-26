"""HTML scraper collector using BeautifulSoup + CSS selectors."""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseCollector, CollectorResult, RawArticle

logger = logging.getLogger(__name__)


class ScraperCollector(BaseCollector):
    """通用 HTML 爬虫采集器。

    Config keys:
        - url: 列表页 URL
        - selectors: CSS selectors
            - container: 文章容器
            - title: 标题元素
            - link: 链接元素
            - date: 日期元素 (可选)
            - summary: 摘要元素 (可选)
            - author: 作者元素 (可选)
            - image: 配图元素 (可选)
        - max_articles: 最多采集数 (默认 30)
        - user_agent: 自定义 UA
        - timeout: 请求超时秒数
    """

    def collect(self) -> CollectorResult:
        url = self.url
        selectors: dict = self.config.get("selectors", {})
        max_articles = self.config.get("max_articles", 30)
        user_agent = self.config.get("user_agent", "FisheryNewsBot/0.1")
        timeout = self.config.get("timeout", 30)

        if not selectors:
            return CollectorResult(
                source_id=self.source_id,
                success=False,
                error="No CSS selectors configured",
            )

        try:
            response = httpx.get(
                url,
                headers={"User-Agent": user_agent},
                timeout=timeout,
                follow_redirects=True,
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            containers = soup.select(selectors.get("container", "article"))

            articles = []
            for container in containers[:max_articles]:
                try:
                    title_el = container.select_one(selectors["title"]) if "title" in selectors else container
                    link_el = container.select_one(selectors["link"]) if "link" in selectors else title_el
                    date_el = container.select_one(selectors["date"]) if "date" in selectors else None
                    summary_el = container.select_one(selectors["summary"]) if "summary" in selectors else None
                    author_el = container.select_one(selectors["author"]) if "author" in selectors else None
                    image_el = container.select_one(selectors["image"]) if "image" in selectors else None

                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title:
                        continue

                    href = link_el.get("href", "") if link_el else ""
                    full_url = urljoin(url, href) if href else ""

                    # 日期解析（尝试多种格式）
                    published = None
                    if date_el:
                        date_text = date_el.get("datetime", "") or date_el.get_text(strip=True)
                        published = self._parse_date(date_text)

                    article = RawArticle(
                        source_id=self.source_id,
                        source_name=self.source_name,
                        url=full_url,
                        title=title,
                        raw_summary=summary_el.get_text(strip=True)[:500] if summary_el else None,
                        author=author_el.get_text(strip=True) if author_el else None,
                        published_at=published,
                        language=self.language,
                        image_url=image_el.get("src") if image_el else None,
                    )
                    articles.append(article)

                except Exception as e:
                    logger.debug(f"[{self.source_id}] Skipped an article: {e}")
                    continue

            logger.info(f"[{self.source_id}] Scraped {len(articles)} articles from {url}")
            return CollectorResult(source_id=self.source_id, articles=articles)

        except httpx.HTTPError as e:
            logger.error(f"[{self.source_id}] HTTP error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))
        except Exception as e:
            logger.exception(f"[{self.source_id}] Unexpected error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))

    @staticmethod
    def _parse_date(text: str) -> datetime | None:
        """尝试多种日期格式。"""
        if not text:
            return None
        from dateutil.parser import parse as dateutil_parse

        try:
            return dateutil_parse(text)
        except (ValueError, TypeError):
            pass
        return None
